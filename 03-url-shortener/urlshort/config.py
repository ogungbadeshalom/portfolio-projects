"""Application settings.

Configuration is read from environment variables prefixed with ``URLSHORT_``
(optionally from a local ``.env`` file). Keeping this dependency-free means the
app boots even in bare environments before optional packages are installed.

Overridable values:

* ``URLSHORT_DATABASE_DIR``  -> directory that holds SQLite db (default ``data``)
* ``URLSHORT_DATABASE_URL``  -> SQLAlchemy async URL (default sqlite+aiosqlite)
* ``URLSHORT_CODE_LENGTH``   -> generated short code length (default 7)
* ``URLSHORT_BASE_URL``      -> absolute base for short URLs (default: relative)
* ``URLSHORT_MAX_CODE_LENGTH`` -> upper bound for custom aliases (default 128)
* ``URLSHORT_CORS_ORIGINS``  -> comma-separated allowlist, ``*`` for any (default *)
* ``URLSHORT_RATE_LIMIT``    -> slowapi limit string (default ``100/minute``)
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

_ENV_PREFIX = "URLSHORT_"


def _env(name: str, default: str) -> str:
    """Return an env var (with prefix) or the given default."""
    return os.environ.get(_ENV_PREFIX + name, default)


class Settings:
    """Plain-attribute container of runtime configuration.

    A class (not a bare dict/namespace) so type hints and a single definition
    site are available, and so a future structured-config backend (Pydantic
    settings, dynaconf, etc.) can swap in behind the same reading code.
    """

    database_dir: Path
    database_url: str
    code_length: int
    base_url: Optional[str]
    max_code_length: int
    cors_origins: str
    rate_limit: str

    def __init__(self) -> None:
        self.database_dir = Path(_env("DATABASE_DIR", "data"))
        self.database_url = _env(
            "DATABASE_URL",
            "sqlite+aiosqlite:///./data/shortener.db",
        )
        self.code_length = int(_env("CODE_LENGTH", "7"))
        base_url = _env("BASE_URL", "")
        self.base_url = base_url or None
        self.max_code_length = int(_env("MAX_CODE_LENGTH", "128"))
        self.cors_origins = _env("CORS_ORIGINS", "*")
        self.rate_limit = _env("RATE_LIMIT", "100/minute")

    @property
    def database_path(self) -> Path:
        """Filesystem path of the SQLite database (empty for non-SQLite backends)."""
        if self.database_url.startswith("sqlite"):
            rel = self.database_url.split("///", 1)[-1]
            return Path(rel) if rel and rel != ":" else Path("")
        return Path("")


# A single importable instance — every module reads one source of truth.
settings = Settings()