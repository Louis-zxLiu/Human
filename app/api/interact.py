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

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from app.api.auth import get_current_user, get_current_user_optional
from app.api.stream_utils import build_stream_tts_segments, split_sentences
from app.core.config import resolve_path, settings
from app.rag.location_agent import ScenicLocationAgent, detect_landmark_follow_up_need
from app.rag.pipeline import ScenicRAGPipeline, AGENT_NODE_LABELS
from app.rag.router import get_query_intent
from app.services.asr_tts import get_asr_service, get_tts_service
from app.services.avatar_engine import get_avatar_engine
from app.services.log_service import log_service
from app.services.preset_route_cache import preset_route_cache
from app.services.session_store import get_session_memory, save_session_memory, init_store

router = APIRouter()

TEMP_DIR = resolve_path("SoulX-FlashHead/data/temp")
os.makedirs(TEMP_DIR, exist_ok=True)

_pipeline_cache: Optional[ScenicRAGPipeline] = None
_location_agent_cache: Optional[ScenicLocationAgent] = None
INVALID_INPUTS = {"（没有听到声音）", "（语音识别失败）", "（未听清）"}
WEAK_GPS_SESSIONS: Dict[str, Dict[str, Any]] = {}
CONVERSATION_SESSIONS: Dict[str, Dict[str, Any]] = {}


def _init_session_store() -> None:
    """Schedule SQLite session store initialisation without blocking module load."""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(init_store())
    except RuntimeError:
        # No running loop at import time — run synchronously
        try:
            asyncio.run(init_store())
        except Exception:
            pass
    except Exception:
        pass


_init_session_store()


@router.get("/v1/interact/avatar/default")
async def get_default_avatar_image():
    avatar_path = resolve_path(settings.AVATAR_DEFAULT_IMAGE_PATH)
    if not os.path.exists(avatar_path):
        raise HTTPException(status_code=404, detail="Default avatar image not found")
    stat = os.stat(avatar_path)
    return FileResponse(
        avatar_path,
        media_type="image/jpeg",
        headers={
            "Cache-Control": "no-store, max-age=0",
            "ETag": f'W/"{int(stat.st_mtime)}-{stat.st_size}"',
        },
    )


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
    WEAK_GPS_SESSIONS.clear()
    CONVERSATION_SESSIONS.clear()


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


def synthesize_chunk_payload(text: str, tts_style: str = None) -> Optional[Dict[str, Any]]:
    clean_text = clean_markdown_for_tts(text)
    if not clean_text or not re.search(r"[\w\u4e00-\u9fa5]", clean_text):
        return None

    tts_service = get_tts_service()
    avatar_engine = get_avatar_engine()
    sentence_id = str(uuid.uuid4())
    audio_path = os.path.join(TEMP_DIR, f"{sentence_id}.mp3")
    tts_service.synthesize(clean_text, audio_path, style=tts_style)
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
    return detect_landmark_follow_up_need(user_text, intent)


def pop_weak_gps_context(session_key: str) -> Optional[Dict[str, Any]]:
    return WEAK_GPS_SESSIONS.pop(session_key, None)


def set_weak_gps_context(session_key: str, context: Dict[str, Any]) -> None:
    WEAK_GPS_SESSIONS[session_key] = context


def parse_conversation_context(raw: Optional[str]) -> list[Dict[str, Any]]:
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    context: list[Dict[str, Any]] = []
    for item in payload[-8:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "")[:16]
        content = str(item.get("content") or "").strip()[:260]
        if role not in {"user", "assistant"} or not content:
            continue
        meta = item.get("meta") if isinstance(item.get("meta"), dict) else None
        context.append({"role": role, "content": content, "meta": meta})
    return context


def get_conversation_memory(session_key: str) -> Dict[str, Any]:
    """Get conversation memory. Falls back to SQLite if not in the in-memory cache."""
    if session_key in CONVERSATION_SESSIONS:
        return dict(CONVERSATION_SESSIONS[session_key])
    # Try persistent store (run in a worker thread to avoid blocking the event loop)
    try:
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, get_session_memory(session_key))
            memory = future.result(timeout=2.0)
            if memory:
                CONVERSATION_SESSIONS[session_key] = memory
                return dict(memory)
    except Exception:
        pass
    return {}

def _extract_preference_memory(
    user_text: str,
    pipeline_result: Dict[str, Any],
    previous: Dict[str, Any],
    route_label: Optional[str] = None,
) -> Dict[str, Any]:
    preferences = dict(previous.get("preferences") or {})
    text = str(user_text or "")
    label = str(route_label or pipeline_result.get("recommendation_label") or "")
    profile_key = str(((pipeline_result.get("recommendation") or {}).get("profile_key")) or "")
    preference_terms = {
        "history": ("历史", "文化", "佛教", "典故", "人文", "history"),
        "nature": ("自然", "风景", "风光", "山水", "拍照", "nature"),
        "family": ("亲子", "孩子", "小孩", "老人", "家庭", "family"),
        "architecture": ("建筑", "艺术", "宫殿", "藏式", "architecture"),
        "relaxed": ("轻松", "少走", "休闲", "慢慢", "relaxed"),
    }
    source = f"{text} {label} {profile_key}".lower()
    interests = set(preferences.get("interests") or [])
    for key, terms in preference_terms.items():
        if key == profile_key or any(term.lower() in source for term in terms):
            interests.add(key)
    if interests:
        preferences["interests"] = sorted(interests)
    if pipeline_result.get("matched_attraction"):
        preferences["last_named_attraction"] = pipeline_result.get("matched_attraction")
    scenic_slug = (pipeline_result.get("recommendation") or {}).get("scenic_slug") or (pipeline_result.get("plan") or {}).get("scenic_slug")
    if scenic_slug:
        preferences["scenic_slug"] = scenic_slug
    return preferences


def _extract_tool_memory(pipeline_result: Dict[str, Any]) -> list[Dict[str, Any]]:
    calls = (((pipeline_result.get("observability") or {}).get("trace") or {}).get("tools") or {}).get("calls") or []
    compact = []
    for call in calls[-3:]:
        if not isinstance(call, dict):
            continue
        compact.append(
            {
                "tool_name": call.get("tool_name"),
                "ok": call.get("ok"),
                "response_kind": call.get("response_kind"),
                "insufficient": call.get("insufficient"),
            }
        )
    return compact


def update_conversation_memory(
    session_key: str,
    user_text: str,
    assistant_text: str,
    pipeline_result: Dict[str, Any],
    scenic_slug: Optional[str] = None,
    attraction_id: Optional[str] = None,
    route_label: Optional[str] = None,
) -> None:
    plan = pipeline_result.get("plan") or {}
    previous = CONVERSATION_SESSIONS.get(session_key) or {}
    matched_attraction = pipeline_result.get("matched_attraction") or previous.get("last_attraction")
    memory = {
        "last_user_text": str(user_text or "")[:220],
        "last_assistant_text": str(assistant_text or "")[:260],
        "last_intent": pipeline_result.get("intent"),
        "last_strategy": plan.get("strategy"),
        "last_response_kind": pipeline_result.get("response_kind"),
        "last_attraction": matched_attraction,
        "last_scenic_slug": scenic_slug or plan.get("scenic_slug") or previous.get("last_scenic_slug"),
        "last_attraction_id": attraction_id or previous.get("last_attraction_id"),
        "last_route_label": route_label or pipeline_result.get("recommendation_label") or previous.get("last_route_label"),
        "preferences": _extract_preference_memory(user_text, pipeline_result, previous, route_label=route_label),
        "last_tools": _extract_tool_memory(pipeline_result),
        "updated_at": time.time(),
    }
    if pipeline_result.get("response_kind") == "clarification":
        memory["pending_clarification"] = {
            "question": str(user_text or "")[:220],
            "question_type": plan.get("question_type"),
            "strategy": plan.get("strategy"),
        }
    elif previous.get("pending_clarification"):
        memory["pending_clarification"] = None
    CONVERSATION_SESSIONS[session_key] = {key: value for key, value in memory.items() if value is not None}
    # Persist asynchronously — fire-and-forget, failure only prints a warning
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(save_session_memory(session_key, CONVERSATION_SESSIONS[session_key]))
    except RuntimeError:
        # No running loop (e.g. unit tests calling this synchronously) — skip persistence
        pass
    except Exception:
        pass


def handle_weak_gps_flow(
    user_text: str,
    gps_status: str,
    session_key: str,
    user_profile: Optional[str],
    scenic_slug: Optional[str] = None,
    attraction_id: Optional[str] = None,
    conversation_context: Optional[list[Dict[str, Any]]] = None,
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
                conversation_context=conversation_context,
                session_memory=get_conversation_memory(session_key),
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
    forced_recommendation_profile: Optional[str] = None,
    forced_recommendation_title: Optional[str] = None,
    conversation_context: Optional[list[Dict[str, Any]]] = None,
) -> Tuple[str, Dict[str, Any]]:
    gps_result = handle_weak_gps_flow(
        user_text,
        gps_status,
        session_key,
        user_profile,
        scenic_slug=scenic_slug,
        attraction_id=attraction_id,
        conversation_context=conversation_context,
    )
    if gps_result:
        return gps_result

    result = get_pipeline().process_query(
        user_text,
        user_profile=user_profile,
        scenic_slug=scenic_slug,
        attraction_id=attraction_id,
        forced_recommendation_profile=forced_recommendation_profile,
        forced_recommendation_title=forced_recommendation_title,
        conversation_context=conversation_context,
        session_memory=get_conversation_memory(session_key),
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
    forced_recommendation_profile: Optional[str] = None,
    forced_recommendation_title: Optional[str] = None,
    conversation_context: Optional[list[Dict[str, Any]]] = None,
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
        forced_recommendation_profile=forced_recommendation_profile,
        forced_recommendation_title=forced_recommendation_title,
        conversation_context=conversation_context,
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
    tts_style = str(pipeline_result.get("tts_style") or "gentle")
    try:
        clean_text_for_tts = clean_markdown_for_tts(assistant_text)
        if clean_text_for_tts and re.search(r"[\w\u4e00-\u9fa5]", clean_text_for_tts):
            tts_error = []

            def run_tts() -> None:
                try:
                    tts_service = get_tts_service()
                    tts_service.synthesize(clean_text_for_tts, audio_output_path, style=tts_style)
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
    update_conversation_memory(
        session_key,
        user_text,
        assistant_text,
        pipeline_result,
        scenic_slug=scenic_slug,
        attraction_id=attraction_id,
        route_label=route_label,
    )

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


def _generate_static_avatar_response(
    assistant_text: str,
    response_kind: str,
    agent_type: str = "static_reply",
    tts_style: str = None,
) -> Dict[str, Any]:
    request_id = str(uuid.uuid4())
    audio_output_path = os.path.join(TEMP_DIR, f"{request_id}.mp3")
    video_output_path = os.path.join(TEMP_DIR, f"{request_id}_video.mp4")

    audio_ready = False
    try:
        clean_text_for_tts = clean_markdown_for_tts(assistant_text)
        if clean_text_for_tts and re.search(r"[\w\u4e00-\u9fa5]", clean_text_for_tts):
            tts_service = get_tts_service()
            tts_service.synthesize(clean_text_for_tts, audio_output_path, style=tts_style)
            audio_ready = os.path.exists(audio_output_path) and os.path.getsize(audio_output_path) > 0
    except Exception as exc:
        print(f"[TTS] static synthesis failed: {exc}")
        audio_ready = False

    video_ready = False
    if audio_ready:
        try:
            avatar_engine = get_avatar_engine()
            success_path = avatar_engine.generate_avatar_video(audio_output_path, video_output_path)
            video_ready = bool(success_path and os.path.exists(video_output_path))
        except Exception as exc:
            print(f"[AvatarEngine] static video generation failed: {exc}")
            video_ready = False

    return {
        "user_text": "",
        "assistant_text": assistant_text,
        "audio_url": f"/static/temp/{request_id}.mp3" if audio_ready else None,
        "video_stream_url": f"/static/temp/{request_id}_video.mp4" if video_ready else None,
        "rag_metadata": {
            "intent": "FACT",
            "agent_type": agent_type,
            "matched_attraction": None,
            "recommendation_label": None,
            "response_kind": response_kind,
            "recommendation": None,
            "gps_state": "awaiting_landmarks" if response_kind == "gps:awaiting_landmarks" else None,
            "gps_candidates": [],
        },
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


def _apply_preset_reply_metadata(
    result: Dict[str, Any],
    preset_reply: Dict[str, str],
    cache_status: str,
) -> Dict[str, Any]:
    rag_metadata = dict(result.get("rag_metadata") or {})
    rag_metadata["preset_reply_key"] = preset_reply["key"]
    rag_metadata["preset_reply_title"] = preset_reply["title"]
    rag_metadata["cache_status"] = cache_status
    result["rag_metadata"] = rag_metadata
    return result


def _apply_fixed_reply_cache(result: Dict[str, Any]) -> Dict[str, Any]:
    rag_metadata = result.get("rag_metadata") or {}
    preset_reply = preset_route_cache.resolve_reply(
        result.get("assistant_text"),
        response_kind=rag_metadata.get("response_kind"),
    )
    if not preset_reply:
        return result

    payload = preset_route_cache.get_or_create_payload(
        preset_reply,
        lambda _reply: result,
    )
    cached_result = {
        "user_text": result.get("user_text", ""),
        "assistant_text": payload.get("assistant_text", result.get("assistant_text", "")),
        "audio_url": payload.get("audio_url"),
        "video_stream_url": payload.get("video_stream_url"),
        "rag_metadata": payload.get("rag_metadata") or rag_metadata,
    }
    cache_status = "hit" if payload.get("cache_hit") else "generated"
    return _apply_preset_reply_metadata(cached_result, preset_reply, cache_status)


def generate_avatar_response(
    user_text: str,
    username: str = "anonymous",
    gps_status: str = "normal",
    client_session_id: Optional[str] = None,
    scenic_slug: Optional[str] = None,
    attraction_id: Optional[str] = None,
    route_label: Optional[str] = None,
    preset_route_key: Optional[str] = None,
    conversation_context: Optional[list[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    preset_route = preset_route_cache.resolve_route(
        user_text,
        scenic_slug=scenic_slug,
        preset_route_key=preset_route_key,
    )
    if not preset_route:
        result = _generate_fresh_avatar_response(
            user_text,
            username,
            gps_status,
            client_session_id=client_session_id,
            scenic_slug=scenic_slug,
            attraction_id=attraction_id,
            route_label=route_label,
            conversation_context=conversation_context,
        )
        return _apply_fixed_reply_cache(result)

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
            forced_recommendation_profile=route.get("profile_key"),
            forced_recommendation_title=route.get("title"),
            conversation_context=conversation_context,
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
    result = _apply_preset_route_metadata(result, preset_route, cache_status)
    session_key = get_session_key(username, client_session_id)
    update_conversation_memory(
        session_key,
        user_text,
        result.get("assistant_text", ""),
        result.get("rag_metadata") or {},
        scenic_slug=preset_route.get("scenic_slug") or scenic_slug,
        attraction_id=attraction_id,
        route_label=route_label or preset_route.get("title"),
    )
    return result


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
                    forced_recommendation_profile=current_route.get("profile_key"),
                    forced_recommendation_title=current_route.get("title"),
                ),
            )
            refreshed += 1
        except Exception as exc:
            failed += 1
            print(f"[PresetRouteCache] refresh failed for {route['key']}: {exc}")
    for reply in preset_route_cache.list_replies():
        try:
            preset_route_cache.get_or_create_payload(
                reply,
                lambda current_reply: _generate_static_avatar_response(
                    current_reply["assistant_text"],
                    response_kind=current_reply["response_kind"],
                    agent_type="preset_reply",
                ),
            )
            refreshed += 1
        except Exception as exc:
            failed += 1
            print(f"[PresetRouteCache] refresh failed for {reply['key']}: {exc}")
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
            conversation_context = payload.get("conversation_context") or []
            if not isinstance(conversation_context, list):
                conversation_context = []
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

            # Phase 1: try weak-GPS fast path; if not applicable, stream graph nodes.
            gps_fast = handle_weak_gps_flow(
                user_text,
                gps_status,
                session_key,
                user_profile=None,
                scenic_slug=scenic_slug,
                attraction_id=attraction_id,
                conversation_context=conversation_context,
            )
            if gps_fast:
                assistant_text, pipeline_result = gps_fast
            else:
                # Normal path: stream per-node progress events to the client.
                _pipeline = get_pipeline()
                assistant_text = ""
                pipeline_result = {}
                async for _event in _pipeline.async_stream_events(
                    user_text=user_text,
                    scenic_slug=scenic_slug,
                    attraction_id=attraction_id,
                    conversation_context=conversation_context,
                    session_memory=get_conversation_memory(session_key),
                ):
                    if _event["node"] == "__final__":
                        pipeline_result = _event["data"]
                        assistant_text = pipeline_result.get("answer", "")
                    else:
                        await websocket.send_json({
                            "type": "agent_node",
                            "node": _event["node"],
                            "label": AGENT_NODE_LABELS.get(_event["node"], _event["node"]),
                            "status": _event["status"],
                            "ts": _event["ts"],
                        })
                pipeline_result["gps_state"] = "normal" if gps_status != "weak" else "weak_without_followup"
                pipeline_result["gps_candidates"] = []
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

            response_kind = str(pipeline_result.get("response_kind") or "")
            ws_tts_style = str(pipeline_result.get("tts_style") or "gentle")
            for sentence in build_stream_tts_segments(assistant_text, response_kind=response_kind):
                payload_chunk = await asyncio.to_thread(synthesize_chunk_payload, sentence, ws_tts_style)
                if payload_chunk:
                    await websocket.send_json({"type": "chunk", **payload_chunk})

            rag_metadata = _build_rag_metadata(
                pipeline_result,
                scenic_slug=scenic_slug,
                attraction_id=attraction_id,
                route_label=route_label,
            )
            update_conversation_memory(
                session_key,
                user_text,
                assistant_text,
                pipeline_result,
                scenic_slug=scenic_slug,
                attraction_id=attraction_id,
                route_label=route_label,
            )

            # Log first so we have log_id for review_status
            log_id = None
            review_status = "auto"
            try:
                log_id, review_status = log_service.analyze_and_log_returning_status(
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

            await websocket.send_json({
                "type": "done",
                "full_text": assistant_text,
                "rag_metadata": rag_metadata,
                "review_status": review_status,
                "log_id": log_id,
            })

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
    audio: UploadFile = File(...),
    avatar_image: Optional[UploadFile] = File(None),
    gps_status: str = Form("normal"),
    client_session_id: Optional[str] = Form(None),
    scenicSlug: Optional[str] = Form(None),
    attractionId: Optional[str] = Form(None),
    routeLabel: Optional[str] = Form(None),
    presetRouteKey: Optional[str] = Form(None),
    conversation_context: Optional[str] = Form(None),
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
        conversation_context=parse_conversation_context(conversation_context),
    )

    total_latency = time.time() - api_start_time
    log_id = None
    review_status = "auto"
    try:
        log_id, review_status = log_service.analyze_and_log_returning_status(
            user_query=user_text,
            ai_response=result.get("assistant_text", ""),
            cost_time=total_latency,
            username=username,
            metadata=result.get("rag_metadata", {}),
        )
    except Exception as exc:
        print(f"[API] failed to log audio interaction: {exc}")

    result["review_status"] = review_status
    result["log_id"] = log_id
    return JSONResponse(content=result)


@router.post("/v1/interact/text")
async def interact_text(
    text: str = Form(...),
    avatar_image: Optional[UploadFile] = File(None),
    gps_status: str = Form("normal"),
    client_session_id: Optional[str] = Form(None),
    scenicSlug: Optional[str] = Form(None),
    attractionId: Optional[str] = Form(None),
    routeLabel: Optional[str] = Form(None),
    presetRouteKey: Optional[str] = Form(None),
    conversation_context: Optional[str] = Form(None),
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
        conversation_context=parse_conversation_context(conversation_context),
    )

    total_latency = time.time() - api_start_time
    log_id = None
    review_status = "auto"
    try:
        log_id, review_status = log_service.analyze_and_log_returning_status(
            user_query=text,
            ai_response=result.get("assistant_text", ""),
            cost_time=total_latency,
            username=username,
            metadata=result.get("rag_metadata", {}),
        )
    except Exception as exc:
        print(f"[API] failed to log text interaction: {exc}")

    result["review_status"] = review_status
    result["log_id"] = log_id
    return JSONResponse(content=result)


@router.get("/v1/interact/review/{log_id}")
async def get_review_status(
    log_id: int,
    current_user: Optional[Dict[str, Any]] = Depends(get_current_user_optional),
):
    """Poll endpoint for frontend to check if a pending review has been resolved."""
    import sqlite3 as _sqlite3
    from app.core.config import resolve_path as _rp
    db_path = _rp("data/processed/interaction_logs.db")
    try:
        conn = _sqlite3.connect(db_path)
        conn.row_factory = _sqlite3.Row
        row = conn.execute(
            "SELECT review_status, suggested_answer, ai_response FROM interaction_logs WHERE id=?",
            (log_id,),
        ).fetchone()
        conn.close()
    except Exception:
        raise HTTPException(status_code=500, detail="DB error")
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    status = row["review_status"]
    # If admin suggested a replacement answer, return it; else return original
    answer = row["suggested_answer"] or row["ai_response"]
    return JSONResponse(content={"review_status": status, "answer": answer if status in ("approved", "rejected") else None})


@router.get("/v1/interact/profile")
async def get_profile(current_user: Dict[str, Any] = Depends(get_current_user)):
    profile = log_service.get_user_profile(current_user["username"])
    return JSONResponse(content={"profile": profile})


@router.get("/v1/interact/history")
async def get_history(limit: int = 50, current_user: Dict[str, Any] = Depends(get_current_user)):
    history = log_service.get_user_history(current_user["username"], limit=limit)
    return JSONResponse(content={"history": history})
