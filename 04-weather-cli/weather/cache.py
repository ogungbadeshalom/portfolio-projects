"""Tiny JSON-on-disk cache with TTL support.

Values are the serialised :class:`~weather.models.Forecast` payloads.
Each cache entry is a small JSON file under :func:`~weather.config.cache_dir`
named from the cache key, e.g. ``~/.cache/weather/lagos:3:metric.json``.

Storing one file per key (rather than one giant JSON blob) keeps the
implementation simple, avoids load/modify/save races on the whole store, and
makes wiping a single stale key trivial.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

from .config import TTL_CURRENT_SECONDS, TTL_FORECAST_SECONDS, cache_dir

# Bundle version so we never confuse the serialiser if the model changes.
_SCHEMA = 1


class WeatherCache:
    """A filesystem-backed, TTL-aware cache keyed by request strings.

    Example
    -------
    >>> cache = WeatherCache()
    >>> forecast = cache.get("lagos:3:metric", ttl_seconds=3600)
    """

    def __init__(self, directory: Optional[Path] = None) -> None:
        self.directory = Path(directory) if directory else cache_dir()
        self.directory.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ #
    # Public API                                                          #
    # ------------------------------------------------------------------ #

    def get(self, key: str, *, ttl_seconds: int) -> Optional[dict]:
        """Return the cached payload for ``key`` if it is still fresh.

        Returns ``None`` when the key is absent, expired, or unreadable.
        Expired files are removed so the next lookup starts clean.
        """
        entry = self._read(key)
        if entry is None:
            return None
        cached_at = entry.get("cached_at", 0)
        if time.time() - cached_at > ttl_seconds:
            self._remove(key)
            return None
        return entry.get("data")

    def get_stale(self, key: str) -> Optional[dict]:
        """Return the cached payload for ``key`` ignoring TTL.

        Used as a graceful fallback when the network is down: a stale answer
        is better than no answer. Returns ``None`` for a missing/invalid key.
        """
        entry = self._read(key)
        if entry is None:
            return None
        return entry.get("data")

    def set(self, key: str, data: dict, *, ttl_seconds: int) -> None:
        """Store ``data`` under ``key`` with the given TTL.

        The TTL is not stored - it is supplied again at read time so a single
        entry can serve callers with different freshness requirements. This
        mirrors how the CLI treats current (30 min) vs forecast (1 h) data.
        """
        if ttl_seconds <= 0:
            return
        path = self._path(key)
        entry = {
            "schema": _SCHEMA,
            "cached_at": time.time(),
            "data": data,
        }
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(entry), encoding="utf-8")
        tmp.replace(path)

    def clear(self, key: Optional[str] = None) -> int:
        """Remove one entry (or all entries when ``key`` is ``None``).

        Returns the number of files removed.
        """
        if key is None:
            removed = 0
            for child in self.directory.glob("*.json"):
                child.unlink(missing_ok=True)
                removed += 1
            return removed
        return 1 if self._remove(key) else 0

    # ------------------------------------------------------------------ #
    # Helpers                                                             #
    # ------------------------------------------------------------------ #

    def _path(self, key: str) -> Path:
        # The key may contain characters (``:``) that are fine in filenames on
        # modern filesystems, but we sanitise anything unusual for safety.
        safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in key)
        return self.directory / f"{safe}.json"

    def _read(self, key: str) -> Optional[dict]:
        """Read a raw cache *entry* (with ``cached_at``) or ``None``."""
        path = self._path(key)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self._remove(key)
            return None

    def _remove(self, key: str) -> bool:
        path = self._path(key)
        if path.exists():
            path.unlink()
            return True
        return False


# Module-level helper for the "current" vs "forecast" TTL choice.
def ttl_for(kind: str) -> int:
    """Return the TTL seconds for a data kind (``current`` or ``forecast``)."""
    if kind == "forecast":
        return TTL_FORECAST_SECONDS
    return TTL_CURRENT_SECONDS