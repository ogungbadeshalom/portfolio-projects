"""Pytest fixtures for the chat application.

Isolation strategy (the spec's preferred approach):

    * A fresh SQLite database file is created for every test.
    * The app's ``get_session`` dependency is overridden to hand out sessions
      bound to that test database, so routes and the WS handler never touch
      the real ``chat.db``.
    * The module-global ``ENGINE`` is monkeypatched so the lifespan's
      ``init_db()`` also targets the test file.
    * The shared :class:`chat.ws.ConnectionManager` and rate limiter are reset
      per test so websocket state cannot leak between tests.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Immediate import of ``chat`` etc. happens in test modules; ensure the project
# root is importable regardless of where pytest runs from.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# A fixed, well-known secret so tokens can be cross-decoded in assertions.
# >= 32 bytes keeps PyJWT's HMAC key-length warning quiet.
os.environ.setdefault("CHAT_SECRET_KEY", "test-secret-key-0123456789abcdef0123456789abcdef")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from chat import models  # noqa: E402,F401  (register models on Base.metadata)
from chat import auth  # noqa: E402
from chat.database import Base, get_session  # noqa: E402
from chat.main import app, manager, rate_limiter  # noqa: E402


@pytest.fixture()
def app_client(tmp_path, monkeypatch):
    """Provide a fresh app + TestClient backed by an isolated SQLite DB."""
    db_path = tmp_path / "test_chat.db"
    engine = create_engine(
        f"sqlite:///{db_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    # Make the lifespan's init_db() and any module-level calls hit the test DB.
    import chat.database as database_mod
    monkeypatch.setattr(database_mod, "ENGINE", engine)

    def override_get_session():
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

    # Reset shared in-memory app state so tests don't interfere with each other.
    manager._rooms.clear()
    rate_limiter.reset()

    app.dependency_overrides[get_session] = override_get_session
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
    manager._rooms.clear()
    rate_limiter.reset()


@pytest.fixture()
def two_users(app_client):
    """Register two users and return their (token, username) pairs + a room."""
    client = app_client
    pair_a = register(client, "alice", "password-a")
    pair_b = register(client, "bob", "password-b")
    room = client.post(
        "/api/rooms",
        json={"name": "general"},
        headers={"Authorization": f"Bearer {pair_a['access_token']}"},
    ).json()
    return client, pair_a, pair_b, room


def register(client, username, password):
    """Register a user and return ``{access_token, username}``."""
    res = client.post(
        "/api/auth/register",
        json={"username": username, "password": password},
    )
    assert res.status_code == 201, res.text
    return res.json()


def connect_ws(client, room_id, token):
    """Open a websocket, fail fast with a useful message on bad tokens."""
    return client.websocket_connect(f"/ws/rooms/{room_id}?token={token}")