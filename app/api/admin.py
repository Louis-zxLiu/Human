import os
import shutil
import sqlite3
import threading
import uuid
from typing import Any, Dict

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.api.auth import get_current_admin
from app.core.config import resolve_path, settings
from app.services.asr_tts import get_tts_service
from app.services.avatar_engine import get_avatar_engine

router = APIRouter()


def get_db_path() -> str:
    return resolve_path("data/processed/interaction_logs.db")


def build_data_status() -> Dict[str, Any]:
    chroma_dir = resolve_path(settings.CHROMA_DB_DIR)
    behavior_db = resolve_path("data/processed/tourist_behavior.db")
    kb_dir = resolve_path(settings.KNOWLEDGE_BASE_DIR)

    chroma_ready = os.path.exists(chroma_dir) and bool(os.listdir(chroma_dir))
    behavior_ready = os.path.exists(behavior_db)
    kb_docs = []
    if os.path.exists(kb_dir):
        kb_docs = [name for name in os.listdir(kb_dir) if name.lower().endswith((".docx", ".xlsx", ".txt", ".csv"))]

    return {
        "preflight_ok": chroma_ready and behavior_ready,
        "knowledge_base_ready": chroma_ready,
        "behavior_db_ready": behavior_ready,
        "knowledge_doc_count": len(kb_docs),
        "knowledge_documents": kb_docs[:10],
    }


@router.get("/dashboard")
async def get_dashboard_data(current_admin: Dict[str, Any] = Depends(get_current_admin)):
    db_path = get_db_path()
    if not os.path.exists(db_path):
        return JSONResponse(
            content={
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
            }
        )

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
            row["query_scope"] or "UNKNOWN": row["count"]
            for row in cursor.execute(
                "SELECT query_scope, COUNT(*) AS count FROM interaction_logs GROUP BY query_scope"
            ).fetchall()
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
        recommendation_label_distribution = {
            row["recommendation_label"]: row["count"]
            for row in cursor.execute(
                """
                SELECT recommendation_label, COUNT(*) AS count
                FROM interaction_logs
                WHERE recommendation_label IS NOT NULL AND recommendation_label != ''
                GROUP BY recommendation_label
                """
            ).fetchall()
        }
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

        return JSONResponse(
            content={
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
            }
        )
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


@router.get("/voice/list")
async def get_available_voices(current_admin: Dict[str, Any] = Depends(get_current_admin)):
    tts_service = get_tts_service()
    return JSONResponse(
        content={
            "current_voice": tts_service.get_current_voice(),
            "available_voices": tts_service.available_voices,
        }
    )


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
