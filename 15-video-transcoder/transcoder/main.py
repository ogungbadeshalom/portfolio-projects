"""FastAPI application entrypoint.

Run with::

    uvicorn transcoder.main:app --port 8080
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import config, models
from .queue import JobQueue
from .routes import jobs, ws

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def build_app(
    *,
    database_uri: str = config.DATABASE_URI,
    max_workers: int = config.MAX_CONCURRENT,
    max_retries: int = config.MAX_RETRIES,
    on_event=None,
) -> FastAPI:
    """Application factory.  Overridable for tests (in-memory DB, fast jobs)."""
    config.ensure_dirs()
    session_factory = models.make_session_factory(database_uri)

    queue = JobQueue(
        session_factory,
        max_workers=max_workers,
        max_retries=max_retries,
        on_event=on_event,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await queue.start()
        yield
        await queue.stop()

    app = FastAPI(title="Video Transcoder Queue", lifespan=lifespan)
    app.state.session_factory = session_factory
    app.state.queue = queue

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(jobs.router)
    app.include_router(ws.router)

    static_dir = config.BASE_DIR / "transcoder" / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    return app


app = build_app()