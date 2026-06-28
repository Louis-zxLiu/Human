"""Admin real-time notification channel via WebSocket."""
from __future__ import annotations
import asyncio
from typing import Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()
_admin_connections: Set[WebSocket] = set()


@router.websocket("/v1/admin/notify")
async def admin_notify_ws(websocket: WebSocket):
    await websocket.accept()
    _admin_connections.add(websocket)
    try:
        while True:
            await websocket.receive_text()  # keep alive
    except WebSocketDisconnect:
        _admin_connections.discard(websocket)
    except Exception:
        _admin_connections.discard(websocket)


async def broadcast_pending_review(log_id: int) -> None:
    """Broadcast to all connected admin clients that a new review is pending."""
    if not _admin_connections:
        return
    payload = {"type": "review_pending", "log_id": log_id}
    dead = set()
    for ws in _admin_connections:
        try:
            await ws.send_json(payload)
        except Exception:
            dead.add(ws)
    _admin_connections.difference_update(dead)


def notify_pending_review(log_id: int) -> None:
    """Fire-and-forget: schedule broadcast on the running event loop."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(broadcast_pending_review(log_id))
    except Exception:
        pass
