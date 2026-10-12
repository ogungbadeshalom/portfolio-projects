"""Runtime configuration for the task scheduler.

All knobs read from environment variables (with sane defaults) so the same
code runs in production, containers, and tests unchanged. No external services
are required -- the scheduler uses an in-process SQLite store for persistence
(so tasks survive crashes) plus a thread-safe in-memory ready-queue for fast
delivery to workers.
"""

from __future__ import annotations

import os
from pathlib import Path

#: Root of the package on disk (for templates/static resolution).
PACKAGE_DIR = Path(__file__).resolve().parent


class Config:
    """Read-only settings bag. Values are read from env at instantiation.

    Only a single instance is created lazily via :func:`get_config`; tests can
    build their own ``Config`` to point at an isolated store.
    """

    # --- Server ------------------------------------------------------
    host: str = os.getenv("SCHEDULER_HOST", "0.0.0.0")
    port: int = int(os.getenv("SCHEDULER_PORT", "9000"))

    # --- Database ----------------------------------------------------
    #: Path to the sqlite store. Empty string -> in-memory (loses data on exit).
    database_path: str = os.getenv("SCHEDULER_DB", "")

    # --- Tasks -------------------------------------------------------
    #: At-least-once: default cap on execution attempts before a task is
    #: parked in the dead-letter queue.
    max_attempts: int = int(os.getenv("SCHEDULER_MAX_ATTEMPTS", "5"))
    #: Base delay (seconds) for exponential backoff: delay = base * 2**attempt.
    backoff_base_seconds: float = float(os.getenv("SCHEDULER_BACKOFF_BASE", "1"))
    #: Upper bound on backoff delay.
    backoff_max_seconds: float = float(os.getenv("SCHEDULER_BACKOFF_MAX", "60"))
    #: Fraction of jitter applied to each backoff delay.
    backoff_jitter: float = float(os.getenv("SCHEDULER_BACKOFF_JITTER", "0.1"))
    #: Default timeout (seconds) that kills a long-running task.
    task_timeout_seconds: float = float(os.getenv("SCHEDULER_TASK_TIMEOUT", "300"))

    # --- Workers -----------------------------------------------------
    #: How often a worker writes its heartbeat (seconds).
    heartbeat_interval_seconds: float = float(
        os.getenv("SCHEDULER_HEARTBEAT_INTERVAL", "5")
    )
    #: A worker whose heartbeat is older than this is considered dead (seconds).
    worker_timeout_seconds: float = float(os.getenv("SCHEDULER_WORKER_TIMEOUT", "30"))

    # --- Scheduler ---------------------------------------------------
    #: How often the dispatcher scans for due cron/one-time tasks.
    scan_interval_seconds: float = float(os.getenv("SCHEDULER_SCAN_INTERVAL", "5"))

    def __init__(self) -> None:
        # Resolve derived path once now that class attrs are set.
        self.database_path = self.database_path or ":memory:"
        self.data_dir = PACKAGE_DIR / "data"

    @property
    def effective_db_path(self) -> str:
        """The sqlalchemy-friendly connection string for the store."""
        if self.database_path == ":memory:":
            return ":memory:"
        path = Path(self.database_path)
        if path.parent and str(path.parent) not in (".", ""):
            path.parent.mkdir(parents=True, exist_ok=True)
        return str(path)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"Config(db={self.database_path!r}, max_attempts={self.max_attempts}, "
            f"backoff_base={self.backoff_base_seconds}s)"
        )


_cached: Config | None = None


def get_config() -> Config:
    """Return a cached Config instance (per-process singleton)."""
    global _cached  # noqa: PLW0603
    if _cached is None:
        _cached = Config()
    return _cached


def reset_config() -> None:
    """Drop the cached config (used by tests)."""
    global _cached  # noqa: PLW0603
    _cached = None


__all__ = ["Config", "get_config", "reset_config", "PACKAGE_DIR"]