"""Tests for ``POST /api/shorten``."""
from __future__ import annotations

import pytest
from httpx import AsyncClient


async def test_shorten_creates_code(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/shorten", json={"url": "https://github.com/yt-dlp/yt-dlp"}
    )
    assert resp.status_code == 201
    data = resp.json()
    assert len(data["code"]) == 7
    assert data["code"].isalnum()
    assert data["short_url"] == f"/{data['code']}"
    assert data["target_url"] == "https://github.com/yt-dlp/yt-dlp"
    assert data["clicks"] == 0


async def test_shorten_returns_422_for_bad_url(client: AsyncClient) -> None:
    resp = await client.post("/api/shorten", json={"url": "not-a-url"})
    assert resp.status_code == 422


async def test_shorten_rejects_localhost_ssrf(client: AsyncClient) -> None:
    for target in ("http://localhost:8080/x", "http://127.0.0.1/x", "http://[::1]/x"):
        resp = await client.post("/api/shorten", json={"url": target})
        assert resp.status_code == 422, target


async def test_shorten_custom_alias(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/shorten", json={"url": "https://example.com", "code": "my-link"}
    )
    assert resp.status_code == 201
    assert resp.json()["code"] == "my-link"
    assert resp.json()["short_url"] == "/my-link"


async def test_shorten_custom_alias_duplicate_conflict(client: AsyncClient) -> None:
    payload = {"url": "https://example.com", "code": "my-link"}
    assert (await client.post("/api/shorten", json=payload)).status_code == 201
    dup = await client.post("/api/shorten", json=payload)
    assert dup.status_code == 409


async def test_generated_codes_are_unique(client: AsyncClient) -> None:
    seen = set()
    for i in range(20):
        resp = await client.post("/api/shorten", json={"url": f"https://example.com/{i}"})
        assert resp.status_code == 201
        code = resp.json()["code"]
        assert code not in seen
        seen.add(code)
    assert len(seen) == 20


async def test_shorten_rejects_oversized_url(client: AsyncClient) -> None:
    long = "https://example.com/" + ("a" * 2100)
    resp = await client.post("/api/shorten", json={"url": long})
    assert resp.status_code == 422