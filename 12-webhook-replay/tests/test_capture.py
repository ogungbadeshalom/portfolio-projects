"""Tests for the capture endpoint and the store/inspect API.

These run the real FastAPI app over ``httpx.ASGITransport`` against an
in-memory SQLite DB. Nothing touches the network.
"""

from __future__ import annotations

import httpx
import pytest

import webtrap.main as main
from tests.conftest import capture


def _b64(value) -> bytes:
    """Decode a FastAPI JSON base64-encoded bytes field."""
    import base64

    return base64.b64decode(value)


@pytest.mark.asyncio
async def test_capture_post_is_stored(capture_client):
    resp = await capture_client.post(
        "/incoming/test-token", content=b'{"event":"ping"}', headers={"content-type": "application/json"}
    )
    assert resp.status_code in (200, 202)
    payload = resp.json()
    assert payload["token"] == "test-token"
    assert payload["id"] >= 1

    # The request is persisted with its body and source info.
    got = await capture_client.get(f"/api/requests/{payload['id']}")
    assert got.status_code == 200
    data = got.json()
    assert data["method"] == "POST"
    assert data["path"] == "/incoming/test-token"
    assert data["body"] is not None
    # FastAPI JSON-encodes ASCII bytes as a UTF-8 string (jsonable_encoder).
    assert '"event":"ping"' in data["body"]


@pytest.mark.asyncio
async def test_capture_any_method_and_query(capture_client):
    resp = await capture_client.put("/incoming/t2?a=1&a=2&b=hello", content=b"raw-body-bytes")
    pid = resp.json()["id"]
    data = (await capture_client.get(f"/api/requests/{pid}")).json()
    assert data["method"] == "PUT"
    # Multi-value query preserved.
    assert data["query"] == {"a": ["1", "2"], "b": ["hello"]}
    assert data["body"] == "raw-body-bytes"


@pytest.mark.asyncio
async def test_capture_get_with_empty_body(capture_client):
    resp = await capture_client.get("/incoming/gettrap?x=1")
    pid = resp.json()["id"]
    data = (await capture_client.get(f"/api/requests/{pid}")).json()
    assert data["method"] == "GET"
    assert data["body"] is None


@pytest.mark.asyncio
async def test_headers_preserved_multivalue(capture_client):
    # Send duplicate headers as a raw list so httpx doesn't collapse them.
    resp = await capture_client.post(
        "/incoming/hdrs", content=b"x", headers=[(b"accept", b"application/json"), (b"accept", b"text/plain"), (b"x-custom", b"v1")]
    )
    pid = resp.json()["id"]
    data = (await capture_client.get(f"/api/requests/{pid}")).json()
    assert data["headers"]["accept"] == ["application/json", "text/plain"]
    assert data["headers"]["x-custom"] == ["v1"]


@pytest.mark.asyncio
async def test_list_and_delete_api(capture_client):
    await capture_client.post("/incoming/a", content=b"1")
    await capture_client.post("/incoming/b", content=b"2")
    listing = await capture_client.get("/api/requests")
    assert listing.status_code == 200
    ids = [r["id"] for r in listing.json()]
    assert len(ids) >= 2

    # Delete the oldest and confirm it is gone.
    target = ids[0]
    result = (await capture_client.delete(f"/api/requests/{target}")).json()
    assert result["deleted"] == target
    gone = await capture_client.get(f"/api/requests/{target}")
    assert gone.status_code == 404


@pytest.mark.asyncio
async def test_web_listing_page_renders(capture_client):
    await capture_client.post("/incoming/webtrap", content=b'{"a":1}')
    page = await capture_client.get("/")
    assert page.status_code == 200
    assert b"Captured requests" in page.content


@pytest.mark.asyncio
async def test_inspect_page_and_curl(capture_client):
    resp = await capture_client.post("/incoming/tok", content=b'{"k":"v"}', headers={"x-thing": "yes"})
    pid = resp.json()["id"]
    page = await capture_client.get(f"/request/{pid}")
    assert page.status_code == 200
    assert b"x-thing" in page.content
    assert b"curl" in page.content