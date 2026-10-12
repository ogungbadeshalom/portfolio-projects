"""API-key authentication for CLI/HTTP calls.

The CLI talks to either the live HTTP API (sharing the server's key) or, when
started locally against the same database, writes directly to sqlite. Either
way a shared key is the boundary that keeps dashboard-enabling endpoints
(``start``/``done``) from being callable by anyone.

The key lives in ``CRONMON_API_KEY`` env var or a ``.api_key`` file next to
the database. :func:`load_or_create_key` returns a stable key per store so the
CLI and server agree without external secret management.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import sys
from pathlib import Path

#: Env var that overrides the persisted key.
ENV_KEY = "CRONMON_API_KEY"


def _key_file() -> Path:
    """Path to the per-store key file (~/.cronmon for the default store)."""
    override = os.getenv("CRONMON_DB")
    if override and override not in (":memory:", ""):
        # Sidecar file next to the database keeps key and data together.
        return Path(override).with_suffix(".api_key")
    return Path.home() / ".cronmon" / "api_key"


def load_or_create_key() -> str:
    """Read the API key, creating one if none exists.

    If ``CRONMON_API_KEY`` is set it wins (good for CI/tests). Otherwise the
    per-store key file is used, created on first call. In-memory / test stores
    fall back to a deterministic insecure key so tests interact as-is.
    """
    env = os.getenv(ENV_KEY)
    if env:
        return env
    db = os.getenv("CRONMON_DB", "")
    if not db or db == ":memory:":
        return "dev-insecure-key"
    key_file = _key_file()
    if not key_file.exists():
        key_file.parent.mkdir(parents=True, exist_ok=True)
        key_file.write_text(f"ck_{secrets.token_urlsafe(32)}", encoding="utf-8")
    return key_file.read_text(encoding="utf-8").strip()


def verify(provided: str) -> bool:
    """Constant-time compare of a caller-supplied key against the current one."""
    expected = (os.getenv(ENV_KEY) or load_or_create_key()).encode()
    return secrets.compare_digest(provided.encode(), expected)


def fingerprint(api_key: str) -> str:
    """Short, non-reversible identifier of the key for display/logging."""
    return hashlib.sha256(api_key.encode()).hexdigest()[:8]


__all__ = ["load_or_create_key", "verify", "fingerprint", "ENV_KEY"]