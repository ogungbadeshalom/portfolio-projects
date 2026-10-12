"""Exponential backoff with jitter for task retries.

``next_attempt_delay`` implements::

    delay = min(backoff_max, backoff_base * 2 ** attempts)
    delay += uniform(-jitter, +jitter) * delay

plus an optional fixed ``scheduled_vs_now`` corrector. The dispatcher uses this
to compute ``due_at`` for a failed task's next attempt; a small random jitter
spreads retries so many tasks failing at once don't thundering-herd.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta

from scheduler.models import now_utc


def backoff_delay_seconds(
    attempts: int,
    *,
    base: float = 1.0,
    max_seconds: float = 60.0,
    jitter: float = 0.1,
    rng: random.Random | None = None,
) -> float:
    """Seconds to wait before attempt ``attempts`` (0-indexed current try).

    Attempt 0 (first try, the one that just failed) => delay 2**0 * base = base.
    """
    raw = base * (2 ** max(0, attempts))
    delay = min(raw, max_seconds)
    rng = rng or random
    span = delay * jitter
    delay += rng.uniform(-span, span)
    return max(0.0, delay)


def next_attempt_at(
    attempts: int,
    *,
    base: float = 1.0,
    max_seconds: float = 60.0,
    jitter: float = 0.1,
    now: datetime | None = None,
    rng: random.Random | None = None,
) -> datetime:
    """UTC datetime when the next attempt should run."""
    return (now or now_utc()) + timedelta(
        seconds=backoff_delay_seconds(attempts, base=base, max_seconds=max_seconds, jitter=jitter, rng=rng)
    )


def is_exhausted(attempts: int, max_attempts: int) -> bool:
    """True when ``attempts`` reached the cap and the task should go to the DLQ."""
    return attempts >= max_attempts


__all__ = ["backoff_delay_seconds", "next_attempt_at", "is_exhausted"]