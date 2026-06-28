import os
import shutil
import sqlite3
import threading
import uuid
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.api import chat as chat_api
from app.api import interact as interact_api
from app.api import scenic as scenic_api
from app.api.auth import get_current_admin
from app.core.config import persist_env_overrides, resolve_path, settings
from app.core.runtime import CONDA_ENV_PREFIX
from app.rag.recommendation_agent import get_recommendation_display_label
from app.services.asr_tts import get_tts_service
from app.services.avatar_engine import get_avatar_engine, reset_avatar_engines
from app.services.log_service import log_service
from app.services.preset_route_cache import preset_route_cache

router = APIRouter()
KNOWN_QUERY_SCOPES = {"FACT", "RECOMMEND", "ANALYTICS"}


def build_cli_command(args: str) -> str:
    env_prefix = CONDA_ENV_PREFIX.as_posix()
    return "\n".join(
        [
            f'Windows: conda run -p "{env_prefix}" python -m app.cli {args}',
            f'Linux/AutoDL: conda run -p "$(pwd)/env" python -m app.cli {args}',
        ]
    )


UNIFIED_EVAL_ARGS = (
    "eval-unified "
    "--report reports/unified_eval_report.json "
    "--markdown-report reports/unified_eval_report.md "
    "--strict --fail-under 90"
)
GENERATE_UNIFIED_EVAL_ARGS = "generate-unified-eval --target 1200 --output tests/unified_eval_cases.jsonl"
UNIFIED_EVAL_COMMAND = build_cli_command(UNIFIED_EVAL_ARGS)
GENERATE_UNIFIED_EVAL_COMMAND = build_cli_command(GENERATE_UNIFIED_EVAL_ARGS)

AVATAR_RUNTIME_PROFILES = {
    "memory_saver": {
        "id": "memory_saver",
        "label": "省显存",
        "summary": "优先压低显存占用和首包压力。",
        "description": "使用 float16 和 0 秒 warmup，更省显存、更快，但画面稳定性和细节可能略差。",
        "torch_dtype": "float16",
        "warmup_seconds": 0.0,
    },
    "quality": {
        "id": "quality",
        "label": "高质量",
        "summary": "优先画面稳定度和数字人观感。",
        "description": "使用 bfloat16 和 0.5 秒 warmup，画质通常更稳，但会增加显存占用和启动开销。",
        "torch_dtype": "bfloat16",
        "warmup_seconds": 0.5,
    },
}


def get_db_path() -> str:
    return resolve_path("data/processed/interaction_logs.db")


def build_data_status() -> Dict[str, Any]:
    chroma_dir = resolve_path(settings.CHROMA_DB_DIR)
    behavior_db = resolve_path("data/processed/tourist_behavior.db")
    kb_dir = resolve_path(settings.KNOWLEDGE_BASE_DIR)
    raw_behavior_dir = resolve_path("data/raw_sql_data")

    chroma_ready = os.path.exists(chroma_dir) and bool(os.listdir(chroma_dir))
    behavior_ready = os.path.exists(behavior_db)
    kb_docs = []
    if os.path.exists(kb_dir):
        kb_docs = [
            build_file_status(Path(kb_dir) / name)
            for name in os.listdir(kb_dir)
            if name.lower().endswith((".docx", ".xlsx", ".txt", ".csv"))
        ]
    behavior_files = []
    if os.path.exists(raw_behavior_dir):
        behavior_files = [
            build_file_status(Path(raw_behavior_dir) / name)
            for name in os.listdir(raw_behavior_dir)
            if name.lower().endswith((".xlsx", ".xls", ".csv"))
        ]

    return {
        "preflight_ok": chroma_ready and behavior_ready,
        "knowledge_base_ready": chroma_ready,
        "behavior_db_ready": behavior_ready,
        "knowledge_doc_count": len(kb_docs),
        "knowledge_documents": [doc["name"] for doc in kb_docs[:10]],
        "knowledge_document_details": kb_docs,
        "behavior_file_count": len(behavior_files),
        "behavior_files": behavior_files,
        "last_knowledge_build_time": get_path_mtime(chroma_dir),
        "last_behavior_build_time": get_path_mtime(behavior_db),
        "rebuild_commands": {
            "knowledge_base": build_cli_command("prepare-kb"),
            "behavior_data": build_cli_command("prepare-data"),
            "unified_eval": UNIFIED_EVAL_COMMAND,
            "generate_unified_eval": GENERATE_UNIFIED_EVAL_COMMAND,
            "demo_seed": build_cli_command("seed-demo-logs --reset"),
        },
    }


def build_file_status(path: Path) -> Dict[str, Any]:
    stat = path.stat()
    return {
        "name": path.name,
        "size_kb": round(stat.st_size / 1024, 1),
        "updated_at": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
        "extension": path.suffix.lower().lstrip("."),
    }


def get_path_mtime(path: str) -> str | None:
    if not os.path.exists(path):
        return None
    return datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M")


def build_eval_status() -> Dict[str, Any]:
    report_path = Path(resolve_path("reports/unified_eval_report.json"))
    if not report_path.exists():
        return {
            "ok": False,
            "available": False,
            "overall_score": None,
            "case_count": 0,
            "failure_count": None,
            "failure_sample_count": 0,
            "updated_at": None,
            "summary": "尚未生成统一评测报告。",
            "command": UNIFIED_EVAL_COMMAND,
            "generate_command": GENERATE_UNIFIED_EVAL_COMMAND,
        }

    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "ok": False,
            "available": False,
            "overall_score": None,
            "case_count": 0,
            "failure_count": None,
            "failure_sample_count": 0,
            "updated_at": get_path_mtime(str(report_path)),
            "summary": f"统一评测报告读取失败：{exc}",
            "command": UNIFIED_EVAL_COMMAND,
            "generate_command": GENERATE_UNIFIED_EVAL_COMMAND,
        }

    source_scores = {
        key: {
            "accuracy": value.get("accuracy"),
            "pass_rate": value.get("pass_rate"),
            "count": value.get("count"),
        }
        for key, value in (payload.get("by_gold_source") or {}).items()
    }
    cases = payload.get("cases") or []
    if cases:
        failure_count = sum(1 for case in cases if not case.get("passed"))
    else:
        source_total = sum(int(value.get("count") or 0) for value in source_scores.values())
        source_passed = sum(
            int(value.get("passed") or 0)
            for value in (payload.get("by_gold_source") or {}).values()
        )
        failure_count = max(source_total - source_passed, 0)
    failure_sample_count = len(payload.get("failures") or [])
    overall_score = payload.get("overall_score")
    case_count = payload.get("case_count", 0)
    return {
        "ok": bool(payload.get("ok")),
        "available": True,
        "overall_score": overall_score,
        "case_count": case_count,
        "failure_count": failure_count,
        "failure_sample_count": failure_sample_count,
        "updated_at": get_path_mtime(str(report_path)),
        "source_scores": source_scores,
        "elapsed_seconds": payload.get("elapsed_seconds"),
        "thresholds": payload.get("thresholds") or {},
        "summary": (
            f"统一评测 {overall_score}/100，覆盖 {case_count} 题，"
            f"未通过样例 {failure_count} 个，报告展示 {failure_sample_count} 个失败样例。"
        ),
        "command": UNIFIED_EVAL_COMMAND,
        "generate_command": GENERATE_UNIFIED_EVAL_COMMAND,
    }


def build_operation_recommendations(snapshot: Dict[str, Any]) -> list[Dict[str, str]]:
    recommendations = []
    data_status = snapshot.get("data_status") or {}
    eval_status = snapshot.get("unified_eval") or {}
    failed_samples = snapshot.get("recent_failed_samples") or []
    recommendation_distribution = snapshot.get("recommendation_label_distribution") or {}
    avg_cost_time = float(snapshot.get("avg_cost_time") or 0)
    total_interactions = int(snapshot.get("total_interactions") or 0)

    if not data_status.get("preflight_ok"):
        recommendations.append(
            {
                "priority": "高",
                "title": "先补齐知识库和行为库预检",
                "detail": "为了保证知识库和游客行为分析都能稳定支撑服务，建议先运行数据准备命令。",
                "action": "运行 prepare-data 与 prepare-kb 后刷新后台。",
            }
        )

    if eval_status.get("available"):
        score = float(eval_status.get("overall_score") or 0)
        if score >= 95:
            recommendations.append(
                {
                    "priority": "高",
                    "title": "把统一评测作为质量基线",
                    "detail": f"当前统一评测 {score}/100，说明事实问答准确率已经达到较高水平，可作为质量证明长期展示。",
                    "action": "在后台、质量周报和对外材料中展示最新评测结果。",
                }
            )
        elif score >= 90:
            recommendations.append(
                {
                    "priority": "高",
                    "title": "统一评测已超过质量线",
                    "detail": f"当前统一评测 {score}/100，已通过 90 分严格线；建议持续展示 1200 题覆盖面，并把待优化样例纳入后续迭代。",
                    "action": "在后台和质量文档中统一展示 reports/unified_eval_report.md 的最新结果。",
                }
            )
        else:
            recommendations.append(
                {
                    "priority": "高",
                    "title": "优先修复统一评测低分项",
                    "detail": "当前评测未达到预期质量线，建议先处理失败样例再继续扩展内容与场景。",
                    "action": "运行 eval-unified 并查看 reports/unified_eval_report.md。",
                }
            )

    if failed_samples:
        first_query = failed_samples[0].get("user_query", "最近失败样例")
        recommendations.append(
            {
                "priority": "中",
                "title": "把拒答样例转成知识库维护动作",
                "detail": f"最近出现“{first_query}”这类需要关注的问题，可作为后台知识库管理价值展示。",
                "action": "补充对应 DOCX 资料或优化无证据问题的拒答规则。",
            }
        )

    if recommendation_distribution:
        top_label = max(recommendation_distribution.items(), key=lambda item: item[1])[0]
        recommendations.append(
            {
                "priority": "中",
                "title": f"{top_label}路线关注度较高",
                "detail": "推荐标签分布可以转化为景区运营洞察，说明系统不只会问答，也能帮助规划讲解资源。",
                "action": "结合推荐标签图表优化前台路线入口与讲解资源配置。",
            }
        )

    if avg_cost_time > 5:
        recommendations.append(
            {
                "priority": "中",
                "title": "控制长回答和视频生成耗时",
                "detail": f"当前平均响应耗时约 {avg_cost_time}s，语音视频链路建议使用短问短答展示。",
                "action": "优先优化长文本和高耗时场景的响应链路。",
            }
        )

    if total_interactions == 0:
        recommendations.append(
            {
                "priority": "高",
                "title": "初始化后台样例数据",
                "detail": "后台空图表会削弱运营可读性，建议先注入一组初始化日志。",
                "action": '运行 conda run -p "D:/Human/env" python -m app.cli seed-demo-logs --reset。',
            }
        )

    recommendations.append(
        {
            "priority": "低",
            "title": "默认启用高质量数字人模式",
            "detail": "当需要更稳定的口型同步、语音合成和表情观感时，高质量模式更适合作为默认配置。",
            "action": "后台选择“高质量”，确认音色试听正常后再正式使用。",
        }
    )

    return recommendations[:5]


def get_avatar_runtime_profile_id() -> str:
    current_dtype = str(settings.AVATAR_TORCH_DTYPE).lower()
    current_warmup = float(settings.AVATAR_WARMUP_SECONDS)
    if current_dtype == "bfloat16" and current_warmup >= 0.5:
        return "quality"
    return "memory_saver"


def build_avatar_runtime_payload() -> Dict[str, Any]:
    return {
        "current_profile_id": get_avatar_runtime_profile_id(),
        "current_settings": {
            "torch_dtype": str(settings.AVATAR_TORCH_DTYPE).lower(),
            "warmup_seconds": float(settings.AVATAR_WARMUP_SECONDS),
        },
        "profiles": list(AVATAR_RUNTIME_PROFILES.values()),
    }


@router.get("/dashboard")
async def get_dashboard_data(current_admin: Dict[str, Any] = Depends(get_current_admin)):
    db_path = get_db_path()
    if not os.path.exists(db_path):
        payload = {
            "total_interactions": 0,
            "daily_interactions": 0,
            "avg_cost_time": 0.0,
            "sentiment_distribution": {},
            "intent_distribution": {},
            "focus_points": [],
            "hot_analytics_questions": [],
            "top_attraction_preferences": [],
            "satisfaction_trend": [],
            "recommendation_label_distribution": {},
            "recent_failed_samples": [],
            "data_status": build_data_status(),
            "unified_eval": build_eval_status(),
        }
        payload["operation_recommendations"] = build_operation_recommendations(payload)
        return JSONResponse(content=payload)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()

        total_interactions = cursor.execute("SELECT COUNT(*) AS count FROM interaction_logs").fetchone()["count"]
        daily_interactions = cursor.execute(
            "SELECT COUNT(*) AS count FROM interaction_logs WHERE date(created_at) = date('now', 'localtime')"
        ).fetchone()["count"]
        avg_cost_time = cursor.execute(
            "SELECT AVG(cost_time) AS avg_time FROM interaction_logs"
        ).fetchone()["avg_time"] or 0.0

        sentiment_distribution = {
            row["sentiment"]: row["count"]
            for row in cursor.execute(
                "SELECT sentiment, COUNT(*) AS count FROM interaction_logs GROUP BY sentiment"
            ).fetchall()
        }
        intent_distribution = {
            row["query_scope"]: row["count"]
            for row in cursor.execute(
                """
                SELECT query_scope, COUNT(*) AS count
                FROM interaction_logs
                WHERE query_scope IS NOT NULL AND query_scope != ''
                GROUP BY query_scope
                """
            ).fetchall()
            if row["query_scope"] in KNOWN_QUERY_SCOPES
        }
        focus_points = [
            {"name": row["focus_point"], "value": row["count"]}
            for row in cursor.execute(
                """
                SELECT focus_point, COUNT(*) AS count
                FROM interaction_logs
                WHERE focus_point != '未知'
                GROUP BY focus_point
                ORDER BY count DESC
                LIMIT 20
                """
            ).fetchall()
        ]
        hot_analytics_questions = [
            {"question": row["user_query"], "count": row["count"]}
            for row in cursor.execute(
                """
                SELECT user_query, COUNT(*) AS count
                FROM interaction_logs
                WHERE query_scope = 'ANALYTICS'
                GROUP BY user_query
                ORDER BY count DESC, MAX(created_at) DESC
                LIMIT 5
                """
            ).fetchall()
        ]
        top_attraction_preferences = [
            {"name": row["matched_attraction"], "value": row["count"]}
            for row in cursor.execute(
                """
                SELECT matched_attraction, COUNT(*) AS count
                FROM interaction_logs
                WHERE matched_attraction IS NOT NULL AND matched_attraction != ''
                GROUP BY matched_attraction
                ORDER BY count DESC
                LIMIT 10
                """
            ).fetchall()
        ]
        satisfaction_trend = [
            {
                "date": row["date"],
                "positive": row["positive_count"],
                "neutral": row["neutral_count"],
                "negative": row["negative_count"],
            }
            for row in cursor.execute(
                """
                SELECT
                    date(created_at) AS date,
                    SUM(CASE WHEN sentiment = '正面' THEN 1 ELSE 0 END) AS positive_count,
                    SUM(CASE WHEN sentiment = '中性' THEN 1 ELSE 0 END) AS neutral_count,
                    SUM(CASE WHEN sentiment = '负面' THEN 1 ELSE 0 END) AS negative_count
                FROM interaction_logs
                GROUP BY date(created_at)
                ORDER BY date(created_at) DESC
                LIMIT 7
                """
            ).fetchall()
        ][::-1]
        recommendation_label_distribution: Dict[str, int] = {}
        for row in cursor.execute(
            """
            SELECT recommendation_label, COUNT(*) AS count
            FROM interaction_logs
            WHERE recommendation_label IS NOT NULL AND recommendation_label != ''
            GROUP BY recommendation_label
            """
        ).fetchall():
            display_label = get_recommendation_display_label(row["recommendation_label"])
            if not display_label:
                continue
            recommendation_label_distribution[display_label] = (
                recommendation_label_distribution.get(display_label, 0) + row["count"]
            )
        recent_failed_samples = [
            {
                "user_query": row["user_query"],
                "ai_response": row["ai_response"],
                "response_kind": row["response_kind"],
                "created_at": row["created_at"],
            }
            for row in cursor.execute(
                """
                SELECT user_query, ai_response, response_kind, created_at
                FROM interaction_logs
                WHERE response_kind LIKE 'refused%' OR response_kind LIKE 'gps:ambiguous%' OR response_kind LIKE 'gps:need_more%'
                ORDER BY created_at DESC
                LIMIT 8
                """
            ).fetchall()
        ]

        payload = {
            "total_interactions": total_interactions,
            "daily_interactions": daily_interactions,
            "avg_cost_time": round(avg_cost_time, 2),
            "sentiment_distribution": sentiment_distribution,
            "intent_distribution": intent_distribution,
            "focus_points": focus_points,
            "hot_analytics_questions": hot_analytics_questions,
            "top_attraction_preferences": top_attraction_preferences,
            "satisfaction_trend": satisfaction_trend,
            "recommendation_label_distribution": recommendation_label_distribution,
            "recent_failed_samples": recent_failed_samples,
            "data_status": build_data_status(),
            "unified_eval": build_eval_status(),
        }
        payload["operation_recommendations"] = build_operation_recommendations(payload)
        return JSONResponse(content=payload)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"获取大屏数据失败: {exc}")
    finally:
        conn.close()


@router.post("/avatar")
async def update_default_avatar(
    file: UploadFile = File(...),
    current_admin: Dict[str, Any] = Depends(get_current_admin),
):
    try:
        target_path = resolve_path(settings.AVATAR_DEFAULT_IMAGE_PATH)
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        with open(target_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        avatar_engine = get_avatar_engine()
        avatar_engine.update_base_image(target_path)
        cleared = preset_route_cache.clear_all()
        interact_api.refresh_preset_route_cache_in_background()
        return JSONResponse(
            content={
                "message": "Default avatar image updated successfully, preset route cache refresh started",
                "preset_route_cache": {
                    "cleared": cleared,
                    "refresh_started": True,
                },
            }
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"更新默认头像失败: {exc}")


class UpdateVoiceRequest(BaseModel):
    voice_id: str


class UpdateAvatarRuntimeRequest(BaseModel):
    profile_id: str


@router.post("/cache/refresh")
async def refresh_runtime_cache(current_admin: Dict[str, Any] = Depends(get_current_admin)):
    chat_api.clear_runtime_cache()
    interact_api.clear_runtime_cache()
    scenic_api.clear_runtime_cache()
    reset_avatar_engines()
    log_reset = log_service.clear_logs()
    preset_cache_removed = preset_route_cache.clear_all()

    return JSONResponse(
        content={
            "ok": True,
            "message": "Backend state cleared successfully",
            "refreshed": [
                "chat_pipeline",
                "interact_pipeline",
                "location_agent",
                "scenic_fact_agent",
                "scenic_recommendation_agent",
                "avatar_engines",
                "preset_route_cache",
                "interaction_logs",
            ],
            "removed_logs": log_reset["removed"],
            "removed_preset_cache_files": preset_cache_removed,
            "refreshed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
    )


@router.get("/voice/list")
async def get_available_voices(current_admin: Dict[str, Any] = Depends(get_current_admin)):
    tts_service = get_tts_service()
    return JSONResponse(
        content={
            "current_voice": tts_service.get_current_voice(),
            "available_voices": tts_service.available_voices,
        }
    )


@router.get("/avatar/runtime")
async def get_avatar_runtime(current_admin: Dict[str, Any] = Depends(get_current_admin)):
    return JSONResponse(content=build_avatar_runtime_payload())


@router.post("/avatar/runtime")
async def update_avatar_runtime(
    request: UpdateAvatarRuntimeRequest,
    current_admin: Dict[str, Any] = Depends(get_current_admin),
):
    profile = AVATAR_RUNTIME_PROFILES.get(request.profile_id)
    if not profile:
        raise HTTPException(status_code=400, detail="Invalid avatar runtime profile")

    previous_dtype = settings.AVATAR_TORCH_DTYPE
    previous_warmup = settings.AVATAR_WARMUP_SECONDS

    try:
        settings.AVATAR_TORCH_DTYPE = profile["torch_dtype"]
        settings.AVATAR_WARMUP_SECONDS = profile["warmup_seconds"]
        reset_avatar_engines()
        avatar_engine = get_avatar_engine()
        default_avatar_path = resolve_path(settings.AVATAR_DEFAULT_IMAGE_PATH)
        if os.path.exists(default_avatar_path):
            avatar_engine.update_base_image(default_avatar_path)
        if not avatar_engine.is_loaded:
            raise RuntimeError("Avatar engine failed to reload with the selected profile.")

        persist_env_overrides(
            {
                "AVATAR_TORCH_DTYPE": str(profile["torch_dtype"]),
                "AVATAR_WARMUP_SECONDS": str(profile["warmup_seconds"]),
            }
        )
    except Exception as exc:
        settings.AVATAR_TORCH_DTYPE = previous_dtype
        settings.AVATAR_WARMUP_SECONDS = previous_warmup
        reset_avatar_engines()
        raise HTTPException(status_code=500, detail=f"Failed to switch avatar runtime profile: {exc}")

    payload = build_avatar_runtime_payload()
    payload["preset_route_cache"] = {
        "cleared": preset_route_cache.clear_all(),
        "refresh_started": True,
    }
    interact_api.refresh_preset_route_cache_in_background()
    payload["message"] = f"Avatar runtime switched to {profile['label']}"
    return JSONResponse(content=payload)


@router.post("/voice/update")
async def update_tts_voice(
    request: UpdateVoiceRequest,
    current_admin: Dict[str, Any] = Depends(get_current_admin),
):
    tts_service = get_tts_service()
    success = tts_service.set_voice(request.voice_id)
    if not success:
        raise HTTPException(status_code=400, detail="Invalid voice ID")
    cleared = preset_route_cache.clear_all()
    interact_api.refresh_preset_route_cache_in_background()
    return JSONResponse(
        content={
            "message": f"TTS voice updated to {request.voice_id}",
            "preset_route_cache": {
                "cleared": cleared,
                "refresh_started": True,
            },
        }
    )


@router.post("/voice/preview")
async def preview_tts_voice(
    request: UpdateVoiceRequest,
    current_admin: Dict[str, Any] = Depends(get_current_admin),
):
    tts_service = get_tts_service()
    voice_info = next((v for v in tts_service.available_voices if v["id"] == request.voice_id), None)
    if not voice_info:
        raise HTTPException(status_code=400, detail="Invalid voice ID")

    preview_text = f"你好，我是{voice_info['name'].split(' ')[0]}，欢迎来到景区。"
    request_id = str(uuid.uuid4())
    temp_dir = resolve_path("SoulX-FlashHead/data/temp")
    os.makedirs(temp_dir, exist_ok=True)
    audio_output_path = os.path.join(temp_dir, f"preview_{request_id}.mp3")

    tts_error = []

    def run_tts() -> None:
        try:
            tts_service = get_tts_service()
            tts_service.synthesize(preview_text, audio_output_path, voice_id=request.voice_id)
        except Exception as exc:
            tts_error.append(exc)

    tts_thread = threading.Thread(target=run_tts)
    tts_thread.start()
    tts_thread.join()

    if tts_error:
        raise HTTPException(status_code=500, detail=f"TTS preview synthesis failed: {tts_error[0]}")

    return JSONResponse(
        content={
            "audio_url": f"/static/temp/preview_{request_id}.mp3",
            "preview_text": preview_text,
        }
    )


# ─── Review Queue ─────────────────────────────────────────────────────────────

class ReviewActionRequest(BaseModel):
    review_note: Optional[str] = None
    suggested_answer: Optional[str] = None


@router.get("/review/queue")
async def get_review_queue(
    status: str = "pending",
    limit: int = 20,
    current_admin: Dict[str, Any] = Depends(get_current_admin),
):
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT id, user_query, ai_response, response_kind, sentiment,
                   focus_point, review_status, review_note, reviewed_by,
                   reviewed_at, suggested_answer, refusal_json, warnings_json,
                   observability_json, created_at
            FROM interaction_logs
            WHERE review_status = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (status, limit),
        ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            for key in ("refusal_json", "warnings_json", "observability_json"):
                try:
                    item[key.replace("_json", "")] = json.loads(item.pop(key) or "null")
                except Exception:
                    item[key.replace("_json", "")] = None
            items.append(item)
        return JSONResponse(content={"items": items, "count": len(items)})
    finally:
        conn.close()


@router.post("/review/{log_id}/approve")
async def approve_review(
    log_id: int,
    request: ReviewActionRequest,
    current_admin: Dict[str, Any] = Depends(get_current_admin),
):
    _update_review(log_id, "approved", current_admin["username"], request.review_note)
    return JSONResponse(content={"ok": True, "log_id": log_id, "status": "approved"})


@router.post("/review/{log_id}/reject")
async def reject_review(
    log_id: int,
    request: ReviewActionRequest,
    current_admin: Dict[str, Any] = Depends(get_current_admin),
):
    _update_review(log_id, "rejected", current_admin["username"], request.review_note)
    return JSONResponse(content={"ok": True, "log_id": log_id, "status": "rejected"})


@router.post("/review/{log_id}/suggest")
async def suggest_answer(
    log_id: int,
    request: ReviewActionRequest,
    current_admin: Dict[str, Any] = Depends(get_current_admin),
):
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            """
            UPDATE interaction_logs
            SET review_status='approved', suggested_answer=?, reviewed_by=?, reviewed_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (request.suggested_answer, current_admin["username"], log_id),
        )
        conn.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail=f"Log {log_id} not found")
    finally:
        conn.close()
    return JSONResponse(content={"ok": True, "log_id": log_id})


@router.get("/review/stats")
async def get_review_stats(current_admin: Dict[str, Any] = Depends(get_current_admin)):
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT review_status, COUNT(*) as count
            FROM interaction_logs
            WHERE review_status != 'auto'
            GROUP BY review_status
            """
        ).fetchall()
        stats = {row["review_status"]: row["count"] for row in rows}
        hot = conn.execute(
            """
            SELECT focus_point, COUNT(*) as cnt
            FROM interaction_logs
            WHERE created_at >= datetime('now', '-24 hours', 'localtime')
              AND focus_point != '未知' AND focus_point IS NOT NULL
            GROUP BY focus_point
            HAVING cnt >= 5
            ORDER BY cnt DESC
            """
        ).fetchall()
        return JSONResponse(content={
            "stats": stats,
            "hot_topics_needing_kb": [{"topic": r["focus_point"], "count": r["cnt"]} for r in hot],
        })
    finally:
        conn.close()


def _update_review(log_id: int, status: str, reviewed_by: str, note: Optional[str]) -> None:
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            """
            UPDATE interaction_logs
            SET review_status=?, review_note=?, reviewed_by=?, reviewed_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (status, note, reviewed_by, log_id),
        )
        conn.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail=f"Log {log_id} not found")
    finally:
        conn.close()
