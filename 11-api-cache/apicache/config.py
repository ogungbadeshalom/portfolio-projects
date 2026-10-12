"""Configuration defaults and runtime settings for :mod:`apicache`.

The library keeps configuration explicit and lightweight: a small set of
tunables with sane defaults, overridable per-call.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

#: Default TTL (seconds) applied when no per-key TTL is supplied.
DEFAULT_TTL: int = 300

#: Default background cleanup interval (seconds) when a periodic task is enabled.
DEFAULT_CLEANUP_INTERVAL: float = 60.0

#: Default in-process cache capacity for the optional L1 hot-path cache.
DEFAULT_MEMORY_LIMIT: int = 10_000


def validate_ttl(ttl: Optional[float]) -> Optional[float]:
    """Validate a TTL value and return a usable ``float`` or ``None``.

    ``None`` (or a non-positive value with ``allow_none=False``) means "do
    not expire". Raises :class:`ValueError` for malformed (non-numeric) input.

    Args:
        ttl: Raw TTL value supplied by a caller.

    Returns:
        A finite non-negative float, or ``None`` for no-expiry.

    Raises:
        ValueError: If ``ttl`` is neither numeric nor ``None``.
    """
    if ttl is None:
        return None
    f: float = float(ttl)
    if f < 0:
        return None
    return f


def resolve_db_path(db_path: Optional[str]) -> str:
    """Resolve a user-supplied DB path to a stable string.

    ``":memory:"`` is passed through untouched so callers can opt into an
    in-memory database. Anything else is normalized to an absolute path
    (parents created as needed).

    Args:
        db_path: Raw database path handed into :class:`APICache`.

    Returns:
        The resolved path string.
    """
    if not db_path:
        return DEFAULT_DB_PATH
    if db_path == ":memory:":
        return ":memory:"
    p = Path(db_path).expanduser().resolve()
    if str(p) != ":memory:" and p.parent and p.parent != Path("."):
        try:
            os.makedirs(p.parent, exist_ok=True)
        except OSError:
            pass  # DB layer will surface real filesystem errors on open.
    return str(p)


#: Default database file name relative to the current working directory.
DEFAULT_DB_PATH: str = "apicache.db"