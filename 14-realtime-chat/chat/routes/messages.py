"""Message history route: paginated, chronological (oldest-first by default)."""
from __future__ import annotations

from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from chat.deps import get_current_user
from chat.database import get_session
from chat.models import Message, Room, User

router = APIRouter(prefix="/api/rooms", tags=["messages"])


def _serialize(msg: Message) -> Dict[str, object]:
    """Render a message with its resolved username."""
    username = msg.user.username if msg.user else None
    return {
        "id": msg.id,
        "room_id": msg.room_id,
        "user_id": msg.user_id,
        "username": username,
        "text": msg.text,
        "created_at": msg.created_at.isoformat() if msg.created_at else None,
    }


@router.get("/{room_id}/messages")
def list_messages(
    room_id: int,
    limit: int = Query(50, ge=1, le=200),
    before_id: int = Query(None, description="Return messages with id < before_id"),
    db: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> List[Dict[str, object]]:
    """Return the most recent ``limit`` messages for a room, oldest-first.

    Supports reconnection: pass ``before_id`` to fetch messages older than a
    client's last seen message id. The final list is reversed so the response
    is always chronological (oldest at index 0).
    """
    if db.get(Room, room_id) is None:
        raise HTTPException(status_code=404, detail="Room not found")

    stmt = (
        select(Message)
        .options(joinedload(Message.user))
        .where(Message.room_id == room_id)
        .order_by(Message.id.desc())  # newest first for the "last N"
    )
    if before_id is not None:
        stmt = stmt.where(Message.id < before_id)
    rows = db.execute(stmt.limit(limit)).scalars().all()
    # Reverse to oldest-first chronological order for the client.
    return [_serialize(m) for m in reversed(rows)]