"""Room routes: creation and listing."""
from __future__ import annotations

from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from chat.deps import get_current_user
from chat.database import get_session
from chat.models import Room, User

router = APIRouter(prefix="/api/rooms", tags=["rooms"])


class RoomIn(BaseModel):
    """Create-room request body."""

    name: str = Field(..., min_length=1, max_length=128)


def _serialize(room: Room, db: Session) -> Dict[str, object]:
    """Render a room row as a JSON-friendly dict."""
    creator_name: str | None = None
    if room.created_by is not None:
        creator = db.get(User, room.created_by)
        creator_name = creator.username if creator else None
    return {
        "id": room.id,
        "name": room.name,
        "created_by": room.created_by,
        "creator": creator_name,
        "created_at": room.created_at.isoformat() if room.created_at else None,
    }


@router.post("", status_code=201)
def create_room(
    payload: RoomIn, db: Session = Depends(get_session), user: User = Depends(get_current_user)
) -> Dict[str, object]:
    """Create a room owned by ``user``.

    Returns ``409`` if a room with that name already exists.
    """
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Room name cannot be blank")
    existing = db.execute(select(Room).where(Room.name == name)).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="Room already exists")
    room = Room(name=name, created_by=user.id)
    db.add(room)
    db.commit()
    db.refresh(room)
    return _serialize(room, db)


@router.get("")
def list_rooms(
    db: Session = Depends(get_session), user: User = Depends(get_current_user)
) -> List[Dict[str, object]]:
    """List all rooms, sorted newest-first."""
    rooms = db.execute(select(Room).order_by(Room.created_at.desc())).scalars().all()
    return [_serialize(r, db) for r in rooms]


@router.get("/{room_id}")
def get_room(
    room_id: int, db: Session = Depends(get_session), user: User = Depends(get_current_user)
) -> Dict[str, object]:
    """Fetch a single room by id, or ``404``."""
    room = db.get(Room, room_id)
    if room is None:
        raise HTTPException(status_code=404, detail="Room not found")
    return _serialize(room, db)