"""Shared fixtures for the API gateway test-suite.

Every test builds an isolated gateway via ``gateway.main.create_app`` with:
* a fresh temporary SQLite file (no shared state between tests),
* an in-process ``httpx.MockTransport`` as the backend (an echo handler) so
  proxying exercises real HTTP semantics with zero network I/O.

``register_and_key`` is a convenience that registers + logs in + creates an API
key and returns ``(app, TestClient, tenant_id, plaintext_key)``.
"""

from __future__ import annotations

import json
from typing import Optional

import httpx
import pytest
from fastapi.testclient import TestClient

# Set the *default* DB URL to in-memory before any gateway module is imported,
# so the module-level app in gateway.main never writes a stray gateway.db here.
import os

os.environ.setdefault("GATEWAY_DATABASE_URL", "sqlite://")


def echo_handler(request: httpx.Request) -> httpx.Response:
    """Synchronous backend echo: reflect method/path/body back as JSON."""
    body = request.read()
    payload = {
        "method": request.method,
        "url": str(request.url),
        "path": request.url.path,
        "body_utf8": body.decode("utf-8", errors="replace"),
        "echo_header": request.headers.get("x-echo", None),
    }
    return httpx.Response(200, json=payload, headers={"x-backend": "echo"})


@pytest.fixture()
def backend_transport():
    return httpx.MockTransport(echo_handler)


@pytest.fixture()
def app_factory(tmp_path, backend_transport, monkeypatch):
    """Return a ``build()`` callable producing an isolated gateway app."""

    created_apps = []

    def build(
        database_url: Optional[str] = None,
        rate_limit: Optional[int] = None,
        rate_window: Optional[int] = None,
        transport=backend_transport,
    ):
        from gateway import usage
        from gateway.database import dispose
        from gateway.ratelimit import reset_limiter

        usage.reset_batcher()
        dispose()
        reset_limiter()
        url = database_url or f"sqlite:///{tmp_path / 'tw'}_{len(created_apps)}.db"
        from gateway.main import create_app

        app = create_app(
            database_url=url,
            backend_transport=transport,
            rate_limit=rate_limit,
            rate_window=rate_window if rate_window is not None else 60,
        )
        created_apps.append(app)
        return app

    yield build

    from gateway import usage as _u
    from gateway.database import dispose as _dispose
    from gateway.ratelimit import reset_limiter as _reset_limiter

    _u.reset_batcher()
    _reset_limiter()
    _dispose()


def register_login(app, client, email="tenant@example.com", password="hunter22", plan=None) -> str:
    """Register a tenant, log in, return the JWT."""
    body = {"email": email, "password": password, "name": email.split("@")[0]}
    if plan:
        body["plan"] = plan
    r = client.post("/api/auth/register", json=body)
    assert r.status_code in (200, 201), r.text
    login = client.post("/api/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    return login.json()["token"]


def create_key(client, token, name="test") -> str:
    """Create an API key; returns the plaintext ``sk_live_...``."""
    r = client.post("/api/keys", headers={"Authorization": f"Bearer {token}"}, json={"name": name})
    assert r.status_code == 200, r.text
    return r.json()["key"]


def make_echo_request(client, key, path="/v1/ping", method="GET", body=b'{"x":1}', headers=None):
    hdrs = {"X-API-Key": key}
    if headers:
        hdrs.update(headers)
    return client.request(method, path, content=body, headers=hdrs)


@pytest.fixture()
def built_app(app_factory, backend_transport):
    """A ready-to-use isolated gateway with a tenant + working API key."""
    app = app_factory()
    client = TestClient(app)
    token = register_login(app, client)
    key = create_key(client, token)
    return {"app": app, "client": client, "token": token, "key": key, "tenant_id": 1}