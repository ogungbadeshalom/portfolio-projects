"""Compact 5-field cron parser + next-fire-time computation (stdlib only).

Supports ``*``, numbers, lists ``1,3``, ranges ``1-5`` and steps ``*/5`` /
``1-10/2``. Used by the dispatcher to mint the next run instance of a cron
task. Purple of the same matcher in the cron-monitor project re-homed here to
keep this package self-contained.
"""

from __future__ import annotations

from datetime import datetime, timedelta

_FIELDS = [
    ("minute", 0, 59),
    ("hour", 0, 23),
    ("day", 1, 31),
    ("month", 1, 12),
    ("dow", 0, 6),  # 0 = Sunday
]


class CronError(ValueError):
    """Raised for an unparseable or out-of-range cron expression."""


def _parse_field(part: str, lo: int, hi: int) -> set[int]:
    allowed: set[int] = set()
    for piece in part.split(","):
        step = 1
        if "/" in piece:
            piece, _, step_s = piece.partition("/")
            step = int(step_s)
            if step < 1:
                raise CronError(f"step must be >= 1, got {step_s!r}")
        if piece in {"", "*"}:
            start, end = lo, hi
        elif "-" in piece:
            start_s, _, end_s = piece.partition("-")
            start, end = int(start_s), int(end_s)
        else:
            start = end = int(piece)
        if not (lo <= start <= hi) or not (lo <= end <= hi) or start > end:
            raise CronError(f"value out of range {part!r}")
        allowed.update(range(start, end + 1, step))
    if not allowed:
        raise CronError(f"empty field {part!r}")
    return allowed


class CronExpr:
    """A parsed 5-field cron expression."""

    __slots__ = ("raw", "fields")

    def __init__(self, expression: str):
        self.raw = expression.strip()
        parts = self.raw.split()
        if len(parts) != 5:
            raise CronError(f"expected 5 fields, got {len(parts)} in {self.raw!r}")
        self.fields = [
            _parse_field(part, lo, hi)
            for part, (_name, lo, hi) in zip(parts, _FIELDS)
        ]

    def matches(self, dt: datetime) -> bool:
        parts = (dt.minute, dt.hour, dt.day, dt.month, (dt.weekday() + 1) % 7)
        return all(v in f for v, f in zip(parts, self.fields))

    def next_fire(self, after: datetime) -> datetime:
        """Earliest fire time strictly after ``after`` (minute resolution)."""
        dt = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
        for _ in range(366 * 24 * 60):
            if self.matches(dt):
                return dt
            dt += timedelta(minutes=1)
        raise CronError(f"no fire time within a year for {self.raw!r}")

    def __repr__(self) -> str:
        return f"CronExpr({self.raw!r})"


def next_fire(expression: str, after: datetime) -> datetime:
    """Convenience: parse ``expression`` and return its next fire after ``after``."""
    return CronExpr(expression).next_fire(after)


__all__ = ["CronExpr", "next_fire", "CronError"]