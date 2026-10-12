"""FastAPI entrypoint for the analytics pipeline.

Exposes the ingestion API, the OLAP query endpoints and the live dashboard:

    * ``POST /api/track``            — ingest one event (async, batched)
    * ``POST /api/track/batch``      — ingest a batch (browser SDK)
    * ``GET  /api/events``           — query events with filters
    * ``GET  /api/funnel``           — funnel analysis
    * ``GET  /api/retention``        — retention cohorts
    * ``GET  /api/top-pages``        — top pages by views
    * ``GET  /api/dashboard``        — everything the dashboard needs
    * ``WS   /ws/dashboard``         — live push of dashboard data
    * ``GET  /dashboard``, ``/events``, ``/static/*``, ``/sdk/analytics.js``

A module-level ``app`` is built at import time so ``analytics/__init__.py`` can
re-export it as the package's public entrypoint; ``create_app()`` is the
factory used by tests and ``uvicorn analytics.main:app``.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi import Request

from analytics import query as query_mod
from analytics.config import PACKAGE_DIR, get_settings
from analytics.ingestion import IngestPipe
from analytics.models import Event
from analytics.store import get_store
from analytics.ws import DashboardBroadcaster

logger = logging.getLogger(__name__)

TEMPLATES = Jinja2Templates(directory=str(PACKAGE_DIR / "templates"))
STATIC_DIR = Path(PACKAGE_DIR / "static")


def create_app(
    *,
    store=None,
    batch: bool = True,
    broadcast: bool = True,
) -> FastAPI:
    """Build the analytics FastAPI application.

    ``store`` lets tests inject a purpose-built store; ``batch``/``broadcast``
    toggle the background flusher and WebSocket broadcaster respectively.
    """
    settings = get_settings()
    store = store or get_store()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        pipe = IngestPipe(store, settings=settings)
        pipe.start()
        broadcaster = DashboardBroadcaster(store, settings=settings)
        if broadcast:
            broadcaster.start()
        app.state.pipe = pipe
        app.state.broadcaster = broadcaster
        try:
            yield
        finally:
            # Auto-flush on shutdown: never drop queued events.
            await pipe.close()
            await broadcaster.stop()

    app = FastAPI(title="Analytics Pipeline", version="1.0.0", lifespan=lifespan)
    app.state.store = store

    # ---- ingestion --------------------------------------------------------
    @app.post("/api/track")
    async def track(body: Event, request: Request):
        # For single-event calls we still accept a bare object; batching is
        # handled by /api/track/batch.
        try:
            event = body.anonymize()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        pipe: IngestPipe = request.app.state.pipe
        if pipe is None:
            raise HTTPException(status_code=503, detail="ingestion not ready")
        await pipe.enqueue(event)
        return {"ok": True, "queued": 1, "estimated": pipe.estimated_size}

    @app.post("/api/track/batch")
    async def track_batch(events: List[Event], request: Request):
        pipe: IngestPipe = request.app.state.pipe
        if pipe is None:
            raise HTTPException(status_code=503, detail="ingestion not ready")
        count = 0
        for ev in events:
            await pipe.enqueue(ev.anonymize())
            count += 1
        # A client-originated batch is often small; write it through now so the
        # dashboard reflects it without waiting for the next interval flush.
        if batch:
            pipe.flush()
        return {"ok": True, "queued": count}

    # ---- queries ------------------------------------------------------------
    def _window_params(start: Optional[int], end: Optional[int], hours: Optional[int]):
        import time

        if hours is not None:
            now = int(time.time())
            return now - int(hours) * 3600, now
        return (int(start) if start is not None else None,
                int(end) if end is not None else None)

    @app.get("/api/events")
    def events(
        event: Optional[str] = None,
        user: Optional[str] = None,
        start: Optional[int] = None,
        end: Optional[int] = None,
        limit: int = Query(default=200, le=1000),
    ):
        rows = query_mod.events_query(
            store,
            event_name=event,
            user_id=user,
            start=start,
            end=end,
            limit=limit,
        )
        return rows

    @app.get("/api/funnel")
    def funnel(
        steps: str = Query(description="comma-separated event steps"),
        start: Optional[int] = None,
        end: Optional[int] = None,
        window_seconds: int = Query(default=86400),
    ):
        step_list = [s.strip() for s in steps.split(",") if s.strip()]
        if not step_list:
            raise HTTPException(status_code=400, detail="steps is required")
        return query_mod.funnel(store, step_list, start=start, end=end,
                                window_seconds=window_seconds)

    @app.get("/api/retention")
    def retention(
        start: Optional[int] = None,
        end: Optional[int] = None,
        days: int = Query(default=7, ge=1, le=30),
    ):
        return query_mod.retention_cohorts(store, start=start, end=end, days=days)

    @app.get("/api/top-pages")
    def top_pages(
        hours: Optional[int] = None,
        start: Optional[int] = None,
        end: Optional[int] = None,
        limit: int = Query(default=10, le=100),
    ):
        s, e = _window_params(start, end, hours)
        return query_mod.top_pages(store, start=s, end=e, limit=limit)

    @app.get("/api/dashboard")
    def dashboard():
        return query_mod.dashboard(store)

    # ---- websocket -----------------------------------------------------------
    @app.websocket("/ws/dashboard")
    async def ws_dashboard(websocket: WebSocket):
        broadcaster: DashboardBroadcaster = websocket.app.state.broadcaster
        await broadcaster.connect(websocket)
        try:
            while True:
                # Keep the socket alive; the loop only closes on disconnect.
                await websocket.receive_text()
        except (WebSocketDisconnect, Exception):  # noqa: BLE001
            await broadcaster.disconnect(websocket)

    # ---- pages ----------------------------------------------------------------
    @app.get("/dashboard")
    def dashboard_page(request: Request):
        return TEMPLATES.TemplateResponse(
            request, "dashboard.html", {}
        )

    @app.get("/events")
    def events_page(request: Request, event: Optional[str] = None,
                    user: Optional[str] = None):
        rows = query_mod.events_query(
            store, event_name=event, user_id=user, limit=100
        )
        return TEMPLATES.TemplateResponse(
            request,
            "events.html",
            {"events": rows, "event": event, "user": user},
        )

    @app.get("/sdk/analytics.js")
    def analytics_sdk():
        return FileResponse(STATIC_DIR.parent / "sdk" / "analytics.js",
                            media_type="application/javascript")

    # Must come after routes (order matters for dispatch).
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    return app


#: Module-level entrypoint — this is what `analytics/__init__.py` imports and
#: what `uvicorn analytics.main:app` serves.
app = create_app()

__all__ = ["app", "create_app"]