"""WebSocket connection management for the chat application.

The :class:`ConnectionManager` tracks the active WebSocket connections grouped
by room, along with the display username of each connected peer so presence
lists can be rendered without an extra DB lookup.

All sends are wrapped in ``try/except`` because a peer may close the socket at
any moment; a dead socket is discarded so it can never block a broadcast.
"""
from __future__ import annotations

import logging
from typing import Dict, Any, List, Optional, Set

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Track active WebSocket connections per room and broadcast to them.

    Data model::

        self._rooms: dict[room_id, dict[WebSocket, str(username)]]

    Keeping the username alongside each socket lets :meth:`list_online`
    build the ``online`` presence list cheaply.
    """

    def __init__(self) -> None:
        self._rooms: Dict[int, Dict[WebSocket, str]] = {}

    # ------------------------------------------------------------------ #
    # Connection lifecycle
    # ------------------------------------------------------------------ #
    async def connect(self, room_id: int, websocket: WebSocket, username: str) -> None:
        """Accept a socket and register it under ``room_id``.

        ``connect`` is idempotent w.r.t. re-registration: if the same socket
        object reconnects we simply overwrite its username.
        """
        await websocket.accept()
        room_sockets = self._rooms.setdefault(room_id, {})
        room_sockets[websocket] = username

    async def disconnect(self, room_id: int, websocket: WebSocket) -> None:
        """Remove a socket from the room and broadcast the updated presence."""
        room_sockets = self._rooms.get(room_id)
        if room_sockets is None:
            return
        username = room_sockets.pop(websocket, None)
        if username is None:
            return
        try:
            await websocket.close()
        except Exception:  # pragma: no cover - socket may already be dead
            logger.debug("Failed closed socket during disconnect", exc_info=True)
        if not room_sockets:
            # Last connection gone: drop the room entirely.
            self._rooms.pop(room_id, None)
        else:
            await self.broadcast(
                room_id,
                {"type": "leave", "user": username},
            )
            await self.broadcast(
                room_id,
                {"type": "presence", "online": await self.list_online(room_id)},
            )

    # ------------------------------------------------------------------ #
    # Sending
    # ------------------------------------------------------------------ #
    async def send_personal(self, websocket: WebSocket, data: Dict[str, Any]) -> None:
        """Send a JSON payload to a single socket, tolerating failures."""
        try:
            await websocket.send_json(data)
        except Exception:
            logger.debug("Failed personal send (socket likely closed)", exc_info=True)

    async def broadcast(
        self,
        room_id: int,
        data: Dict[str, Any],
        exclude: Optional[WebSocket] = None,
    ) -> None:
        """Send ``data`` to every socket in a room except an optional one.

        Dead sockets are discarded as they are hit so a single closed peer
        cannot raise or block delivery to the others.
        """
        room_sockets = self._rooms.get(room_id)
        if not room_sockets:
            return
        for ws in list(room_sockets):
            if ws is exclude:
                continue
            try:
                await ws.send_json(data)
            except Exception:
                # Remove the dead socket so future broadcasts skip it.
                room_sockets.pop(ws, None)
                logger.debug("Discarded dead socket from room %s", room_id, exc_info=True)
        if not room_sockets:
            self._rooms.pop(room_id, None)

    # ------------------------------------------------------------------ #
    # Introspection
    # ------------------------------------------------------------------ #
    async def list_online(self, room_id: int) -> List[str]:
        """Return the sorted list of usernames currently connected to a room."""
        room_sockets = self._rooms.get(room_id) or {}
        usernames = {username for username in room_sockets.values()}
        return sorted(usernames)

    async def username_of(self, room_id: int, websocket: WebSocket) -> Optional[str]:
        """Return the username registered for a socket in a room, if any."""
        room_sockets = self._rooms.get(room_id) or {}
        return room_sockets.get(websocket)

    @property
    def rooms(self) -> Dict[int, Set[WebSocket]]:
        """Expose the room->sockets mapping (for tests/introspection)."""
        return {rid: set(socks) for rid, socks in self._rooms.items()}