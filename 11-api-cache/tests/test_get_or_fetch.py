"""``APICache.get_or_fetch`` — populate-on-miss behaviour."""
from __future__ import annotations

from apicache import APICache


async def test_get_or_fetch_populates_and_hits(cache: APICache) -> None:
    calls = 0

    async def fetcher(key: str, headers: dict | None = None):
        nonlocal calls
        calls += 1
        return {"key": key, "n": calls}

    first = await cache.get_or_fetch("k", fetcher)
    assert first == {"key": "k", "n": 1}
    second = await cache.get_or_fetch("k", fetcher)
    assert second == {"key": "k", "n": 1}  # cached, no second fetch
    assert calls == 1


async def test_get_or_fetch_bare_value(cache: APICache) -> None:
    async def fetcher(key: str, headers: dict | None = None):
        return 42

    assert await cache.get_or_fetch("k", fetcher) == 42
    assert await cache.get_or_fetch("k", fetcher) == 42


async def test_get_or_fetch_two_tuple_value_headers(cache: APICache) -> None:
    async def fetcher(key: str, headers: dict | None = None):
        return ({"data": True}, {"etag": '"abc"'})

    value = await cache.get_or_fetch("k", fetcher)
    assert value == {"data": True}
    assert (await cache.inspect("k")).etag == '"abc"'


async def test_get_or_fetch_tags_applied(cache: APICache) -> None:
    async def fetcher(key: str, headers: dict | None = None):
        return {"ok": True}

    await cache.get_or_fetch("k", fetcher, tags=["users", "u-{0}"])
    entry = await cache.inspect("k")
    assert "users" in entry.tags
    assert await cache.invalidate_tag("u-{0}") == 1