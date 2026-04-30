import asyncio
import base64
import json
import os
import re
import shutil
import threading
import time
import uuid
from typing import Any, Dict, Optional, Tuple

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.api.auth import get_current_user, get_current_user_optional
from app.core.config import resolve_path
from app.rag.pipeline import ScenicRAGPipeline
from app.services.asr_tts import asr_service, tts_service
from app.services.avatar_engine import avatar_engine
from app.services.log_service import log_service

router = APIRouter()

TEMP_DIR = resolve_path("SoulX-FlashHead/data/temp")
os.makedirs(TEMP_DIR, exist_ok=True)

_pipeline_cache: Optional[ScenicRAGPipeline] = None
EMPTY_ASR_RESULTS = {"（没有听到声音）", "（语音识别失败）", "（未听清）"}
SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？!?；;])")


class TextInteractRequest(BaseModel):
    text: str


def get_pipeline() -> ScenicRAGPipeline:
    global _pipeline_cache
    if _pipeline_cache is None:
        _pipeline_cache = ScenicRAGPipeline()
    return _pipeline_cache


def clean_markdown_for_tts(text: str) -> str:
    import markdown
    from bs4 import BeautifulSoup

    html = markdown.markdown(text)
    soup = BeautifulSoup(html, "html.parser")
    plain_text = soup.get_text()
    emoji_pattern = re.compile(
        r"["  # remove emojis while preserving Chinese text
        r"\U0001f600-\U0001f64f"
        r"\U0001f300-\U0001f5ff"
        r"\U0001f680-\U0001f6ff"
        r"\U0001f1e0-\U0001f1ff"
        r"]+",
        flags=re.UNICODE,
    )
    return emoji_pattern.sub("", plain_text).strip()


def is_valid_user_text(text: str) -> bool:
    return bool(text.strip()) and text not in EMPTY_ASR_RESULTS


def apply_gps_fallback(user_text: str, answer: str, gps_status: str, intent: str) -> str:
    if gps_status != "weak":
        return answer
    if intent != "FACT":
        return answer
    if not any(keyword in user_text for keyword in ("位置", "在哪", "哪里", "怎么走", "路线", "导航")):
        return answer
    return (
        "当前 GPS 信号较弱，我还不能准确判断您的位置。"
        "请您先描述一下附近最显眼的建筑、佛像、广场或桥梁，我再结合灵山景点资料继续帮您判断路线。"
    )


def split_sentences(text: str) -> list[str]:
    stripped = text.strip()
    if not stripped:
        return []
    parts = [part.strip() for part in SENTENCE_SPLIT_RE.split(stripped) if part.strip()]
    return parts or [stripped]


def synthesize_chunk_payload(text: str) -> Optional[Dict[str, Any]]:
    clean_text = clean_markdown_for_tts(text)
    if not clean_text or not re.search(r"[\w\u4e00-\u9fa5]", clean_text):
        return None

    sentence_id = str(uuid.uuid4())
    audio_path = os.path.join(TEMP_DIR, f"{sentence_id}.mp3")
    tts_service.synthesize(clean_text, audio_path)

    if not os.path.exists(audio_path) or os.path.getsize(audio_path) == 0:
        return None

    with open(audio_path, "rb") as file_obj:
        audio_b64 = base64.b64encode(file_obj.read()).decode("utf-8")

    frames = avatar_engine.generate_avatar_stream(audio_path, is_file_path=True)
    frames_b64 = [base64.b64encode(frame).decode("utf-8") for frame in frames]
    return {"audio": audio_b64, "frames": frames_b64}


def run_answer_pipeline(user_text: str, gps_status: str) -> Tuple[str, Dict[str, Any]]:
    result = get_pipeline().process_query(user_text)
    answer = apply_gps_fallback(user_text, result["answer"], gps_status, result["intent"])
    return answer, result


def generate_avatar_response(
    user_text: str,
    username: str = "anonymous",
    gps_status: str = "normal",
) -> Dict[str, Any]:
    start_time = time.time()

    if not is_valid_user_text(user_text):
        return {
            "user_text": user_text,
            "assistant_text": "抱歉，我没有听清您说的内容，您可以再说一遍吗？",
            "audio_url": None,
            "video_stream_url": None,
            "rag_metadata": {
                "intent": "FACT",
                "agent_type": "invalid_input",
                "matched_attraction": None,
                "recommendation_label": None,
                "response_kind": "invalid_input",
            },
        }

    assistant_text, pipeline_result = run_answer_pipeline(user_text, gps_status)

    request_id = str(uuid.uuid4())
    audio_output_path = os.path.join(TEMP_DIR, f"{request_id}.mp3")
    video_output_path = os.path.join(TEMP_DIR, f"{request_id}_video.mp4")

    audio_ready = False
    try:
        clean_text_for_tts = clean_markdown_for_tts(assistant_text)
        if clean_text_for_tts and re.search(r"[\w\u4e00-\u9fa5]", clean_text_for_tts):
            tts_error = []

            def run_tts() -> None:
                try:
                    tts_service.synthesize(clean_text_for_tts, audio_output_path)
                except Exception as exc:  # pragma: no cover - runtime environment dependent
                    tts_error.append(exc)

            tts_thread = threading.Thread(target=run_tts)
            tts_thread.start()
            tts_thread.join()
            if tts_error:
                raise tts_error[0]
            audio_ready = os.path.exists(audio_output_path) and os.path.getsize(audio_output_path) > 0
    except Exception as exc:  # pragma: no cover - runtime environment dependent
        print(f"[TTS] synthesis failed: {exc}")
        audio_ready = False

    video_ready = False
    if audio_ready:
        try:
            success_path = avatar_engine.generate_avatar_video(audio_output_path, video_output_path)
            video_ready = bool(success_path and os.path.exists(video_output_path))
        except Exception as exc:  # pragma: no cover - runtime environment dependent
            print(f"[AvatarEngine] video generation failed: {exc}")
            video_ready = False

    latency = time.time() - start_time
    print(f"[Multimodal] processed in {latency:.2f}s via {pipeline_result['intent']}")

    return {
        "user_text": user_text,
        "assistant_text": assistant_text,
        "audio_url": f"/static/temp/{request_id}.mp3" if audio_ready else None,
        "video_stream_url": f"/static/temp/{request_id}_video.mp4" if video_ready else None,
        "rag_metadata": {
            "intent": pipeline_result["intent"],
            "agent_type": pipeline_result["agent_type"],
            "matched_attraction": pipeline_result.get("matched_attraction"),
            "recommendation_label": pipeline_result.get("recommendation_label"),
            "response_kind": pipeline_result.get("response_kind"),
        },
    }


@router.websocket("/v1/interact/stream")
async def interact_stream_ws(websocket: WebSocket):
    await websocket.accept()

    try:
        while True:
            payload = json.loads(await websocket.receive_text())

            if "avatar_image" in payload:
                image_bytes = base64.b64decode(payload["avatar_image"])
                image_req_id = str(uuid.uuid4())
                image_path = os.path.join(TEMP_DIR, f"{image_req_id}_avatar.jpg")
                with open(image_path, "wb") as file_obj:
                    file_obj.write(image_bytes)
                avatar_engine.update_base_image(image_path)

            user_text = ""
            is_audio_input = False
            gps_status = payload.get("gps_status", "normal")

            if "text" in payload:
                user_text = payload["text"]
            elif "audio" in payload:
                is_audio_input = True
                audio_bytes = base64.b64decode(payload["audio"])
                request_id = str(uuid.uuid4())
                temp_audio_path = os.path.join(TEMP_DIR, f"{request_id}_ws_input.webm")
                with open(temp_audio_path, "wb") as file_obj:
                    file_obj.write(audio_bytes)
                try:
                    asr_result = asr_service.transcribe(temp_audio_path)
                    user_text = asr_result.strip() if isinstance(asr_result, str) else str(asr_result)
                    if not user_text:
                        user_text = "（没有听到声音）"
                except Exception:
                    user_text = "（语音识别失败）"

            if not is_valid_user_text(user_text):
                await websocket.send_json({"type": "error", "message": "未识别到有效语音或文本。"})
                continue

            if is_audio_input:
                await websocket.send_json({"type": "text_user", "text": user_text})

            assistant_text, pipeline_result = run_answer_pipeline(user_text, gps_status)

            for char in assistant_text:
                await websocket.send_json({"type": "text_token", "text": char})

            for sentence in split_sentences(assistant_text):
                payload_chunk = await asyncio.to_thread(synthesize_chunk_payload, sentence)
                if payload_chunk:
                    await websocket.send_json({"type": "chunk", **payload_chunk})

            await websocket.send_json({"type": "done", "full_text": assistant_text})

            try:
                log_service.analyze_and_log(
                    user_query=user_text,
                    ai_response=assistant_text,
                    cost_time=0.0,
                    username="ws_user",
                    metadata={
                        "query_scope": pipeline_result["intent"],
                        "matched_attraction": pipeline_result.get("matched_attraction"),
                        "recommendation_label": pipeline_result.get("recommendation_label"),
                    },
                )
            except Exception as exc:
                print(f"[API] failed to log websocket interaction: {exc}")

    except WebSocketDisconnect:
        print("[API] WebSocket disconnected")
    except Exception as exc:
        print(f"[API] WebSocket error: {exc}")
        try:
            await websocket.send_json({"type": "error", "message": f"系统错误: {exc}"})
        except Exception:
            pass


@router.post("/v1/interact/audio")
async def interact_audio(
    background_tasks: BackgroundTasks,
    audio: UploadFile = File(...),
    avatar_image: Optional[UploadFile] = File(None),
    gps_status: str = Form("normal"),
    current_user: Optional[Dict[str, Any]] = Depends(get_current_user_optional),
):
    api_start_time = time.time()
    request_id = str(uuid.uuid4())
    username = current_user["username"] if current_user else "anonymous"

    if avatar_image:
        image_path = os.path.join(TEMP_DIR, f"{request_id}_avatar.jpg")
        with open(image_path, "wb") as buffer:
            shutil.copyfileobj(avatar_image.file, buffer)
        avatar_engine.update_base_image(image_path)

    temp_audio_path = os.path.join(TEMP_DIR, f"{request_id}_input.webm")
    with open(temp_audio_path, "wb") as buffer:
        shutil.copyfileobj(audio.file, buffer)

    try:
        asr_result = asr_service.transcribe(temp_audio_path)
        user_text = asr_result.strip() if isinstance(asr_result, str) else str(asr_result)
        if not user_text:
            user_text = "（没有听到声音）"
    except Exception:
        user_text = "（语音识别失败）"

    result = generate_avatar_response(user_text, username, gps_status)

    total_latency = time.time() - api_start_time
    background_tasks.add_task(
        log_service.analyze_and_log,
        user_query=user_text,
        ai_response=result.get("assistant_text", ""),
        cost_time=total_latency,
        username=username,
        metadata={
            "query_scope": result.get("rag_metadata", {}).get("intent"),
            "matched_attraction": result.get("rag_metadata", {}).get("matched_attraction"),
            "recommendation_label": result.get("rag_metadata", {}).get("recommendation_label"),
        },
    )

    return JSONResponse(content=result)


@router.post("/v1/interact/text")
async def interact_text(
    background_tasks: BackgroundTasks,
    text: str = Form(...),
    avatar_image: Optional[UploadFile] = File(None),
    gps_status: str = Form("normal"),
    current_user: Optional[Dict[str, Any]] = Depends(get_current_user_optional),
):
    api_start_time = time.time()
    username = current_user["username"] if current_user else "anonymous"

    if avatar_image:
        request_id = str(uuid.uuid4())
        image_path = os.path.join(TEMP_DIR, f"{request_id}_avatar.jpg")
        with open(image_path, "wb") as buffer:
            shutil.copyfileobj(avatar_image.file, buffer)
        avatar_engine.update_base_image(image_path)

    result = generate_avatar_response(text, username, gps_status)

    total_latency = time.time() - api_start_time
    background_tasks.add_task(
        log_service.analyze_and_log,
        user_query=text,
        ai_response=result.get("assistant_text", ""),
        cost_time=total_latency,
        username=username,
        metadata={
            "query_scope": result.get("rag_metadata", {}).get("intent"),
            "matched_attraction": result.get("rag_metadata", {}).get("matched_attraction"),
            "recommendation_label": result.get("rag_metadata", {}).get("recommendation_label"),
        },
    )

    return JSONResponse(content=result)


@router.get("/v1/interact/profile")
async def get_profile(current_user: Dict[str, Any] = Depends(get_current_user)):
    profile = log_service.get_user_profile(current_user["username"])
    return JSONResponse(content={"profile": profile})


@router.get("/v1/interact/history")
async def get_history(
    limit: int = 50,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    history = log_service.get_user_history(current_user["username"], limit=limit)
    return JSONResponse(content={"history": history})
