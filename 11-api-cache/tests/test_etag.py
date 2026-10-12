"""ETag support: store an ETag, send If-None-Match, handle 304 refresh."""
from __future__ import annotations

from apicache import APICache


class FakeHeaders(dict):
    """Minimal response-like headers for ETag extraction."""


class FakeResponse:
    """A stand-in for an httpx.Response exposing the bits we consume."""

    def __init__(self, status_code: int, json_value: object, etag: str | None = None) -> None:
        self.status_code = status_code
        self._json = json_value
        self.headers = FakeHeaders({"etag": etag} if etag else {})

    def json(self):
        return self._json


async def test_store_and_reuse_etag(cache) -> None:
    fetched: list[int] = []

    async def fetcher(key: str, headers: dict | None = None) -> object:
        fetched.append(len(fetched))
        # Pretend the origin returns the same body and an ETag each time.
        return FakeResponse(200, {"data": "hello"}, etag='"abc"')

    first = await cache.get_or_fetch("k", fetcher, use_etag=True)
    assert first == {"data": "hello"}

    # The ETag must be stored so a later conditional fetch can send it.
    entry = await cache.inspect("k")
    assert entry.etag == '"abc"'

    cached = await cache.get_or_fetch("k", fetcher, use_etag=True)
    assert cached == {"data": "hello"}
    assert len(fetched) == 1  # only one origin fetch occurred


async def test_304_refreshes_without_refetch(cache, monkeypatch) -> None:
    import apicache.models as models

    fetched = 0
    now_value = [1000.0]
    monkeypatch.setattr(models.time, "time", lambda: now_value[0])

    async def fetcher(key: str, headers: dict | None = None):
        nonlocal fetched
        fetched += 1
        assert headers and headers.get("If-None-Match") == '"etag-1"'
        return FakeResponse(304, None, etag='"etag-1"')

    # Store an entry that is already expired but carries a stored ETag.
    await cache.set("k", {"v": 2}, ttl=0, etag='"etag-1"')

    # ttl=0 ⇒ expires_at == now, so the entry is expired and the fetcher is
    # called with If-None-Match; the 304 keeps the cached body.
    result = await cache.get_or_fetch("k", fetcher, use_etag=True)
    assert result == {"v": 2}
    assert fetched == 1


async def test_etag_absent_when_not_requested(cache) -> None:
    async def fetcher(key: str, headers: dict | None = None):
        # When use_etag=False we must not pass If-None-Match headers.
        assert headers is None
        return {"plain": True}

    await cache.get_or_fetch("k", fetcher, use_etag=False)


async def test_cache_serves_fresh_entry(cache) -> None:
    fetched = 0

    async def fetcher(key: str, headers: dict | None = None):
        nonlocal fetched
        fetched += 1
        return {"v": fetched}

    # Warm the cache explicitly, then a get_or_fetch must not call origin.
    await cache.set("k", {"v": 99})
    result = await cache.get_or_fetch("k", fetcher)
    assert result == {"v": 99}
    assert fetched == 0