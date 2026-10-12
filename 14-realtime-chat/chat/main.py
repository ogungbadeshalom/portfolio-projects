"""FastAPI application entry point for the real-time chat.

Mounts:
    * REST routers under ``/api`` (auth, rooms, messages).
    * The WebSocket endpoint ``/ws/rooms/{room_id}``.
    * Jinja HTML templates and the ``/static`` mount.

Run with::

    uvicorn chat.main:app --port 8000
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Dict

from fastapi import Depends, FastAPI, HTTPException, Query, WebSocket
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request
from sqlalchemy.orm import Session

from chat.database import get_session, init_db
from chat.deps import verify_ws_token
from chat.ratelimit import RateLimiter
from chat.routes import auth as auth_routes
from chat.routes import messages as messages_routes
from chat.routes import rooms as rooms_routes
from chat.ws import ConnectionManager
from chat.ws_handlers.connection import handle_connect

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
_BASE_DIR = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(_BASE_DIR / "templates"))
STATIC_DIR = _BASE_DIR / "static"

# --------------------------------------------------------------------------- #
# Application state
# --------------------------------------------------------------------------- #
manager = ConnectionManager()
rate_limiter = RateLimiter()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Create tables on startup and clean up nothing on shutdown."""
    init_db()
    logger.info("Chat database initialised")
    yield


app = FastAPI(
    title="Real-Time Chat",
    version="1.0.0",
    description="Real-time WebSocket chat with rooms, typing and presence.",
    lifespan=lifespan,
)

# --------------------------------------------------------------------------- #
# Routers (REST)
# --------------------------------------------------------------------------- #
app.include_router(auth_routes.router)
app.include_router(rooms_routes.router)
app.include_router(messages_routes.router)

# --------------------------------------------------------------------------- #
# WebSocket endpoint
# --------------------------------------------------------------------------- #
@app.websocket("/ws/rooms/{room_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    room_id: int,
    token: str = Query(None, description="JWT passed via the query string"),
    db: Session = Depends(get_session),
) -> None:
    """Serve the real-time channel for a room.

    The socket is accepted only after the JWT in ``?token=...`` validates; a
    missing/invalid token is rejected with a ``403`` close. Everything after
    connect is delegated to :func:`chat.ws_handlers.connection.handle_connect`.
    """
    # Raise before the socket is accepted so bad tokens get a denied handshake.
    user_id, username = verify_ws_token(token)
    await handle_connect(
        manager, rate_limiter, db, room_id, user_id, username, websocket
    )


# --------------------------------------------------------------------------- #
# Web UI (templates)
# --------------------------------------------------------------------------- #
@app.get("/", include_in_schema=False)
def index(request: Request) -> Dict[str, object]:
    """Serve the login / room-list landing page."""
    return TEMPLATES.TemplateResponse(request, "login.html", {"title": "Login"})


@app.get("/rooms", include_in_schema=False)
def rooms_page(request: Request) -> Dict[str, object]:
    """Serve the room list + create page."""
    return TEMPLATES.TemplateResponse(request, "rooms.html", {"title": "Rooms"})


@app.get("/rooms/{room_id}", include_in_schema=False)
def chat_page(request: Request, room_id: int) -> Dict[str, object]:
    """Serve the chat page for a specific room."""
    return TEMPLATES.TemplateResponse(
        request, "chat.html", {"title": "Chat", "room_id": room_id}
    )


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")