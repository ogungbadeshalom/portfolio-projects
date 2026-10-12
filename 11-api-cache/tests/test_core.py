"""Core APICache behaviour: set/get, TTL, stats, and cleanup."""
from __future__ import annotations

from unittest import mock

from apicache import APICache, CacheStats


async def test_set_get_roundtrip(cache: APICache) -> None:
    await cache.set("greeting", {"hello": "world"})
    value = await cache.get("greeting")
    assert value == {"hello": "world"}


async def test_get_missing_is_none(cache: APICache) -> None:
    assert await cache.get("nope") is None


async def test_set_overwrites(cache: APICache) -> None:
    await cache.set("k", 1)
    await cache.set("k", 2)
    assert await cache.get("k") == 2


async def test_ttl_expiration(cache: APICache) -> None:
    before = 1_000_000.0
    with mock.patch("apicache.models.time.time", return_value=before):
        await cache.set("temp", "value", ttl=10)
        assert await cache.get("temp") == "value"

    # 11s later the entry is expired → treated as a miss.
    with mock.patch("apicache.models.time.time", return_value=before + 11):
        assert await cache.get("temp") is None


async def test_no_ttl_never_expires(cache: APICache) -> None:
    await cache.set("sticky", "v", ttl=None)
    with mock.patch("apicache.models.time.time", return_value=1e12):
        assert await cache.get("sticky") == "v"


async def test_stats_hit_miss(cache: APICache) -> None:
    await cache.set("a", 1)
    assert await cache.get("a") == 1  # hit
    assert await cache.get("a") == 1  # hit
    await cache.get("missing")  # miss

    snap: CacheStats = await cache.stats()
    assert snap.hits == 2
    assert snap.misses == 1
    assert snap.total_entries == 1
    assert snap.total_lookups == 3
    assert snap.hit_rate == 2 / 3


async def test_cleanup_expired(cache: APICache) -> None:
    before = 1000.0
    with mock.patch("apicache.models.time.time", return_value=before):
        await cache.set("a", 1, ttl=5)
        await cache.set("b", 2, ttl=None)

    with mock.patch("apicache.models.time.time", return_value=before + 10):
        removed = await cache.cleanup_expired()
        assert removed >= 1
        keys = await cache.list_keys()
        assert "b" in keys
        assert "a" not in keys


async def test_list_keys_and_clear(cache: APICache) -> None:
    await cache.set("x", 1)
    await cache.set("y", 2)
    assert sorted(await cache.list_keys()) == ["x", "y"]
    cleared = await cache.clear()
    assert cleared == 2
    assert await cache.list_keys() == []


async def test_inspect_returns_entry(cache: APICache) -> None:
    await cache.set("k", {"n": 5}, ttl=30, tags=["t1"])
    entry = await cache.inspect("k")
    assert entry is not None
    assert entry.value == {"n": 5}
    assert entry.tags == ["t1"]
    assert await cache.inspect("absent") is None