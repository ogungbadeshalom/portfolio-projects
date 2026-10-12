"""FastAPI application entry point for the URL shortener.

Run with::

    uvicorn urlshort.main:app --reload --port 8000

The module exposes both a ready-to-use :data:`app` instance and a
:func:`create_app` factory. Tests build an isolated app and override the
``get_db`` dependency to point at their own temporary database.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from sqlalchemy import text

from urlshort.config import settings
from urlshort.database import engine, get_db, init_db
from urlshort.routes import redirect, shorten, stats

limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Create tables on startup, then shut down the engine on exit."""
    await init_db()
    try:
        yield
    finally:
        await engine.dispose()


def _build_app() -> FastAPI:
    """Construct and configure a :class:`FastAPI` instance (no router mounts)."""
    app = FastAPI(
        title="URL Shortener",
        description="A minimal FastAPI + SQLite URL shortener.",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(RateLimitExceeded)
    async def _rate_limit_handler(request: Request, exc: RateLimitExceeded):
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded. Try again shortly."},
        )

    @app.get("/health")
    async def health() -> dict:
        """Confirm the app and database are reachable."""
        db_status = "ok"
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception:  # noqa: BLE001 - report any backend failure as degraded
            db_status = "error"
        return {"status": "ok", "database": db_status}

    app.include_router(shorten.router)
    app.include_router(redirect.router)
    app.include_router(stats.router)
    return app


#: Global app instance used by ``uvicorn urlshort.main:app``.
app = _build_app()


def create_app(**settings_overrides: Any) -> FastAPI:
    """Build a fresh, un-mounted-by-default FastAPI app.

    ``settings_overrides`` is accepted for signature compatibility so callers
    may pass overrides; the returned app still uses the shared router
    definitions. Tests typically call this and then *override the
    ``get_db`` dependency* (see ``tests/conftest.py``):

        app = create_app()
        app.dependency_overrides[get_db] = override

    Returns:
        A configured :class:`FastAPI` instance ready for a TestClient.
    """
    return _build_app()