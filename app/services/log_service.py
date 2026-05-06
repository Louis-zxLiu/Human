import json
import os
import sqlite3
from collections import Counter
from typing import Any, Dict, Optional

from app.core.config import resolve_path
from app.rag.llm_client import generate_chat_completion


INVALID_INPUTS = {"（没有听到声音）", "（语音识别失败）", "（未听清）"}


class LogService:
    """Persist interaction logs and expose lightweight user-profile summaries."""

    def __init__(self):
        self.db_path = resolve_path("data/processed/interaction_logs.db")
        self._init_db()

    def _init_db(self) -> None:
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS interaction_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT DEFAULT 'anonymous',
                    user_query TEXT,
                    ai_response TEXT,
                    intent_type TEXT,
                    sentiment TEXT,
                    focus_point TEXT,
                    query_scope TEXT,
                    matched_attraction TEXT,
                    recommendation_label TEXT,
                    response_kind TEXT,
                    cost_time REAL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            cursor.execute("PRAGMA table_info(interaction_logs)")
            columns = {col[1] for col in cursor.fetchall()}
            migrations = {
                "username": "ALTER TABLE interaction_logs ADD COLUMN username TEXT DEFAULT 'anonymous'",
                "query_scope": "ALTER TABLE interaction_logs ADD COLUMN query_scope TEXT",
                "matched_attraction": "ALTER TABLE interaction_logs ADD COLUMN matched_attraction TEXT",
                "recommendation_label": "ALTER TABLE interaction_logs ADD COLUMN recommendation_label TEXT",
                "response_kind": "ALTER TABLE interaction_logs ADD COLUMN response_kind TEXT",
            }
            for column, statement in migrations.items():
                if column not in columns:
                    cursor.execute(statement)
            conn.commit()
        finally:
            conn.close()

    def analyze_and_log(
        self,
        user_query: str,
        ai_response: str,
        cost_time: float,
        username: str = "anonymous",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not user_query or user_query in INVALID_INPUTS:
            return

        metadata = metadata or {}
        intent_type = "未知"
        sentiment = "中性"
        focus_point = "未知"

        try:
            labels = self._extract_summary_labels(user_query)
            intent_type = labels.get("intent_type", intent_type)
            sentiment = labels.get("sentiment", sentiment)
            focus_point = labels.get("focus_point", focus_point)
        except Exception as exc:
            print(f"[LogService] failed to analyze log labels: {exc}")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO interaction_logs
                (username, user_query, ai_response, intent_type, sentiment, focus_point,
                 query_scope, matched_attraction, recommendation_label, response_kind, cost_time)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    username,
                    user_query,
                    ai_response,
                    intent_type,
                    sentiment,
                    focus_point,
                    metadata.get("query_scope"),
                    metadata.get("matched_attraction"),
                    metadata.get("recommendation_label"),
                    metadata.get("response_kind"),
                    cost_time,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def get_user_history(self, username: str, limit: int = 50):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT user_query, ai_response, created_at
                FROM interaction_logs
                WHERE username = ?
                ORDER BY created_at DESC LIMIT ?
                """,
                (username, limit),
            )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def get_user_profile(self, username: str) -> str:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT intent_type, sentiment, focus_point, recommendation_label
                FROM interaction_logs
                WHERE username = ?
                ORDER BY created_at DESC LIMIT 20
                """,
                (username,),
            )
            rows = cursor.fetchall()
        finally:
            conn.close()

        if not rows:
            return "新游客，暂无历史偏好记录。"

        intents = [row["intent_type"] for row in rows if row["intent_type"] and row["intent_type"] != "未知"]
        sentiments = [row["sentiment"] for row in rows if row["sentiment"]]
        focuses = [row["focus_point"] for row in rows if row["focus_point"] and row["focus_point"] != "未知"]
        labels = [row["recommendation_label"] for row in rows if row["recommendation_label"]]

        profile_parts = []
        if intents:
            profile_parts.append(f"主要互动意图：{Counter(intents).most_common(1)[0][0]}")
        if focuses:
            top_focuses = "、".join(item[0] for item in Counter(focuses).most_common(3))
            profile_parts.append(f"核心关注点：{top_focuses}")
        if sentiments:
            profile_parts.append(f"近期情感倾向：{Counter(sentiments).most_common(1)[0][0]}")
        if labels:
            profile_parts.append(f"常见推荐偏好：{Counter(labels).most_common(1)[0][0]}")

        return "；".join(profile_parts) if profile_parts else "暂无明显的偏好特征。"

    def clear_logs(self) -> Dict[str, Any]:
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            removed = cursor.execute("SELECT COUNT(*) FROM interaction_logs").fetchone()[0]
            cursor.execute("DELETE FROM interaction_logs")
            cursor.execute("DELETE FROM sqlite_sequence WHERE name = 'interaction_logs'")
            conn.commit()
        finally:
            conn.close()

        return {
            "ok": True,
            "removed": removed,
            "db_path": self.db_path,
        }

    def _extract_summary_labels(self, user_query: str) -> Dict[str, str]:
        system_prompt = (
            "Return strict JSON only. Analyze the user query and extract intent_type, sentiment, focus_point. "
            "Sentiment must be one of 正面, 中性, 负面."
        )
        prompt = f"""
用户提问: "{user_query}"

请输出如下 JSON:
{{
  "intent_type": "...",
  "sentiment": "...",
  "focus_point": "..."
}}
"""
        raw = generate_chat_completion(prompt, system_prompt, temperature=0.1)
        cleaned = raw.replace("```json", "").replace("```", "").strip()
        return json.loads(cleaned)


log_service = LogService()
