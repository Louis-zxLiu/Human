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

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.api.auth import get_current_user, get_current_user_optional
from app.core.config import resolve_path
from app.rag.location_agent import ScenicLocationAgent
from app.rag.pipeline import ScenicRAGPipeline
from app.rag.router import get_query_intent
from app.services.asr_tts import get_asr_service, get_tts_service
from app.services.avatar_engine import get_avatar_engine
from app.services.log_service import log_service
from app.services.preset_route_cache import preset_route_cache

router = APIRouter()

TEMP_DIR = resolve_path("SoulX-FlashHead/data/temp")
os.makedirs(TEMP_DIR, exist_ok=True)

_pipeline_cache: Optional[ScenicRAGPipeline] = None
_location_agent_cache: Optional[ScenicLocationAgent] = None
INVALID_INPUTS = {"（没有听到声音）", "（语音识别失败）", "（未听清）"}
SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？!?；;])")
WEAK_GPS_SESSIONS: Dict[str, Dict[str, Any]] = {}


class TextInteractRequest(BaseModel):
    text: str


def get_pipeline() -> ScenicRAGPipeline:
    global _pipeline_cache
    if _pipeline_cache is None:
        _pipeline_cache = ScenicRAGPipeline()
    return _pipeline_cache


def get_location_agent() -> ScenicLocationAgent:
    global _location_agent_cache
    if _location_agent_cache is None:
        _location_agent_cache = ScenicLocationAgent(get_pipeline().fact_agent)
    return _location_agent_cache


def clear_runtime_cache() -> None:
    global _pipeline_cache, _location_agent_cache
    _pipeline_cache = None
    _location_agent_cache = None


def _build_rag_metadata(
    pipeline_result: Dict[str, Any],
    scenic_slug: Optional[str] = None,
    attraction_id: Optional[str] = None,
    route_label: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "intent": pipeline_result["intent"],
        "query_scope": pipeline_result["intent"],
        "agent_type": pipeline_result["agent_type"],
        "matched_attraction": pipeline_result.get("matched_attraction"),
        "recommendation_label": pipeline_result.get("recommendation_label"),
        "response_kind": pipeline_result.get("response_kind"),
        "recommendation": pipeline_result.get("recommendation"),
        "gps_state": pipeline_result.get("gps_state"),
        "gps_candidates": pipeline_result.get("gps_candidates", []),
        "scenic_slug": scenic_slug,
        "attraction_id": attraction_id,
        "route_label": route_label,
        "preset_route_key": pipeline_result.get("preset_route_key"),
        "preset_route_title": pipeline_result.get("preset_route_title"),
        "cache_status": pipeline_result.get("cache_status"),
        "plan": pipeline_result.get("plan"),
        "evidence": pipeline_result.get("evidence", []),
        "refusal": pipeline_result.get("refusal"),
        "warnings": pipeline_result.get("warnings", []),
        "observability": pipeline_result.get("observability"),
    }


def _build_log_metadata(
    pipeline_result: Dict[str, Any],
    scenic_slug: Optional[str] = None,
    attraction_id: Optional[str] = None,
    route_label: Optional[str] = None,
) -> Dict[str, Any]:
    metadata = _build_rag_metadata(pipeline_result, scenic_slug=scenic_slug, attraction_id=attraction_id, route_label=route_label)
    metadata["query_scope"] = pipeline_result["intent"]
    return metadata


def clean_markdown_for_tts(text: str) -> str:
    import markdown
    from bs4 import BeautifulSoup

    html = markdown.markdown(text)
    soup = BeautifulSoup(html, "html.parser")
    plain_text = soup.get_text()
    emoji_pattern = re.compile(
        r"["
        r"\U0001f600-\U0001f64f"
        r"\U0001f300-\U0001f5ff"
        r"\U0001f680-\U0001f6ff"
        r"\U0001f1e0-\U0001f1ff"
        r"]+",
        flags=re.UNICODE,
    )
    return emoji_pattern.sub("", plain_text).strip()


def _select_avatar_response_text(
    assistant_text: str,
    pipeline_result: Dict[str, Any],
    prefer_compact_recommendation: bool,
) -> str:
    compact_mode = True
    recommendation = pipeline_result.get("recommendation") or {}
    compact_answer = str(recommendation.get("compact_answer") or "").strip()
    response_kind = str(pipeline_result.get("response_kind") or "")
    if compact_answer and (prefer_compact_recommendation or response_kind == "recommendation"):
        return compact_answer
    if not compact_mode:
        return assistant_text
    return _compact_response_text(assistant_text, response_kind=response_kind)


def _compact_response_text(text: str, response_kind: str = "") -> str:
    normalized = " ".join(str(text or "").split())
    if not normalized:
        return normalized

    if response_kind.startswith("comparison:"):
        lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
        compact_lines = [_truncate_line(line, 56) for line in lines[:3]]
        return "\n".join(compact_lines)

    if response_kind in {"overview", "history", "docx_general", "rag_answer", "rag_general", "rag_fallback"}:
        return _compact_sentences(normalized, max_sentences=2, max_chars=110)

    if response_kind.startswith("field:"):
        return _compact_labeled_answer(normalized, max_chars=95)

    if response_kind.startswith("refused") or response_kind in {"invalid_input", "gps:awaiting_landmarks"}:
        return _compact_sentences(normalized, max_sentences=2, max_chars=88)

    if response_kind.startswith("gps:"):
        return _compact_sentences(normalized, max_sentences=2, max_chars=96)

    return _compact_sentences(normalized, max_sentences=2, max_chars=100)


def _compact_labeled_answer(text: str, max_chars: int) -> str:
    if "：" not in text:
        return _compact_sentences(text, max_sentences=2, max_chars=max_chars)
    prefix, value = text.split("：", 1)
    head = f"{prefix.strip()}："
    remain = max(max_chars - len(head), 24)
    return head + _truncate_line(value.strip(), remain)


def _compact_sentences(text: str, max_sentences: int, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text

    parts = split_sentences(text)
    chosen: list[str] = []
    total = 0
    for part in parts:
        candidate_len = total + len(part)
        if chosen and (len(chosen) >= max_sentences or candidate_len > max_chars):
            break
        chosen.append(part)
        total = candidate_len
        if total >= max_chars:
            break

    if chosen:
        compact = "".join(chosen).strip()
        if len(compact) >= len(text):
            return compact
        return _truncate_line(compact, max_chars)
    return _truncate_line(text, max_chars)


def _truncate_line(text: str, max_chars: int) -> str:
    normalized = " ".join(str(text or "").split())
    if len(normalized) <= max_chars:
        return normalized
    clipped = normalized[: max(0, max_chars - 3)].rstrip("，,；;、 ")
    return f"{clipped}..."


def is_valid_user_text(text: str) -> bool:
    return bool(text.strip()) and text not in INVALID_INPUTS


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

    tts_service = get_tts_service()
    avatar_engine = get_avatar_engine()
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


def get_session_key(username: str, client_session_id: Optional[str], fallback: Optional[str] = None) -> str:
    if client_session_id:
        return f"session:{client_session_id}"
    if username and username != "anonymous":
        return f"user:{username}"
    return fallback or "anonymous"


def should_enter_weak_gps_flow(user_text: str, gps_status: str, intent: str) -> bool:
    if gps_status != "weak":
        return False
    location_agent = get_location_agent()
    if location_agent.is_navigation_query(user_text):
        return True
    return intent == "RECOMMEND" and any(keyword in user_text for keyword in ("从这里", "当前位置", "附近"))


def pop_weak_gps_context(session_key: str) -> Optional[Dict[str, Any]]:
    return WEAK_GPS_SESSIONS.pop(session_key, None)


def set_weak_gps_context(session_key: str, context: Dict[str, Any]) -> None:
    WEAK_GPS_SESSIONS[session_key] = context


def handle_weak_gps_flow(
    user_text: str,
    gps_status: str,
    session_key: str,
    user_profile: Optional[str],
    scenic_slug: Optional[str] = None,
    attraction_id: Optional[str] = None,
) -> Optional[Tuple[str, Dict[str, Any]]]:
    if gps_status != "weak":
        pop_weak_gps_context(session_key)
        return None

    pipeline = get_pipeline()
    location_agent = get_location_agent()
    pending = WEAK_GPS_SESSIONS.get(session_key)

    if pending:
        candidates = location_agent.infer_candidates(user_text, scenic_slug=pending.get("scenic_slug"))
        gps_result = location_agent.build_candidate_reply(candidates, pending["original_query"])
        base_metadata = {
            "query": pending["original_query"],
            "intent": pending["original_intent"],
            "agent_type": "weak_gps_location",
            "matched_attraction": gps_result.get("resolved_attraction"),
            "recommendation_label": None,
            "response_kind": f"gps:{gps_result['gps_state']}",
            "recommendation": None,
            "gps_state": gps_result["gps_state"],
            "gps_candidates": gps_result.get("candidate_names", []),
        }

        if gps_result["gps_state"] != "resolved":
            set_weak_gps_context(session_key, pending)
            return gps_result["answer"], base_metadata

        current_attraction = gps_result["resolved_attraction"]
        pop_weak_gps_context(session_key)

        if pending["original_intent"] == "RECOMMEND":
            recommendation_result = pipeline.process_query(
                pending["original_query"],
                user_profile=user_profile,
                start_attraction=current_attraction,
                scenic_slug=pending.get("scenic_slug"),
                attraction_id=pending.get("attraction_id"),
            )
            recommendation_result["agent_type"] = "weak_gps_recommendation"
            recommendation_result["matched_attraction"] = current_attraction
            recommendation_result["response_kind"] = "gps:resolved_recommendation"
            recommendation_result["gps_state"] = "resolved"
            recommendation_result["gps_candidates"] = gps_result.get("candidate_names", [])
            answer = gps_result["answer"] + "\n" + recommendation_result["answer"]
            recommendation_result["answer"] = answer
            return answer, recommendation_result

        return gps_result["answer"], base_metadata

    original_intent = get_query_intent(user_text)
    if not should_enter_weak_gps_flow(user_text, gps_status, original_intent):
        return None

    set_weak_gps_context(
        session_key,
        {
            "original_query": user_text,
            "original_intent": original_intent,
            "created_at": time.time(),
            "scenic_slug": scenic_slug,
            "attraction_id": attraction_id,
        },
    )
    answer = location_agent.build_follow_up_prompt()
    return answer, {
        "query": user_text,
        "intent": original_intent,
        "agent_type": "weak_gps_prompt",
        "matched_attraction": None,
        "recommendation_label": None,
        "response_kind": "gps:awaiting_landmarks",
        "recommendation": None,
        "gps_state": "awaiting_landmarks",
        "gps_candidates": [],
    }


def run_answer_pipeline(
    user_text: str,
    gps_status: str,
    session_key: str,
    user_profile: Optional[str] = None,
    scenic_slug: Optional[str] = None,
    attraction_id: Optional[str] = None,
) -> Tuple[str, Dict[str, Any]]:
    gps_result = handle_weak_gps_flow(
        user_text,
        gps_status,
        session_key,
        user_profile,
        scenic_slug=scenic_slug,
        attraction_id=attraction_id,
    )
    if gps_result:
        return gps_result

    result = get_pipeline().process_query(
        user_text,
        user_profile=user_profile,
        scenic_slug=scenic_slug,
        attraction_id=attraction_id,
    )
    result["gps_state"] = "normal" if gps_status != "weak" else "weak_without_followup"
    result["gps_candidates"] = []
    return result["answer"], result


def _generate_fresh_avatar_response(
    user_text: str,
    username: str = "anonymous",
    gps_status: str = "normal",
    client_session_id: Optional[str] = None,
    scenic_slug: Optional[str] = None,
    attraction_id: Optional[str] = None,
    route_label: Optional[str] = None,
    prefer_compact_recommendation: bool = False,
) -> Dict[str, Any]:
    start_time = time.time()
    session_key = get_session_key(username, client_session_id)
    user_profile = log_service.get_user_profile(username) if username and username != "anonymous" else None

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
                "recommendation": None,
                "gps_state": "invalid_input",
                "gps_candidates": [],
            },
        }

    assistant_text, pipeline_result = run_answer_pipeline(
        user_text,
        gps_status,
        session_key=session_key,
        user_profile=user_profile,
        scenic_slug=scenic_slug,
        attraction_id=attraction_id,
    )
    assistant_text = _select_avatar_response_text(
        assistant_text,
        pipeline_result,
        prefer_compact_recommendation=prefer_compact_recommendation,
    )

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
                    tts_service = get_tts_service()
                    tts_service.synthesize(clean_text_for_tts, audio_output_path)
                except Exception as exc:
                    tts_error.append(exc)

            tts_thread = threading.Thread(target=run_tts)
            tts_thread.start()
            tts_thread.join()
            if tts_error:
                raise tts_error[0]
            audio_ready = os.path.exists(audio_output_path) and os.path.getsize(audio_output_path) > 0
    except Exception as exc:
        print(f"[TTS] synthesis failed: {exc}")
        audio_ready = False

    video_ready = False
    if audio_ready:
        try:
            avatar_engine = get_avatar_engine()
            success_path = avatar_engine.generate_avatar_video(audio_output_path, video_output_path)
            video_ready = bool(success_path and os.path.exists(video_output_path))
        except Exception as exc:
            print(f"[AvatarEngine] video generation failed: {exc}")
            video_ready = False

    latency = time.time() - start_time
    print(f"[Multimodal] processed in {latency:.2f}s via {pipeline_result['intent']}")

    return {
        "user_text": user_text,
        "assistant_text": assistant_text,
        "audio_url": f"/static/temp/{request_id}.mp3" if audio_ready else None,
        "video_stream_url": f"/static/temp/{request_id}_video.mp4" if video_ready else None,
        "rag_metadata": _build_rag_metadata(
            pipeline_result,
            scenic_slug=scenic_slug,
            attraction_id=attraction_id,
            route_label=route_label,
        ),
    }


def _apply_preset_route_metadata(
    result: Dict[str, Any],
    preset_route: Dict[str, str],
    cache_status: str,
) -> Dict[str, Any]:
    rag_metadata = dict(result.get("rag_metadata") or {})
    rag_metadata["preset_route_key"] = preset_route["key"]
    rag_metadata["preset_route_title"] = preset_route["title"]
    rag_metadata["cache_status"] = cache_status
    result["rag_metadata"] = rag_metadata
    return result


def generate_avatar_response(
    user_text: str,
    username: str = "anonymous",
    gps_status: str = "normal",
    client_session_id: Optional[str] = None,
    scenic_slug: Optional[str] = None,
    attraction_id: Optional[str] = None,
    route_label: Optional[str] = None,
    preset_route_key: Optional[str] = None,
) -> Dict[str, Any]:
    preset_route = preset_route_cache.resolve_route(
        user_text,
        scenic_slug=scenic_slug,
        preset_route_key=preset_route_key,
    )
    if not preset_route:
        return _generate_fresh_avatar_response(
            user_text,
            username,
            gps_status,
            client_session_id=client_session_id,
            scenic_slug=scenic_slug,
            attraction_id=attraction_id,
            route_label=route_label,
        )

    payload = preset_route_cache.get_or_create_payload(
        preset_route,
        lambda route: _generate_fresh_avatar_response(
            route["prompt"],
            username,
            gps_status,
            client_session_id=client_session_id,
            scenic_slug=route["scenic_slug"],
            attraction_id=attraction_id,
            route_label=route_label or route["title"],
            prefer_compact_recommendation=True,
        ),
    )
    result = {
        "user_text": user_text,
        "assistant_text": payload.get("assistant_text", ""),
        "audio_url": payload.get("audio_url"),
        "video_stream_url": payload.get("video_stream_url"),
        "rag_metadata": payload.get("rag_metadata") or {},
    }
    cache_status = "hit" if payload.get("cache_hit") else "generated"
    return _apply_preset_route_metadata(result, preset_route, cache_status)


def refresh_preset_route_cache() -> Dict[str, int]:
    refreshed = 0
    failed = 0
    for route in preset_route_cache.list_routes():
        try:
            preset_route_cache.get_or_create_payload(
                route,
                lambda current_route: _generate_fresh_avatar_response(
                    current_route["prompt"],
                    username="system",
                    gps_status="normal",
                    scenic_slug=current_route["scenic_slug"],
                    route_label=current_route["title"],
                    prefer_compact_recommendation=True,
                ),
            )
            refreshed += 1
        except Exception as exc:
            failed += 1
            print(f"[PresetRouteCache] refresh failed for {route['key']}: {exc}")
    return {"refreshed": refreshed, "failed": failed}


def refresh_preset_route_cache_in_background() -> None:
    thread = threading.Thread(target=refresh_preset_route_cache, daemon=True)
    thread.start()


@router.websocket("/v1/interact/stream")
async def interact_stream_ws(websocket: WebSocket):
    await websocket.accept()
    ws_session_key = f"ws:{uuid.uuid4()}"

    try:
        while True:
            payload = json.loads(await websocket.receive_text())

            if "avatar_image" in payload:
                image_bytes = base64.b64decode(payload["avatar_image"])
                image_req_id = str(uuid.uuid4())
                image_path = os.path.join(TEMP_DIR, f"{image_req_id}_avatar.jpg")
                with open(image_path, "wb") as file_obj:
                    file_obj.write(image_bytes)
                avatar_engine = get_avatar_engine()
                avatar_engine.update_base_image(image_path)

            user_text = ""
            is_audio_input = False
            gps_status = payload.get("gps_status", "normal")
            client_session_id = payload.get("client_session_id")
            scenic_slug = payload.get("scenicSlug")
            attraction_id = payload.get("attractionId")
            route_label = payload.get("routeLabel")
            preset_route_key = payload.get("presetRouteKey")
            session_key = get_session_key("anonymous", client_session_id, fallback=ws_session_key)

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
                    asr_service = get_asr_service()
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

            assistant_text, pipeline_result = run_answer_pipeline(
                user_text,
                gps_status,
                session_key=session_key,
                user_profile=None,
                scenic_slug=scenic_slug,
                attraction_id=attraction_id,
            )
            assistant_text = _select_avatar_response_text(
                assistant_text,
                pipeline_result,
                prefer_compact_recommendation=bool(preset_route_key),
            )
            pipeline_result["answer"] = assistant_text

            preset_route = preset_route_cache.resolve_route(
                user_text,
                scenic_slug=scenic_slug,
                preset_route_key=preset_route_key,
            )
            if preset_route:
                pipeline_result["preset_route_key"] = preset_route["key"]
                pipeline_result["preset_route_title"] = preset_route["title"]
                pipeline_result["cache_status"] = "stream_bypass"

            for char in assistant_text:
                await websocket.send_json({"type": "text_token", "text": char})

            for sentence in split_sentences(assistant_text):
                payload_chunk = await asyncio.to_thread(synthesize_chunk_payload, sentence)
                if payload_chunk:
                    await websocket.send_json({"type": "chunk", **payload_chunk})

            rag_metadata = _build_rag_metadata(
                pipeline_result,
                scenic_slug=scenic_slug,
                attraction_id=attraction_id,
                route_label=route_label,
            )
            await websocket.send_json({"type": "done", "full_text": assistant_text, "rag_metadata": rag_metadata})

            try:
                log_service.analyze_and_log(
                    user_query=user_text,
                    ai_response=assistant_text,
                    cost_time=0.0,
                    username="ws_user",
                    metadata=_build_log_metadata(
                        pipeline_result,
                        scenic_slug=scenic_slug,
                        attraction_id=attraction_id,
                        route_label=route_label,
                    ),
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
    client_session_id: Optional[str] = Form(None),
    scenicSlug: Optional[str] = Form(None),
    attractionId: Optional[str] = Form(None),
    routeLabel: Optional[str] = Form(None),
    presetRouteKey: Optional[str] = Form(None),
    current_user: Optional[Dict[str, Any]] = Depends(get_current_user_optional),
):
    api_start_time = time.time()
    request_id = str(uuid.uuid4())
    username = current_user["username"] if current_user else "anonymous"

    if avatar_image:
        image_path = os.path.join(TEMP_DIR, f"{request_id}_avatar.jpg")
        with open(image_path, "wb") as buffer:
            shutil.copyfileobj(avatar_image.file, buffer)
        avatar_engine = get_avatar_engine()
        avatar_engine.update_base_image(image_path)

    temp_audio_path = os.path.join(TEMP_DIR, f"{request_id}_input.webm")
    with open(temp_audio_path, "wb") as buffer:
        shutil.copyfileobj(audio.file, buffer)

    try:
        asr_service = get_asr_service()
        asr_result = asr_service.transcribe(temp_audio_path)
        user_text = asr_result.strip() if isinstance(asr_result, str) else str(asr_result)
        if not user_text:
            user_text = "（没有听到声音）"
    except Exception:
        user_text = "（语音识别失败）"

    result = generate_avatar_response(
        user_text,
        username,
        gps_status,
        client_session_id=client_session_id,
        scenic_slug=scenicSlug,
        attraction_id=attractionId,
        route_label=routeLabel,
        preset_route_key=presetRouteKey,
    )

    total_latency = time.time() - api_start_time
    background_tasks.add_task(
        log_service.analyze_and_log,
        user_query=user_text,
        ai_response=result.get("assistant_text", ""),
        cost_time=total_latency,
        username=username,
        metadata=result.get("rag_metadata", {}),
    )

    return JSONResponse(content=result)


@router.post("/v1/interact/text")
async def interact_text(
    background_tasks: BackgroundTasks,
    text: str = Form(...),
    avatar_image: Optional[UploadFile] = File(None),
    gps_status: str = Form("normal"),
    client_session_id: Optional[str] = Form(None),
    scenicSlug: Optional[str] = Form(None),
    attractionId: Optional[str] = Form(None),
    routeLabel: Optional[str] = Form(None),
    presetRouteKey: Optional[str] = Form(None),
    current_user: Optional[Dict[str, Any]] = Depends(get_current_user_optional),
):
    api_start_time = time.time()
    username = current_user["username"] if current_user else "anonymous"

    if avatar_image:
        request_id = str(uuid.uuid4())
        image_path = os.path.join(TEMP_DIR, f"{request_id}_avatar.jpg")
        with open(image_path, "wb") as buffer:
            shutil.copyfileobj(avatar_image.file, buffer)
        avatar_engine = get_avatar_engine()
        avatar_engine.update_base_image(image_path)

    result = generate_avatar_response(
        text,
        username,
        gps_status,
        client_session_id=client_session_id,
        scenic_slug=scenicSlug,
        attraction_id=attractionId,
        route_label=routeLabel,
        preset_route_key=presetRouteKey,
    )

    total_latency = time.time() - api_start_time
    background_tasks.add_task(
        log_service.analyze_and_log,
        user_query=text,
        ai_response=result.get("assistant_text", ""),
        cost_time=total_latency,
        username=username,
        metadata=result.get("rag_metadata", {}),
    )

    return JSONResponse(content=result)


@router.get("/v1/interact/profile")
async def get_profile(current_user: Dict[str, Any] = Depends(get_current_user)):
    profile = log_service.get_user_profile(current_user["username"])
    return JSONResponse(content={"profile": profile})


@router.get("/v1/interact/history")
async def get_history(limit: int = 50, current_user: Dict[str, Any] = Depends(get_current_user)):
    history = log_service.get_user_history(current_user["username"], limit=limit)
    return JSONResponse(content={"history": history})
