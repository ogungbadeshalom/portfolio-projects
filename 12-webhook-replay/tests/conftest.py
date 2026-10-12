"""Shared test fixtures for webtrap.

Everything runs in-process:
* The capture server is exercised via ``httpx.ASGITransport`` against the real
  FastAPI app (``webtrap.main.app``).
* Replay and forward *targets* are an in-process ASGI "echo" app served
  through ``httpx.ASGITransport`` — no sockets, no external services.
* The database is an in-memory SQLite URL (shared via StaticPool) so tests are
  fast and leave nothing on disk.
"""

from __future__ import annotations

import json
from typing import Dict, List, Optional

import httpx
import pytest

# --- in-process "echo" ASGI target ---------------------------------------- #
# A minimal ASGI app that echoes the request (method, headers, body) back so
# replay/forward tests can assert exactly what the target received.


async def echo_app(scope, receive, send):
    """ASGI app: echo back method, path, query, and raw body."""
    body = b""
    while True:
        message = await receive()
        if message["type"] == "http.request":
            body += message.get("body", b"")
            if not message.get("more_body"):
                break
        else:
            break
    payload = json.dumps(
        {
            "method": scope["method"],
            "path": scope["path"],
            "query": scope["query_string"].decode(),
            "body_utf8": body.decode("utf-8", errors="replace"),
            "body_len": len(body),
        }
    ).encode()
    await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"application/json")]})
    await send({"type": "http.response.body", "body": payload})


@pytest.fixture()
def echo_transport() -> httpx.ASGITransport:
    return httpx.ASGITransport(app=echo_app)


@pytest.fixture()
async def capture_client(tmp_path, monkeypatch):
    """An ASGITransport client bound to the real FastAPI app, with an
    isolated in-memory DB and clean forward state."""
    import webtrap.database as db
    import webtrap.forwarder as fwd
    import webtrap.main as main

    # Reset DB to a fresh in-memory sqlite and create tables.
    db._engine = None
    db._session_factory = None
    db.init_db("sqlite+aiosqlite:///:memory:")
    await db.create_tables()

    # Reset forward singleton so tests start with no targets / no transport.
    fwd._forwarder = None
    fwd._default_transport = None

    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://webtrap.test") as client:
        yield client


async def capture(transport, app, method: str, path: str, body: bytes = b"", headers: Optional[Dict[str, str]] = None):
    """Helper: issue one raw request against an ASGI-gated app."""
    async with httpx.AsyncClient(transport=transport, base_url="http://webtrap.test") as client:
        return await client.request(method, path, content=body, headers=headers or {})