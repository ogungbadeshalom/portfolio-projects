"""The :class:`APICache` orchestration layer.

``APICache`` binds together the SQLite storage, hit/miss stats, TTL logic,
tag invalidation, and the ``cached`` decorator behind a single async object:

    cache = APICache("cache.db", default_ttl=300)
    await cache.open()

    await cache.set("greeting", {"hello": "world"}, ttl=60)
    value = await cache.get("greeting")

    @cache.cached(ttl=600, tags=["user-{user_id}"])
    async def fetch_user(user_id: int): ...

    await cache.invalidate_tag("user-42")
    await cache.close()
"""
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Optional, Sequence

from apicache.config import DEFAULT_CLEANUP_INTERVAL, validate_ttl
from apicache.decorator import CachedFunction
from apicache.etag import build_if_none_match, extract_etag, is_not_modified
from apicache.models import CacheEntry, CacheStats, now
from apicache.stats import StatsTracker
from apicache.storage import SQLiteStorage

Fetcher = Callable[[str], Awaitable[Any]]


class APICache:
    """A generic, asyncio-first JSON cache with TTL, tags, ETag, and stats.

    Args:
        db_path: SQLite database path (``":memory:"`` for an in-process store).
        default_ttl: TTL (seconds) applied when a call omits ``ttl``.
        cleanup_interval: Seconds between background expired-row purges.
        start_cleanup: Whether to launch the background cleanup task on open.
    """

    def __init__(
        self,
        db_path: str = "apicache.db",
        *,
        default_ttl: Optional[float] = None,
        cleanup_interval: float = DEFAULT_CLEANUP_INTERVAL,
        start_cleanup: bool = False,
    ) -> None:
        self.default_ttl = validate_ttl(default_ttl)
        self.cleanup_interval = cleanup_interval
        self.storage = SQLiteStorage(db_path)
        self._stats = StatsTracker()
        self._cleanup_task: Optional[asyncio.Task] = None
        self._start_cleanup = start_cleanup

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    async def open(self) -> "APICache":
        """Open storage and (optionally) start the background cleanup task."""
        await self.storage.open()
        if self._start_cleanup:
            self._cleanup_task = asyncio.create_task(self._run_cleanup())
            self._cleanup_task.add_done_callback(self._guard_cleanup)
        return self

    async def close(self) -> None:
        """Cancel the background task (if any) and close storage."""
        if self._cleanup_task is not None:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._cleanup_task = None
        await self.storage.close()

    async def __aenter__(self) -> "APICache":
        return await self.open()

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    def _guard_cleanup(self, task: asyncio.Task) -> None:
        if not task.cancelled() and task.exception():
            # A failing background cleanup should not kill the event loop.
            task.exception()  # consume so pytest doesn't complain

    async def _run_cleanup(self) -> None:
        while True:
            await asyncio.sleep(self.cleanup_interval)
            try:
                await self.storage.cleanup_expired()
            except Exception:  # noqa: BLE001 - keep the loop alive
                continue

    # ------------------------------------------------------------------
    # Core get/set
    # ------------------------------------------------------------------
    async def get(self, key: str) -> Any:
        """Return the fresh value for ``key``, or ``None`` on a miss/expiry.

        Expired entries are treated as misses but left in place for the
        periodic cleanup; this is the "lazy expiry" behaviour.
        """
        entry = await self.storage.get(key)
        if entry is None or entry.is_expired(now()):
            self._stats.record_miss()
            return None
        self._stats.record_hit()
        return entry.value

    async def get_entry(self, key: str) -> CacheEntry | None:
        """Return the stored entry (even if expired) for inspection/ETag."""
        return await self.storage.get(key)

    async def set(
        self,
        key: str,
        value: Any,
        *,
        ttl: Optional[float] = None,
        tags: Sequence[str] = (),
        etag: Optional[str] = None,
    ) -> None:
        """Store ``value`` under ``key`` with an optional TTL, tags, and ETag."""
        ttl_seconds = self.default_ttl if ttl is None else validate_ttl(ttl)
        expires_at = None if ttl_seconds is None else now() + ttl_seconds
        entry = CacheEntry(
            key=key,
            value=value,
            expires_at=expires_at,
            tags=list(tags or ()),
            etag=etag,
            created_at=now(),
        )
        await self.storage.set(entry)

    # ------------------------------------------------------------------
    # get_or_fetch
    # ------------------------------------------------------------------
    async def get_or_fetch(
        self,
        key: str,
        fetcher: Fetcher,
        *,
        ttl: Optional[float] = None,
        tags: Sequence[str] = (),
        use_etag: bool = False,
    ) -> Any:
        """Return the cached value for ``key`` or populate it via ``fetcher``.

        On a miss, ``fetcher(key)`` is awaited, its return value is treated as
        a ``(value, headers|etag)`` pair (or a bare value), and the result is
        stored under the key.

        ``use_etag=True`` sends ``If-None-Match`` when a stored ETag exists and
        refreshes the TTL on a ``304`` without overwriting the body.
        """
        entry = await self.storage.get(key)
        if entry is not None and not entry.is_expired(now()):
            self._stats.record_hit()
            return entry.value

        self._stats.record_miss()

        send_headers: dict[str, str] = {}
        if use_etag and entry is not None and entry.etag:
            send_headers = build_if_none_match(entry.etag)

        result = await fetcher(key, send_headers) if use_etag else await fetcher(key)

        # Normalise the fetcher result to (value, etag).
        value, etag = self._coerce_result(result, entry, use_etag, send_headers)

        ttl_seconds = self.default_ttl if ttl is None else validate_ttl(ttl)
        expires_at = None if ttl_seconds is None else now() + ttl_seconds
        new_entry = CacheEntry(
            key=key,
            value=value,
            expires_at=expires_at,
            tags=list(tags or ()),
            etag=etag,
            created_at=now(),
        )
        await self.storage.set(new_entry)
        return value

    def _coerce_result(
        self,
        result: Any,
        previous: CacheEntry | None,
        use_etag: bool,
        sent_headers: dict[str, str],
    ) -> tuple[Any, Optional[str]]:
        """Interpret a fetcher result as ``(value, etag)``.

        Supports three shapes: a bare value, a 2-tuple ``(value, headers)``
        (dict or response-like), or a ``304``-style marker. When the origin
        returns 304 and we had a stored ETag, the stored value is reused and
        its expiry refreshed.
        """
        # Shape (status, value, headers) or response-like objects.
        from apicache.etag import extract_etag as _ex

        if isinstance(result, tuple) and len(result) == 2:
            value, headers = result
            etag = _ex(headers) if headers is not None else None
            return value, etag
        if isinstance(result, tuple) and len(result) == 3:
            status, value, headers = result
            if use_etag and is_not_modified(status) and previous is not None and "If-None-Match" in sent_headers:
                return previous.value, previous.etag
            etag = _ex(headers) if headers is not None else None
            return value, etag

        # Response-like object with .status_code and .json()/.text.
        if hasattr(result, "status_code"):
            if use_etag and is_not_modified(result.status_code) and previous is not None and "If-None-Match" in sent_headers:
                return previous.value, previous.etag
            if hasattr(result, "json"):
                value = result.json()
            else:
                value = getattr(result, "text", None)
            return value, extract_etag(result.headers)

        return result, None

    # ------------------------------------------------------------------
    # Cache maintenance
    # ------------------------------------------------------------------
    async def invalidate_tag(self, tag: str) -> int:
        """Delete every entry tagged with ``tag``. Returns how many were removed."""
        return await self.storage.delete_by_tag(tag)

    async def clear(self) -> int:
        """Clear the whole cache. Returns the number of rows removed."""
        return await self.storage.clear()

    async def cleanup_expired(self) -> int:
        """Delete expired rows now (regardless of the background task)."""
        return await self.storage.cleanup_expired()

    async def list_keys(self) -> list[str]:
        """Return every key in the cache."""
        return await self.storage.list_keys()

    async def inspect(self, key: str) -> CacheEntry | None:
        """Return a stored entry (including expired ones) for inspection."""
        return await self.storage.get(key)

    async def stats(self) -> CacheStats:
        """Return aggregate hit/miss/entry statistics."""
        total = await self.storage.count()
        expired = await self.storage.count_expired()
        return self._stats.snapshot(total, expired)

    def reset_stats(self) -> None:
        """Reset the in-memory hit/miss counters."""
        self._stats.reset()

    # ------------------------------------------------------------------
    # Decorator sugar
    # ------------------------------------------------------------------
    def cached(
        self,
        ttl: Optional[float] = None,
        tags: Sequence[str] = (),
        key_prefix: str | None = None,
    ) -> Callable[[Any], "CachedFunction"]:
        """Decorate an async function to be served through this cache.

        Usage::

            @cache.cached(ttl=600, tags=["user-{user_id}"])
            async def fetch_user(user_id: int): ...
        """
        from apicache.decorator import cached as _cached

        return _cached(self, ttl=ttl, tags=tags, key_prefix=key_prefix)