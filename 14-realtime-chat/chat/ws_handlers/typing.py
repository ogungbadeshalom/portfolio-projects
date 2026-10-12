"""Typing-indicator handling: fan out a typing event to peers (not sender)."""
from __future__ import annotations

from typing import Dict

from fastapi import WebSocket

from chat.ws import ConnectionManager


async def broadcast_typing(
    manager: ConnectionManager,
    room_id: int,
    username: str,
    sender: WebSocket,
) -> None:
    """Announce ``{"type":"typing","user":username}`` to everyone but ``sender``."""
    payload: Dict[str, str] = {"type": "typing", "user": username}
    await manager.broadcast(room_id, payload, exclude=sender)