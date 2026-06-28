"""
Persistent session store backed by SQLite (aiosqlite for async access).
Replaces the in-memory CONVERSATION_SESSIONS dict in interact.py.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict

import aiosqlite

from app.core.config import resolve_path


DB_PATH = resolve_path("data/processed/graph_sessions.db")

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS conversation_sessions (
    session_key TEXT PRIMARY KEY,
    memory_json TEXT NOT NULL DEFAULT '{}',
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
"""


async def _ensure_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(_CREATE_TABLE)
        await db.commit()


async def get_session_memory(session_key: str) -> Dict[str, Any]:
    """Return the stored memory dict for session_key, or {} if not found."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT memory_json FROM conversation_sessions WHERE session_key = ?",
                (session_key,),
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return json.loads(row[0]) or {}
    except Exception:
        pass
    return {}


async def save_session_memory(session_key: str, memory: Dict[str, Any]) -> None:
    """Upsert the memory dict for session_key."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """
                INSERT INTO conversation_sessions (session_key, memory_json, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(session_key) DO UPDATE SET
                    memory_json = excluded.memory_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (session_key, json.dumps(memory, ensure_ascii=False)),
            )
            await db.commit()
    except Exception as exc:
        print(f"[SessionStore] failed to save session {session_key}: {exc}")


async def init_store() -> None:
    """Call once at startup to ensure the database and table exist."""
    await _ensure_db()
