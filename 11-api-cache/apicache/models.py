"""Pydantic models for cache entries and statistics.

All data stored in the SQLite backend is validated and serialized through
these models so that every row read from disk is guaranteed to be a
well-formed :class:`CacheEntry`.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

#: Row delimiter used to collapse the list of tags onto a single TEXT column.
TAG_DELIMITER = "\x1f"


def now() -> float:
    """Return the current monotonic-independent epoch time in seconds."""
    return time.time()


class CacheEntry(BaseModel):
    """A single cache entry as persisted in SQLite.

    Attributes:
        key: Unique cache key (always a string).
        value: JSON-serializable payload (JSON object, list, scalar).
        expires_at: UNIX epoch seconds at which the entry becomes stale.
        tags: List of string tags used for group invalidation.
        etag: Optional HTTP ``ETag`` stored from the origin response.
        created_at: UNIX epoch seconds when the entry was written.
    """

    model_config = ConfigDict(extra="forbid")

    key: str
    value: Any
    expires_at: Optional[float] = None
    tags: List[str] = Field(default_factory=list)
    etag: Optional[str] = None
    created_at: float = Field(default_factory=now)

    # ------------------------------------------------------------------
    # Serialization helpers used by the storage backend
    # ------------------------------------------------------------------
    def value_bytes(self) -> bytes:
        """Serialize ``value`` to UTF-8 JSON bytes for the ``value_json`` column."""
        return json.dumps(self.value, ensure_ascii=False).encode("utf-8")

    def tags_delimited(self) -> str:
        """Collapse ``tags`` into a single delimited string for storage."""
        return TAG_DELIMITER.join(self.tags)

    def is_expired(self, at: Optional[float] = None) -> bool:
        """Whether the entry has expired at the given instant (default now)."""
        exp = self.expires_at
        if exp is None:
            return False
        return exp <= (now() if at is None else at)

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _split_tags(delimited: Optional[str]) -> List[str]:
        if not delimited:
            return []
        return [t for t in delimited.split(TAG_DELIMITER) if t]

    @classmethod
    def from_row(cls, row: tuple) -> "CacheEntry":
        """Build a ``CacheEntry`` from a raw ``(key, value_json, expires_at,
        tags, etag, created_at)`` row.

        The value column stores JSON text; we decode it back to native
        Python objects here.
        """
        (
            key,
            value_json,
            expires_at,
            tags_str,
            etag,
            created_at,
        ) = row
        value: Any = json.loads(value_json)
        return cls(
            key=key,
            value=value,
            expires_at=expires_at,
            tags=cls._split_tags(tags_str),
            etag=etag,
            created_at=created_at if created_at is not None else now(),
        )


class CacheStats(BaseModel):
    """Aggregate statistics describing cache behaviour.

    Attributes:
        hits: Number of successful cache reads.
        misses: Number of cache reads that found no (fresh) entry.
        total_entries: Number of stored entries on disk.
        expired_entries: Number of stored entries whose TTL has lapsed.
        active_entries: ``total_entries - expired_entries``.
        total_lookups: ``hits + misses``.
        hit_rate: ``hits / total_lookups``; ``1.0`` when there were no lookups.
        miss_rate: ``misses / total_lookups``; ``0.0`` when there were no lookups.
    """

    model_config = ConfigDict(extra="forbid")

    hits: int = 0
    misses: int = 0
    total_entries: int = 0
    expired_entries: int = 0

    @property
    def active_entries(self) -> int:
        return max(0, self.total_entries - self.expired_entries)

    @property
    def total_lookups(self) -> int:
        return self.hits + self.misses

    @property
    def hit_rate(self) -> float:
        if self.total_lookups == 0:
            return 1.0
        return self.hits / self.total_lookups

    @property
    def miss_rate(self) -> float:
        if self.total_lookups == 0:
            return 0.0
        return self.misses / self.total_lookups

    def as_dict(self) -> Dict[str, Any]:
        """Flattened dict of the headline metrics, handy for the CLI."""
        return {
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": round(self.hit_rate, 4),
            "miss_rate": round(self.miss_rate, 4),
            "total_entries": self.total_entries,
            "expired_entries": self.expired_entries,
            "active_entries": self.active_entries,
        }