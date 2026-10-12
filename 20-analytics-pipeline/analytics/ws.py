"""WebSocket live-update broadcasting for the dashboard.

Every connected dashboard client gets pushed a small JSON envelope
(the real-time event counters) on a fixed interval (default 5s). Clients that
disconnect are removed; reconnects are handled automatically by the browser SDK
in the templates.

The broadcaster is started from the FastAPI lifespan and shares the process
:class:`~analytics.store.Store` for computation.
"""

from __future__ import annotations

import asyncio
import logging
from typing import List

from fastapi import WebSocket

from analytics.config import get_settings
from analytics.query import dashboard
from analytics.store import Store

logger = logging.getLogger(__name__)


class DashboardBroadcaster:
    """Registry of connected sockets + an interval broadcaster task."""

    def __init__(self, store: Store, *, settings=None) -> None:
        self.store = store
        self.settings = settings or get_settings()
        self.clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()
        self._task: asyncio.Task | None = None

    def start(self) -> "DashboardBroadcaster":
        self._task = asyncio.create_task(self._broadcast_loop())
        return self

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None
        await self.disconnect_all()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self.clients.add(ws)
        # Push an immediate snapshot on connect.
        await self._send_one(ws)

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self.clients.discard(ws)

    async def disconnect_all(self) -> None:
        async with self._lock:
            sockets = list(self.clients)
            self.clients.clear()
        for ws in sockets:
            try:
                await ws.close()
            except Exception:  # noqa: BLE001
                pass

    async def _send_one(self, ws: WebSocket) -> None:
        try:
            await ws.send_json(self._payload())
        except Exception:  # noqa: BLE001 - a dead socket is dropped next pass
            await self.disconnect(ws)

    def _payload(self) -> dict:
        data = dashboard(self.store)
        return {"type": "dashboard", "data": data}

    async def _broadcast_loop(self) -> None:
        interval = self.settings.broadcast_interval_seconds
        while True:
            await asyncio.sleep(interval)
            async with self._lock:
                sockets = list(self.clients)
            for ws in sockets:
                await self._send_one(ws)


__all__ = ["DashboardBroadcaster"]