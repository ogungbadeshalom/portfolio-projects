"""Configuration for the GitHub -> Slack webhook notifier.

Secrets are read from environment variables with sane development defaults,
so the app runs out of the box with zero configuration (see the ``defaults``
values below). In production you MUST set ``GITHUB_WEBHOOK_SECRET`` and
``SLACK_WEBHOOK_URL``.

Everything is expressed as a plain dataclass so it can be imported freely
without triggering Flask at import time (which helps runnable tests).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


def _env(name: str, default: Optional[str]) -> Optional[str]:
    """Read ``name`` from the environment, returning ``default`` if unset."""
    return os.environ.get(name, default)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class Config:
    """Immutable application configuration."""

    #: Shared secret used to HMAC-SHA256 sign webhook payloads.
    github_webhook_secret: str = field(
        default_factory=lambda: _env("GITHUB_WEBHOOK_SECRET", "dev-secret")  # type: ignore[arg-type]
    )

    #: Public Slac Incoming Webhook URL. Set to disable actual delivery.
    slack_webhook_url: Optional[str] = field(
        default_factory=lambda: _env("SLACK_WEBHOOK_URL", None)
    )

    #: Optional verbosity for async httpx Slack client (0 = never, 1 = always).
    slack_client_enabled: bool = field(
        default_factory=lambda: _env("SLACK_CLIENT_ENABLED", "1") == "1"
    )

    #: Number of delivery attempts before an event is marked failed.
    max_retries: int = field(default_factory=lambda: _env_int("MAX_RETRIES", 3))

    #: Base backoff (seconds) for the exponential-backoff schedule.
    backoff_base_seconds: float = field(
        default_factory=lambda: float(_env("BACKOFF_BASE_SECONDS", "1.0"))
    )

    #: Database URL. An in-memory SQLite db is used when unset.
    database_url: str = field(
        default_factory=lambda: _env("DATABASE_URL", "sqlite:///githook.db")
    )

    #: Root of the project (used to resolve templates/ and the sqlite file).
    base_dir: Path = field(
        default_factory=lambda: Path(os.path.dirname(os.path.abspath(__file__))).parent
    )

    #: Log level for the root logger.
    log_level: int = field(
        default_factory=lambda: getattr(
            logging, _env("LOG_LEVEL", "INFO").upper(), logging.INFO
        )
    )

    #: Convenience accessor for the events rendered on ``GET /events``.
    recent_events_limit: int = field(default_factory=lambda: _env_int("EVENTS_LIMIT", 100))


def configure_logging(level: Optional[int] = None) -> None:
    """Bootstrap the root logger with a reasonable text format."""
    logging.basicConfig(
        level=level if level is not None else Config().log_level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )