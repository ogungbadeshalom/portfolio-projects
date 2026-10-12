"""Parse FFmpeg progress output.

The build-order spec calls for parsing FFmpeg's stderr ``time=`` lines; the
code standards later recommend ``-progress pipe:1`` which emits the same
time base but in a machine-readable ``out_time_ms=`` form.  This module
supports both so either flag style works.

Both functions are pure and synchronous -- handy for unit testing without
spawning a subprocess.
"""

from __future__ import annotations

import re
from typing import Optional

# ``-progress pipe:1`` key/value stream.
_MS_LINE = re.compile(r"^out_time_ms=([0-9]+)$", re.MULTILINE)
_STATE_LINE = re.compile(r"^progress=(continue|end)$", re.MULTILINE)

# Classic stderr ``time=00:01:23.45`` lines.
_TIME_LINE = re.compile(r"time=(\d+):(\d+):([0-9.]+)")
_TIME_SEC_RE = re.compile(r"time=(\d+\.?\d*)")


def parse_progress_pipe1(raw: str, duration_seconds: Optional[float] = None) -> float:
    """Return the latest progress percent from an ``out_time_ms`` stream.

    ``raw`` is the concatenated text of one ``-progress pipe:1`` read.
    Returns a value in ``[0, 99.0]`` (the last full percent is left to the
    caller reporting completion) or ``0.0`` when nothing parseable is found.
    """
    ms = _MS_LINE.findall(raw)
    if not ms:
        return 0.0
    # NB: FFmpeg's ``out_time_ms`` field is actually **microseconds**.
    current_us = int(ms[-1])
    if duration_seconds and duration_seconds > 0:
        total_us = duration_seconds * 1_000_000.0
        return min(99.0, current_us / total_us * 100.0)
    # Unknown duration: monotonic ramp from number of emitted samples.
    return min(99.0, len(ms) * 5.0)


def parse_stderr_progress(raw: str) -> Optional[float]:
    """Parse classic ``time=HH:MM:SS.mmm`` lines into seconds (or ``None``)."""
    # ``_TIME_LINE`` matches the full clock form.
    m = _TIME_LINE.findall(raw)
    if m:
        hh, mm, ss = m[-1]
        return int(hh) * 3600 + int(mm) * 60 + float(ss)
    m2 = _TIME_SEC_RE.findall(raw)
    if m2:
        return float(m2[-1])
    return None


def progress_from_stderr(raw: str, duration_seconds: Optional[float] = None) -> float:
    """Compute a percent from stderr ``time=`` lines.

    Prefer :func:`parse_progress_pipe1` when ``-progress pipe:1`` is used;
    this helper exists for the build-order step and for human fallback.
    """
    seconds = parse_stderr_progress(raw)
    if seconds is None:
        return 0.0
    if duration_seconds and duration_seconds > 0:
        return min(99.0, seconds / duration_seconds * 100.0)
    return seconds