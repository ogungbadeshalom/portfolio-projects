"""Configuration for the file upload service.

Settings are read from environment variables with an ``UPLOAD_`` prefix,
falling back to the defaults below. Kept dependency-free (no Pydantic
settings) so the package imports in bare environments.
"""
from __future__ import annotations

import os
from pathlib import Path

_ENV_PREFIX = "UPLOAD_"

#: Default maximum upload size in bytes (100 MB).
DEFAULT_MAX_SIZE = 100 * 1024 * 1024
#: Default signed-URL lifetime in seconds (1 hour).
DEFAULT_EXPIRES = 3600
#: Secret used to sign URLs (override in production).
DEFAULT_SECRET = "dev-insecure-secret-change-me"

#: Whitelisted MIME types. Default: images, PDFs and common documents.
DEFAULT_ALLOWED_TYPES = (
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
    "image/svg+xml",
    "application/pdf",
    "text/plain",
    "text/markdown",
    "text/html",
    "application/json",
    "application/xml",
    "application/octet-stream",
)


def _env(name: str, default: str) -> str:
    return os.environ.get(_ENV_PREFIX + name, default)


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


class Settings:
    """Runtime settings container parsed from the environment."""

    storage_dir: Path
    max_size: int
    allowed_types: tuple[str, ...]
    expires_in: int
    secret: str
    use_range: bool

    def __init__(self) -> None:
        self.storage_dir = Path(_env("STORAGE_DIR", "storage"))
        self.max_size = _env_int("MAX_SIZE", DEFAULT_MAX_SIZE)
        raw_types = _env("ALLOWED_TYPES", ",".join(DEFAULT_ALLOWED_TYPES))
        self.allowed_types = tuple(t.strip() for t in raw_types.split(",") if t.strip())
        self.expires_in = _env_int("EXPIRES", DEFAULT_EXPIRES)
        self.secret = _env("SECRET", DEFAULT_SECRET)
        self.use_range = _env("USE_RANGE", "1") == "1"


settings = Settings()