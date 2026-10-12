"""Minimal 5-field cron matcher + next-fire-time computation (stdlib only).

The watchdog needs to answer *"has this job missed its next scheduled fire
time?"* which requires, given a cron expression, computing when it last
was / next will be due. ``croniter`` is the usual tool but is not always
installable, so this module implements the small subset we need:

* ``CronExpr`` parses a standard 5-field cron (``min hour dom mon dow``),
  supporting ``*``, numeric values, lists ``1,3``, ranges ``1-5``, and step
  values ``*/5`` (and ``range/step``).
* ``next_fire``/``prev_fire`` walk one minute at a time back/forward to find
  the nearest valid minute — perfectly adequate for a watchdog that runs the
  check every minute.

Unparseable expressions raise :class:`ValueError`; jobs with a bad cron are
skipped by the watchdog rather than crashing the sweep.
"""

from __future__ import annotations

from datetime import datetime, timedelta

# Field bounds for validation/indexing.
_FIELDS = [
    ("minute", 0, 59),
    ("hour", 0, 23),
    ("day", 1, 31),
    ("month", 1, 12),
    ("dow", 0, 6),  # 0 = Sunday, cron standard
]
_NAMES = ["minute", "hour", "day", "month", "dow"]


class CronExpr:
    """A parsed 5-field cron expression.

    Attributes
    ----------
    values : list[set[int]]
        One set of allowed values per field (minute, hour, day, month, dow).
    raw : str
        The original expression as given.
    """

    __slots__ = ("raw", "values")

    def __init__(self, expression: str):
        self.raw = expression.strip()
        parts = self.raw.split()
        if len(parts) != 5:
            raise ValueError(
                f"Invalid cron {self.raw!r}: expected 5 fields (min hour dom mon dow)"
            )
        self.values = [self._parse(part, lo, hi, name) for part, (name, lo, hi) in zip(parts, _FIELDS)]

    @staticmethod
    def _parse(part: str, lo: int, hi: int, name: str) -> set[int]:
        if part == "*":
            return set(range(lo, hi + 1))
        allowed: set[int] = set()
        for piece in part.split(","):
            step = 1
            if "/" in piece:
                piece, _, step_s = piece.partition("/")
                step = int(step_s)
                if step < 1:
                    raise ValueError(f"step must be >=1 in cron field {name}")
            if piece in {"*", ""}:
                start, end = lo, hi
            elif "-" in piece:
                start_s, _, end_s = piece.partition("-")
                start, end = int(start_s), int(end_s)
            else:
                start = end = int(piece)
            if not (lo <= start <= hi) or not (lo <= end <= hi) or start > end:
                raise ValueError(f"out-of-range value in cron field {name}: {part!r}")
            allowed.update(range(start, end + 1, step))
        if not allowed:
            raise ValueError(f"empty cron field {name}: {part!r}")
        return allowed

    def matches(self, dt: datetime) -> bool:
        """True when ``dt`` (local-naive) falls on an allowed minute."""
        parts = (
            dt.minute,
            dt.hour,
            dt.day,
            dt.month,
            (dt.weekday() + 1) % 7,  # ISO weekday 0=Mon -> cron 0=Sun
        )
        return all(v in allowed for v, allowed in zip(parts, self.values))

    def next_fire(self, after: datetime) -> datetime:
        """Earliest fire time strictly after ``after`` (minute resolution)."""
        dt = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
        guard = 0
        while guard < 366 * 24 * 60:  # ~1 year of minutes
            if self.matches(dt):
                return dt
            dt += timedelta(minutes=1)
            guard += 1
        raise ValueError(f"no fire time found within a year for {self.raw!r}")

    def prev_fire(self, before: datetime) -> datetime:
        """Latest fire time strictly before ``before`` (minute resolution)."""
        dt = before.replace(second=0, microsecond=0) - timedelta(minutes=1)
        guard = 0
        while guard < 366 * 24 * 60:
            if self.matches(dt):
                return dt
            dt -= timedelta(minutes=1)
            guard += 1
        raise ValueError(f"no prior fire time found within a year for {self.raw!r}")

    def __repr__(self) -> str:
        return f"CronExpr({self.raw!r})"


def next_fire(expression: str, after: datetime) -> datetime:
    """Convenience wrapper: parse ``expression`` and return next fire time."""
    return CronExpr(expression).next_fire(after)


__all__ = ["CronExpr", "next_fire"]