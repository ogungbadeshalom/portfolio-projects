"""Message broadcast handling: validate, persist, and fan out a chat message."""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from fastapi import WebSocket
from sqlalchemy.orm import Session

from chat.ratelimit import RateLimiter
from chat.sanitize import sanitize
from chat.ws import ConnectionManager

logger = logging.getLogger(__name__)

MAX_MESSAGE_LENGTH = 1000
MAX_MESSAGES_PER_MINUTE = 10


async def handle_incoming_message(
    manager: ConnectionManager,
    limiter: RateLimiter,
    db: Session,
    room_id: int,
    user_id: int,
    username: str,
    sender: WebSocket,
    data: Dict[str, Any],
) -> None:
    """Validate + persist a ``{"type":"message","text":...}`` payload, then broadcast.

    Validation failures (over-length, over rate limit, empty) are sent back to
    the sender as an error payload rather than killing the socket.
    """
    text = data.get("text")
    if not isinstance(text, str):
        await manager.send_personal(
            sender,
            {"type": "error", "message": "Message text must be a string"},
        )
        return

    if len(text) > MAX_MESSAGE_LENGTH:
        await manager.send_personal(
            sender,
            {
                "type": "error",
                "message": f"Message exceeds {MAX_MESSAGE_LENGTH} characters",
            },
        )
        return

    if not limiter.allow(user_id, room_id):
        await manager.send_personal(
            sender,
            {"type": "error", "message": "Rate limit exceeded: one message per ~6 seconds"},
        )
        return

    clean = sanitize(text)
    if not clean:
        await manager.send_personal(
            sender,
            {"type": "error", "message": "Message is empty after sanitization"},
        )
        return

    # Persist before broadcasting so history is durable even if a fan-out fails.
    try:
        from chat.models import Message

        msg = Message(room_id=room_id, user_id=user_id, text=clean)
        db.add(msg)
        db.commit()
        db.refresh(msg)
        message_id: Optional[int] = msg.id
    except Exception:
        db.rollback()
        logger.exception("Failed to persist message user=%s room=%s", user_id, room_id)
        await manager.send_personal(
            sender, {"type": "error", "message": "Could not persist message"}
        )
        return

    payload: Dict[str, Any] = {
        "type": "message",
        "user": username,
        "text": clean,
        "ts": int(time.time()),
        "id": message_id,
        "room_id": room_id,
    }
    await manager.broadcast(room_id, payload)