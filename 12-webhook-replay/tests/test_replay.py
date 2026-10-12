"""Tests for replaying captured requests against an in-process echo target.

The replay *API endpoint* lives on the FastAPI app (driven through
``capture_client``), while the outbound replay hop goes to the echo ASGI app
via an injected ``httpx.ASGITransport``. FastAPI JSON-encodes ``bytes``
bodies as base64, so the tests decode them before asserting.
"""

from __future__ import annotations

import json

import httpx
import pytest

import webtrap.replay as rep
from tests.conftest import echo_app


@pytest.fixture()
def replay_transport():
    """Make the replay endpoint's outbound hop go to the in-process echo app."""
    transport = httpx.ASGITransport(app=echo_app)
    rep.set_replay_transport(transport)
    yield transport
    rep.set_replay_transport(None)


@pytest.mark.asyncio
async def test_replay_preserves_method_and_body(capture_client, replay_transport):
    pid = (
        await capture_client.post("/incoming/r", content=b"payload-123", headers={"x-token": "abc"})
    ).json()["id"]

    resp = await capture_client.post(
        "/api/requests/%d/replay" % pid, json={"target": "http://target.test", "delay_ms": 0}
    )
    assert resp.status_code == 200
    result = resp.json()
    assert result["status_code"] == 200
    echoed = json.loads(result["body"])
    assert echoed["method"] == "POST"
    assert echoed["body_utf8"] == "payload-123"


@pytest.mark.asyncio
async def test_replay_preserves_query_string(capture_client, replay_transport):
    pid = (await capture_client.get("/incoming/q?a=1&a=2&b=zz")).json()["id"]
    resp = await capture_client.post("/api/requests/%d/replay" % pid, json={"target": "http://t"})
    echoed = json.loads(resp.json()["body"])
    assert "a=1" in echoed["query"]
    assert "a=2" in echoed["query"]
    assert "b=zz" in echoed["query"]


@pytest.mark.asyncio
async def test_replay_unknown_id_returns_404(capture_client, replay_transport):
    resp = await capture_client.post("/api/requests/99999/replay", json={"target": "http://t"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_replay_request_function_preserves_method(capture_client):
    from webtrap.database import get_session_factory

    pid = (await capture_client.delete("/incoming/del")).json()["id"]
    transport = httpx.ASGITransport(app=echo_app)
    async with get_session_factory()() as session:
        result = await rep.replay_request(session, pid, target="http://t", transport=transport)
    assert result is not None
    echoed = json.loads(result.body)
    assert echoed["method"] == "DELETE"
    assert result.status_code == 200


@pytest.mark.asyncio
async def test_replay_apply_delay_is_respected(capture_client, replay_transport):
    import time

    pid = (await capture_client.post("/incoming/slow", content=b"x")).json()["id"]
    start = time.monotonic()
    await capture_client.post(
        "/api/requests/%d/replay" % pid, json={"target": "http://t", "delay_ms": 150}
    )
    elapsed = time.monotonic() - start
    assert elapsed >= 0.12  # the delay was actually applied before sending