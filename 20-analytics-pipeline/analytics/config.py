"""Application configuration.

All settings are read from environment variables so the same code runs in
production, containers, and tests without modification. Prefer upper-case
environment variables like the Starlette ``SettingsConfigDict`` convention.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings

#: Root of the analytics package on disk (used to resolve template/static dirs).
PACKAGE_DIR = Path(__file__).resolve().parent


def _env_boolean(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class Settings(BaseSettings):
    """Runtime configuration for the analytics pipeline."""

    # --- Server -----------------------------------------------------------
    host: str = "0.0.0.0"
    port: int = 8080

    # --- Storage ----------------------------------------------------------
    #: Absolute path to the OLAP database file. Empty string selects in-memory.
    database_path: str = ""
    #: Force a backend. One of "duckdb" | "sqlite" | "auto".
    #: "auto" prefers DuckDB when importable, else falls back to sqlite3 so the
    #: pipeline runs out-of-the-box with only the standard library.
    store_backend: str = "auto"
    #: Directory used for file-backed storage when `database_path` is empty.
    data_dir: str = ""

    # --- Ingestion --------------------------------------------------------
    #: Flush the ingest queue every N seconds (whichever comes first).
    flush_interval_seconds: float = 0.1
    #: Flush the ingest queue every N events (whichever comes first).
    batch_size: int = 1000
    #: Max events held in the in-memory queue (backpressure ceiling).
    queue_maxsize: int = 100000
    #: Stream the corresponding broadcast on interval for live counters.
    broadcast_interval_seconds: float = 5.0

    # --- Localisation -----------------------------------------------------
    #: IANA timezone used for *display*; events are always stored in UTC.
    display_tz: str = "UTC"

    # --- Derived paths ----------------------------------------------------
    @property
    def data_dir_path(self) -> Path:
        if self.data_dir:
            return Path(self.data_dir)
        return PACKAGE_DIR / "data"

    @property
    def default_db_path(self) -> Path:
        # In-memory by default, like the spec's "embedded, easier setup" story.
        if not self.database_path:
            return Path(":memory:")
        return Path(self.database_path)

    @staticmethod
    def utcnow() -> datetime:
        """Timezone-aware UTC now."""
        return datetime.now(timezone.utc)

    @field_validator("flush_interval_seconds", "batch_size", "queue_maxsize")
    @classmethod
    def _positive(cls, value: float, info) -> float:
        if value <= 0:
            raise ValueError(f"{info.field_name} must be positive")
        return value

    @field_validator("store_backend")
    @classmethod
    def _backend(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in {"auto", "duckdb", "sqlite"}:
            raise ValueError("store_backend must be auto|duckdb|sqlite")
        return value


def get_settings() -> Settings:
    """Cache a single Settings instance per process."""
    if not hasattr(get_settings, "_cached"):
        get_settings._cached = Settings()
    return get_settings._cached


#: Reload the cache when the module is reloaded in dev. Simple and idempotent.
def reset_settings() -> None:
    if hasattr(get_settings, "_cached"):
        del get_settings._cached


__all__: List[str] = ["Settings", "get_settings", "reset_settings", "PACKAGE_DIR"]