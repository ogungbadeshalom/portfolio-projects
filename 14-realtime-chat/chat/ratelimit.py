"""In-memory rate limiting for chat messages.

A simple per-(user, room) sliding window keeps track of message send
timestamps. This is explicitly an in-memory limiter (per the project spec):
it resets on process restart and does not scale beyond one worker, which is
fine for a portfolio-grade app. Each entry holds a small timestamp deque.
"""
from __future__ import annotations

import time
import threading
from typing import DefaultDict, Deque, Tuple
from collections import defaultdict, deque


class RateLimiter:
    """Track and enforce a max-messages-per-window rate per key.

    The default policy from the spec is ``MAX_MESSAGES_PER_MINUTE = 10``.
    """

    def __init__(self, max_messages: int = 10, window_seconds: float = 60.0) -> None:
        self.max_messages = max_messages
        self.window_seconds = window_seconds
        self._timestamps: DefaultDict[Tuple[int, int], Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _key(self, user_id: int, room_id: int) -> Tuple[int, int]:
        return (user_id, room_id)

    def _prune(self, key: Tuple[int, int], now: float) -> None:
        """Pop timestamp entries older than the sliding window."""
        q = self._timestamps[key]
        cutoff = now - self.window_seconds
        while q and q[0] <= cutoff:
            q.popleft()

    def allow(self, user_id: int, room_id: int) -> bool:
        """Record a message and return whether it is permitted.

        Returns ``True`` when the message is under the window limit and records
        it; returns ``False`` when the user is over the limit (nothing recorded).
        """
        now = time.monotonic()
        key = self._key(user_id, room_id)
        with self._lock:
            self._prune(key, now)
            q = self._timestamps[key]
            if len(q) >= self.max_messages:
                return False
            q.append(now)
            return True

    def reset(self) -> None:
        """Clear all rate-limit state (used between tests)."""
        with self._lock:
            self._timestamps.clear()