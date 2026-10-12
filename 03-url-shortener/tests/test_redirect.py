"""Tests for ``GET /{code}`` redirects and click counting."""
from __future__ import annotations

from httpx import AsyncClient


async def _create(client: AsyncClient, url: str = "https://example.com/page") -> str:
    resp = await client.post("/api/shorten", json={"url": url})
    assert resp.status_code == 201
    return resp.json()["code"]


async def test_redirect_302(client: AsyncClient) -> None:
    code = await _create(client)
    resp = await client.get(f"/{code}", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "https://example.com/page"


async def test_redirect_increments_click_count(client: AsyncClient) -> None:
    code = await _create(client)
    await client.get(f"/{code}", follow_redirects=False)
    await client.get(f"/{code}", follow_redirects=False)
    stats = await client.get(f"/api/stats/{code}")
    assert stats.status_code == 200
    assert stats.json()["clicks"] == 2


async def test_redirect_missing_code_404(client: AsyncClient) -> None:
    resp = await client.get("/nope123", follow_redirects=False)
    assert resp.status_code == 404


async def test_redirect_after_delete_not_applicable(client: AsyncClient) -> None:
    # No DELETE endpoint in the MVP; ensure unknown codes stay 404.
    assert (await client.get("/zzzzzz", follow_redirects=False)).status_code == 404