"""Tag-based invalidation and multi-tag semantics."""
from __future__ import annotations

from apicache import APICache


async def test_multiple_tags_per_entry(cache: APICache) -> None:
    await cache.set("a", 1, tags=["users", "admin"])
    entry = await cache.inspect("a")
    assert sorted(entry.tags) == ["admin", "users"]


async def test_invalidate_any_tag_hits_entry(cache: APICache) -> None:
    await cache.set("a", 1, tags=["users", "admins"])
    assert await cache.invalidate_tag("admins") == 1
    assert await cache.get("a") is None


async def test_invalidate_tag_no_match_removes_zero(cache: APICache) -> None:
    await cache.set("a", 1, tags=["users"])
    assert await cache.invalidate_tag("projects") == 0
    assert await cache.get("a") == 1


async def test_invalidate_tag_exact_not_substring(cache: APICache) -> None:
    await cache.set("u1", "x", tags=["user-1"])
    await cache.set("u12", "y", tags=["user-12"])
    # Invalidating user-1 must NOT remove user-12.
    assert await cache.invalidate_tag("user-1") == 1
    assert await cache.get("u12") == "y"
    assert await cache.get("u1") is None