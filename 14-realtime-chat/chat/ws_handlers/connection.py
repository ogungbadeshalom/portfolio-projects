"""WebSocket connection lifecycle and message dispatch.

This module owns the accept -> membership -> presence -> receive-loop flow for
the ``/ws/rooms/{id}`` endpoint. All pushes to the socket are done via the
:class:`~chat.ws.ConnectionManager`, and every JSON message is validated and
handed to a focused handler.

The receive loop itself lives here so that ``chat/main.py`` stays thin.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from chat.ratelimit import RateLimiter
from chat.ws import ConnectionManager
from chat.ws_handlers.broadcast import handle_incoming_message
from chat.ws_handlers.presence import (
    broadcast_presence,
    send_presence_to,
)
from chat.ws_handlers.typing import broadcast_typing

logger = logging.getLogger(__name__)


async def handle_connect(
    manager: ConnectionManager,
    limiter: RateLimiter,
    db: Session,
    room_id: int,
    user_id: int,
    username: str,
    websocket: WebSocket,
) -> None:
    """Register a socket, record membership, announce join/presence, and loop.

    This is the long-lived entry point called from the WebSocket route. It runs
    until the client disconnects (raising :class:`WebSocketDisconnect`), at
    which point the socket is deregistered and the room presence is refreshed.
    """
    await manager.connect(room_id, websocket, username)

    # Persist membership (best-effort; a duplicate row is silently ignored).
    _record_membership(db, user_id, room_id)

    # Tell the newcomer who is online, then announce to everyone else and
    # refresh the room-wide presence list so every peer stays in sync.
    await send_presence_to(manager, room_id, websocket)
    await manager.broadcast(room_id, {"type": "join", "user": username}, exclude=websocket)
    await broadcast_presence(manager, room_id, exclude=websocket)

    try:
        await _receive_loop(
            manager, limiter, db, room_id, user_id, username, websocket
        )
    except WebSocketDisconnect:
        logger.debug(
            "Client disconnected user=%s room=%s", user_id, room_id
        )
    finally:
        await manager.disconnect(room_id, websocket)


async def _receive_loop(
    manager: ConnectionManager,
    limiter: RateLimiter,
    db: Session,
    room_id: int,
    user_id: int,
    username: str,
    websocket: WebSocket,
) -> None:
    """Read JSON frames and dispatch each to its handler until disconnect."""
    while True:
        try:
            raw = await websocket.receive_text()
        except WebSocketDisconnect:
            raise
        data: Dict[str, Any]
        try:
            data = _parse_json(raw)
        except ValueError:
            await manager.send_personal(
                websocket, {"type": "error", "message": "Malformed JSON"}
            )
            continue

        msg_type = data.get("type")
        if msg_type == "message":
            await handle_incoming_message(
                manager, limiter, db, room_id, user_id, username, websocket, data
            )
        elif msg_type == "typing":
            await broadcast_typing(manager, room_id, username, websocket)
        else:
            await manager.send_personal(
                websocket, {"type": "error", "message": "Unknown message type"}
            )


def _parse_json(raw: str) -> Dict[str, Any]:
    """Parse a JSON string into a dict, raising ``ValueError`` on failure."""
    import json

    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object")
    return data


def _record_membership(db: Session, user_id: int, room_id: int) -> None:
    """Insert a RoomMembership row (idempotent via unique pair).

    Ignored rows: where the room doesn't exist or the pair already exists.
    """
    try:
        from sqlalchemy import select

        from chat.models import RoomMembership

        existing = db.execute(
            select(RoomMembership).where(
                RoomMembership.user_id == user_id,
                RoomMembership.room_id == room_id,
            )
        ).scalar_one_or_none()
        if existing is None:
            db.add(RoomMembership(user_id=user_id, room_id=room_id))
            db.commit()
    except Exception:
        db.rollback()
        logger.warning(
            "Could not record membership user=%s room=%s", user_id, room_id, exc_info=True
        )