"""The ``@cached`` decorator: caching, TTL, template keys, and tags."""
from __future__ import annotations

from unittest import mock

from apicache import APICache


async def test_decorator_caches_second_call(cache: APICache) -> None:
    calls: list[int] = []

    @cache.cached(ttl=600)
    async def fetch(x: int) -> dict:
        calls.append(x)
        return {"value": x * 2}

    assert await fetch(5) == {"value": 10}
    assert await fetch(5) == {"value": 10}
    assert calls == [5]  # function ran only once


async def test_decorator_distinguishes_arguments(cache: APICache) -> None:
    calls: list[int] = []

    @cache.cached(ttl=600)
    async def fetch(x: int) -> int:
        calls.append(x)
        return x * 2

    assert await fetch(2) == 4
    assert await fetch(3) == 6
    assert calls == [2, 3]  # different arg → separate cache entry


async def test_decorator_ttl_expiry(cache: APICache) -> None:
    calls = 0
    before = 50_000.0

    @cache.cached(ttl=10)
    async def fetch(x: int) -> int:
        nonlocal calls
        calls += 1
        return x

    with mock.patch("apicache.models.time.time", return_value=before):
        assert await fetch(1) == 1
        assert await fetch(1) == 1  # cached
        assert calls == 1

    with mock.patch("apicache.models.time.time", return_value=before + 11):
        assert await fetch(1) == 1  # expired → fetched again
        assert calls == 2


async def test_decorator_tag_invalidation(cache: APICache) -> None:
    calls = 0

    @cache.cached(ttl=600, tags=["user-{user_id}"])
    async def fetch_user(user_id: int) -> dict:
        nonlocal calls
        calls += 1
        return {"id": user_id, "calls": calls}

    assert (await fetch_user(42))["calls"] == 1
    assert (await fetch_user(42))["calls"] == 1  # cached

    removed = await cache.invalidate_tag("user-42")
    assert removed >= 1

    assert (await fetch_user(42))["calls"] == 2  # refetched after invalidation


async def test_decorator_tag_invalidation_only_affects_match(cache: APICache) -> None:
    @cache.cached(ttl=600, tags=["user-{user_id}"])
    async def fetch(user_id: int) -> list[int]:
        return [user_id]

    await fetch(1)
    await fetch(2)

    # Invalidate only user-1; user-2 must remain cached.
    removed = await cache.invalidate_tag("user-1")
    assert removed == 1
    keys = await cache.list_keys()
    assert len(keys) == 1


async def test_bare_cached_function_decorator(cache: APICache) -> None:
    from apicache import cached as bare_cached

    calls = 0

    @bare_cached(cache, ttl=600)
    async def fetch() -> str:
        nonlocal calls
        calls += 1
        return "value"

    assert await fetch() == "value"
    assert await fetch() == "value"
    assert calls == 1