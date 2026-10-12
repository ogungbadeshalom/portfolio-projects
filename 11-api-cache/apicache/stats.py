"""Hit/miss accounting for the cache.

The tracker is monotonic per ``APICache`` instance; snapshotting projects both
raw counters and derived ratios (hit rate, miss rate).
"""
from __future__ import annotations

from apicache.models import CacheStats


class StatsTracker:
    """A small, thread-safe hit/miss counter backed by :mod:`threading`."""

    def __init__(self) -> None:
        self.hits = 0
        self.misses = 0

    def record_hit(self) -> None:
        self.hits += 1

    def record_miss(self) -> None:
        self.misses += 1

    def snapshot(self, total_entries: int, expired_entries: int) -> CacheStats:
        """Return a :class:`CacheStats` for the given store-level counts."""
        return CacheStats(
            hits=self.hits,
            misses=self.misses,
            total_entries=total_entries,
            expired_entries=expired_entries,
        )

    def reset(self) -> None:
        self.hits = 0
        self.misses = 0