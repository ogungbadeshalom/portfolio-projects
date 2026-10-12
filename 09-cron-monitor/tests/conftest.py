"""Shared fixtures: isolated in-memory database per test + TestClient."""

from __future__ import annotations

import os
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

os.environ["CRONMON_DB"] = ":memory:"

import cronmon.database as dbmod  # noqa: E402
import cronmon.main as mainmod  # noqa: E402
from cronmon import auth  # noqa: E402


@pytest.fixture()
def db(tmp_path) -> Generator[Session, None, None]:
    """A session bound to a fresh in-memory store, no demo seed."""
    session = dbmod.init_db(":memory:", seed=False)
    yield session
    session.close()


@pytest.fixture()
def client(tmp_path) -> Generator[TestClient, None, None]:
    """TestClient for the fully-wired app (no background scheduler)."""
    app = mainmod.create_app(enable_scheduler=False)
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def api_key() -> str:
    """A valid key the run-mutation endpoints will accept."""
    return auth.load_or_create_key()


@pytest.fixture(autouse=True)
def _clean_engine():
    """Rebuild global engine before each test so state never leaks across tests."""
    os.environ["CRONMON_DB"] = ":memory:"
    dbmod.engine = dbmod.make_engine(":memory:")
    dbmod.SessionLocal.configure(bind=dbmod.engine)
    yield


@pytest.fixture()
def primed_webhook(tmp_path):
    """A live local HTTP server (stdlib) that captures POSTed JSON payloads.

    Returns a dict: ``url`` to POST to and ``received`` list of parsed bodies.
    """
    import json
    import socket
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    received: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            received.append(json.loads(body or b"{}"))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *args):  # silence
            pass

    # Bind an ephemeral port, then grab the actual port.
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    server = HTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}/hook"
    try:
        yield {"url": url, "received": received}
    finally:
        server.shutdown()
        thread.join(timeout=2)