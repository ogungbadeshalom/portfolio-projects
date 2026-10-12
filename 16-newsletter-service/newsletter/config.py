"""Application configuration, read from environment variables.

Every value that differs between dev / test / prod lives here so the same
codebase runs against SQLite locally, the FileSender dev backend offline, or a
real (e.g. Mailtrap) SMTP host with only an env restore.

Environment variables (all optional, sensible defaults provided):

    NEWSLETTER_DB_URL          SQLAlchemy database URL (default: sqlite file in project dir)
    NEWSLETTER_BASE_URL        Public base URL used to build tracking/unsubscribe links
    NEWSLETTER_FROM_EMAIL      "Name <addr>" the sender should present
    NEWSLETTER_SENDER_BACKEND  auto | aiosmtplib | smtplib | file
    NEWSLETTER_SMTP_HOST       SMTP host (Mailtrap-friendly default)
    NEWSLETTER_SMTP_PORT       SMTP port
    NEWSLETTER_SMTP_USERNAME   SMTP username
    NEWSLETTER_SMTP_PASSWORD   SMTP password
    NEWSLETTER_SMTP_USE_TLS    "1"/"0" -- STARTTLS on connect
    NEWSLETTER_OUTBOX_DIR      Directory the FileSender backend writes .eml files to
    NEWSLETTER_RATE_PER_MIN    Max emails per minute when sending a campaign
    NEWSLETTER_HMAC_SECRET     Secret used to sign/verify unsubscribe tokens
    NEWSLETTER_ADMIN_USER      Admin dashboard username
    NEWSLETTER_ADMIN_PASSWORD  Admin dashboard password
    NEWSLETTER_COMPANY_NAME    Sender/site name used in templates and the footer
"""

from __future__ import annotations

import os
from pathlib import Path

from newsletter import DB_URL_DEFAULT

_PROJECT_DIR = Path(__file__).resolve().parent.parent


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "y"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


class Settings:
    """Stateless settings bag backed by the process environment."""

    def __init__(self) -> None:
        self.db_url: str = os.getenv("NEWSLETTER_DB_URL", DB_URL_DEFAULT)
        self.base_url: str = os.getenv(
            "NEWSLETTER_BASE_URL", "http://localhost:8080"
        ).rstrip("/")
        self.from_email: str = os.getenv(
            "NEWSLETTER_FROM_EMAIL", "Newsletter <noreply@example.com>"
        )
        self.sender_backend: str = os.getenv(
            "NEWSLETTER_SENDER_BACKEND", "auto"
        ).lower()

        self.smtp_host: str = os.getenv("NEWSLETTER_SMTP_HOST", "sandbox.smtp.mailtrap.io")
        self.smtp_port: int = _env_int("NEWSLETTER_SMTP_PORT", 2525)
        self.smtp_username: str = os.getenv("NEWSLETTER_SMTP_USERNAME", "mailtrap")
        self.smtp_password: str = os.getenv("NEWSLETTER_SMTP_PASSWORD", "mailtrap")
        self.smtp_use_tls: bool = _env_bool("NEWSLETTER_SMTP_USE_TLS", True)

        self.outbox_dir: Path = Path(
            os.getenv("NEWSLETTER_OUTBOX_DIR", str(_PROJECT_DIR / "outbox"))
        )
        self.rate_per_min_: int = _env_int("NEWSLETTER_RATE_PER_MIN", 100)

        self.hmac_secret: str = os.getenv(
            "NEWSLETTER_HMAC_SECRET", "dev-change-me-newsletter-secret"
        )

        self.admin_user: str = os.getenv("NEWSLETTER_ADMIN_USER", "admin")
        self.admin_password: str = os.getenv("NEWSLETTER_ADMIN_PASSWORD", "admin")

        self.company_name: str = os.getenv(
            "NEWSLETTER_COMPANY_NAME", "Newsletter Service"
        )

    @property
    def rate_per_min(self) -> float:
        """Per-minute email throttle; guard against zero/negative config."""
        return max(self.rate_per_min_, 1)


def load_settings() -> Settings:
    """Build a fresh :class:`Settings`. Kept as a function so callers can
    override env vars and re-load for tests without shared stale state."""
    return Settings()

# Module-level convenience instance (constants, CLI, and app share one config).
settings = load_settings()