"""In-memory sliding-window rate limiter (token-bucket style).

Backing store is a per-key deque of request timestamps (a true sliding window,
smoother than a fixed window). Works out of the box with no Redis; the
interface is small enough to swap for a shared store in a multi-process
deployment later.

The limiter is not thread-locked (each request thread calls ``check`` quickly
under the GIL); for strict cross-thread accuracy a ``threading.Lock`` is held
only while pruning/acquiring a token slot.
"""

from __future__ import annotations

import threading
import time
from typing import Dict, List


class SlidingWindowLimiter:
    """Per-key sliding-window request limiter."""

    def __init__(self) -> None:
        self._window: Dict[str, List[float]] = {}
        self._lock = threading.Lock()

    def check(
        self,
        key: str,
        limit: int,
        window_seconds: int = 60,
    ) -> "LimitDecision":
        """Record a request against ``key`` and decide if it is allowed.

        Returns a :class:`LimitDecision` with ``allowed``, the number of
        requests remaining in the window, and the seconds until the window
        resets (for the ``Retry-After`` header).
        """
        now = time.monotonic()
        deadline = now - window_seconds

        with self._lock:
            hits = self._window.get(key, [])
            # Prune entries older than the window.
            hits = [t for t in hits if t > deadline]
            # the count that would result if this request is admitted
            if len(hits) >= limit:
                # A slot is not available -> denied; reset = time oldest frees.
                if hits:
                    reset = max(0.0, (hits[0] + window_seconds) - now)
                else:
                    reset = float(window_seconds)
                self._window[key] = hits
                return LimitDecision(allowed=False, remaining=0, retry_after=reset)

            hits.append(now)
            self._window[key] = hits
            remaining = max(0, limit - len(hits))
            return LimitDecision(allowed=True, remaining=remaining, retry_after=0.0)

    def reset(self, key: str) -> None:
        with self._lock:
            self._window.pop(key, None)

    def snapshot(self) -> Dict[str, int]:
        with self._lock:
            return {k: len(v) for k, v in self._window.items()}


class LimitDecision:
    __slots__ = ("allowed", "remaining", "retry_after")

    def __init__(self, allowed: bool, remaining: int, retry_after: float):
        self.allowed = allowed
        self.remaining = remaining
        self.retry_after = retry_after

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<LimitDecision allowed={self.allowed} remaining={self.remaining} retry_after={self.retry_after:.2f}>"


# Module-level singleton (matching Redis's "one store" mental model).
_limiter = SlidingWindowLimiter()


def get_limiter() -> SlidingWindowLimiter:
    return _limiter


def check_limit(tenant_id: int, endpoint: str, *, limit: int, window_seconds: int = 60) -> LimitDecision:
    """Convenience: rate-limit a (tenant, endpoint) pair."""
    key = f"{tenant_id}:{endpoint}"
    return get_limiter().check(key, limit, window_seconds)


def reset(tenant_id: int, endpoint: str) -> None:
    get_limiter().reset(f"{tenant_id}:{endpoint}")


def reset_limiter() -> None:
    """Drop all in-memory rate-limit state (used between test apps)."""
    global _limiter
    _limiter = SlidingWindowLimiter()


def replace_limiter(limiter: "SlidingWindowLimiter") -> None:
    """Swap in a custom limiter instance (isolation/testing)."""
    global _limiter
    _limiter = limiter