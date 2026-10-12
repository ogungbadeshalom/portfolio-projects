"""Presence handling: who is online in a room."""
from __future__ import annotations

from typing import Dict, List

from fastapi import WebSocket

from chat.ws import ConnectionManager


async def presence_payload(manager: ConnectionManager, room_id: int) -> Dict[str, object]:
    """Build the ``{"type": "presence", "online": [...]}`` payload for a room."""
    online: List[str] = await manager.list_online(room_id)
    return {"type": "presence", "online": online}


async def send_presence_to(
    manager: ConnectionManager, room_id: int, websocket: WebSocket
) -> None:
    """Deliver the current online list to a single joining socket."""
    await manager.send_personal(websocket, await presence_payload(manager, room_id))


async def broadcast_presence(
    manager: ConnectionManager, room_id: int, exclude: WebSocket | None = None
) -> None:
    """Announce the updated online list to the whole room."""
    await manager.broadcast(room_id, await presence_payload(manager, room_id), exclude=exclude)