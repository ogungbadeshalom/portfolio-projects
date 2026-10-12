"""apicache — a generic JSON API → SQLite cache with TTL, tags, ETag, and stats.

Quick start::

    from apicache import APICache

    cache = APICache("cache.db")
    await cache.open()

    await cache.set("key", {"data": "value"}, ttl=300)
    result = await cache.get("key")

    @cache.cached(ttl=600, tags=["user-{user_id}"])
    async def fetch_user(user_id: int): ...

    await cache.invalidate_tag("user-42")
    await cache.close()

Exports:

* :class:`apicache.APICache` — the main entry point.
* :func:`apicache.cached` — bare decorator for an explicit cache instance.
* :class:`apicache.models.CacheEntry` / :class:`apicache.models.CacheStats`.
"""
from __future__ import annotations

from apicache.core import APICache
from apicache.decorator import CachedFunction, cached
from apicache.models import CacheEntry, CacheStats
from apicache.config import DEFAULT_TTL

__version__ = "0.1.0"

__all__ = [
    "APICache",
    "CachedFunction",
    "CacheEntry",
    "CacheStats",
    "cached",
    "DEFAULT_TTL",
]