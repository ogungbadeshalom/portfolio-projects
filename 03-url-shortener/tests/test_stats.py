"""Tests for ``GET /api/stats/{code}`` and ``GET /api/list``."""
from __future__ import annotations

from httpx import AsyncClient


async def _create(client: AsyncClient, url: str) -> str:
    resp = await client.post("/api/shorten", json={"url": url})
    assert resp.status_code == 201
    return resp.json()["code"]


async def test_stats(client: AsyncClient) -> None:
    code = await _create(client, "https://example.com/stats")
    stats = await client.get(f"/api/stats/{code}")
    assert stats.status_code == 200
    body = stats.json()
    assert body["code"] == code
    assert body["url"] == "https://example.com/stats"
    assert body["clicks"] == 0
    assert body["created_at"]


async def test_stats_missing_404(client: AsyncClient) -> None:
    resp = await client.get("/api/stats/missing1")
    assert resp.status_code == 404


async def test_list_pagination(client: AsyncClient) -> None:
    for i in range(5):
        await _create(client, f"https://example.com/{i}")

    first = await client.get("/api/list?page=1&page_size=2")
    second = await client.get("/api/list?page=2&page_size=2")
    third = await client.get("/api/list?page=3&page_size=2")

    assert first.status_code == 200
    assert first.json()["total"] == 5
    assert len(first.json()["items"]) == 2
    assert len(second.json()["items"]) == 2
    assert len(third.json()["items"]) == 1

    all_codes = [
        *[i["code"] for i in first.json()["items"]],
        *[i["code"] for i in second.json()["items"]],
        *[i["code"] for i in third.json()["items"]],
    ]
    assert len(set(all_codes)) == 5  # no duplicates across pages


async def test_list_reflects_clicks(client: AsyncClient) -> None:
    code = await _create(client, "https://example.com/clicked")
    await client.get(f"/{code}", follow_redirects=False)
    listing = await client.get("/api/list")
    item = next(i for i in listing.json()["items"] if i["code"] == code)
    assert item["clicks"] == 1


async def test_empty_list(client: AsyncClient) -> None:
    resp = await client.get("/api/list")
    assert resp.status_code == 200
    assert resp.json()["items"] == []
    assert resp.json()["total"] == 0