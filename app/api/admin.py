import os
import shutil
import sqlite3
import threading
import uuid
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.api.auth import get_current_admin
from app.core.config import persist_env_overrides, resolve_path, settings
from app.rag.recommendation_agent import get_recommendation_display_label
from app.services.asr_tts import get_tts_service
from app.services.avatar_engine import get_avatar_engine, reset_avatar_engines

router = APIRouter()
KNOWN_QUERY_SCOPES = {"FACT", "RECOMMEND", "ANALYTICS"}

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
            "knowledge_base": 'conda run -p "D:/Human/env" python -m app.cli prepare-kb',
            "behavior_data": 'conda run -p "D:/Human/env" python -m app.cli prepare-data',
            "unified_eval": 'conda run -p "D:/Human/env" python -m app.cli eval-unified',
            "demo_seed": 'conda run -p "D:/Human/env" python -m app.cli seed-demo-logs --reset',
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
            "updated_at": None,
            "summary": "尚未生成统一评测报告。",
            "command": 'conda run -p "D:/Human/env" python -m app.cli eval-unified',
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
            "updated_at": get_path_mtime(str(report_path)),
            "summary": f"统一评测报告读取失败：{exc}",
            "command": 'conda run -p "D:/Human/env" python -m app.cli eval-unified',
        }

    source_scores = {
        key: {
            "accuracy": value.get("accuracy"),
            "pass_rate": value.get("pass_rate"),
            "count": value.get("count"),
        }
        for key, value in (payload.get("by_gold_source") or {}).items()
    }
    failure_count = len(payload.get("failures") or [])
    overall_score = payload.get("overall_score")
    return {
        "ok": bool(payload.get("ok")),
        "available": True,
        "overall_score": overall_score,
        "case_count": payload.get("case_count", 0),
        "failure_count": failure_count,
        "updated_at": get_path_mtime(str(report_path)),
        "source_scores": source_scores,
        "summary": f"统一评测 {overall_score}/100，失败样例 {failure_count} 个。",
        "command": 'conda run -p "D:/Human/env" python -m app.cli eval-unified',
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
                "detail": "评委会重点看本地知识库与游客行为数据能否稳定支撑回答，建议先运行数据准备命令。",
                "action": "运行 prepare-data 与 prepare-kb 后刷新后台。",
            }
        )

    if eval_status.get("available"):
        score = float(eval_status.get("overall_score") or 0)
        if score >= 95:
            recommendations.append(
                {
                    "priority": "高",
                    "title": "把统一评测分数放进演示亮点",
                    "detail": f"当前统一评测 {score}/100，可直接支撑“事实问答准确率高于 90%”这一赛题要求。",
                    "action": "PPT 和演示视频中展示评测报告截图。",
                }
            )
        else:
            recommendations.append(
                {
                    "priority": "高",
                    "title": "优先修复统一评测低分项",
                    "detail": "当前评测未达到演示安全线，建议先处理失败样例再录制视频。",
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
                "action": "补充对应 DOCX 资料或在演示中说明系统会拒绝无证据问题。",
            }
        )

    if recommendation_distribution:
        top_label = max(recommendation_distribution.items(), key=lambda item: item[1])[0]
        recommendations.append(
            {
                "priority": "中",
                "title": f"{top_label}路线关注度较高",
                "detail": "推荐标签分布可以转化为景区运营洞察，说明系统不只会问答，也能帮助规划讲解资源。",
                "action": "演示后台推荐标签图表，并切到对应前台路线卡。",
            }
        )

    if avg_cost_time > 5:
        recommendations.append(
            {
                "priority": "中",
                "title": "演示前控制长回答和视频生成耗时",
                "detail": f"当前平均响应耗时约 {avg_cost_time}s，语音视频链路建议使用短问短答展示。",
                "action": "演示时优先选择 20-40 秒口播问题。",
            }
        )

    if total_interactions == 0:
        recommendations.append(
            {
                "priority": "高",
                "title": "开场前预热演示数据",
                "detail": "后台空图表会削弱管理端观感，建议开场前注入一组演示日志。",
                "action": '运行 conda run -p "D:/Human/env" python -m app.cli seed-demo-logs --reset。',
            }
        )

    recommendations.append(
        {
            "priority": "低",
            "title": "演示默认切换数字人高质量模式",
            "detail": "赛题 20 分体验项会看口型同步、语音合成和表情观感，后台高质量模式更适合录屏。",
            "action": "后台选择“高质量”，确认音色试听正常后再录制。",
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
        avatar_dir = resolve_path("data/processed")
        os.makedirs(avatar_dir, exist_ok=True)
        target_path = os.path.join(avatar_dir, "default_avatar.jpg")
        with open(target_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        avatar_engine = get_avatar_engine()
        avatar_engine.update_base_image(target_path)
        return JSONResponse(content={"message": "Default avatar image updated successfully"})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"更新默认头像失败: {exc}")


class UpdateVoiceRequest(BaseModel):
    voice_id: str


class UpdateAvatarRuntimeRequest(BaseModel):
    profile_id: str


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
        default_avatar_path = resolve_path("data/processed/default_avatar.jpg")
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
    return JSONResponse(content={"message": f"TTS voice updated to {request.voice_id}"})


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
