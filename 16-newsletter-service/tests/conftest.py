"""Pytest fixtures and environment setup for the newsletter test suite.

Immediately runnable, offline, self-contained: we force the FileSender backend,
a throwaway temp SQLite database and outbox directory, and known HMAC/admin
credentials BEFORE importing any ``newsletter.*`` module (the module-level
engines in ``newsletter.db`` are built from ``NEWSLETTER_DB_URL`` at import time,
so the environment must be set first). Everything is torn down with the temp dir
when the test session ends.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# --- Environment is configured BEFORE importing the package -------------------
_TMP = Path(tempfile.mkdtemp(prefix="newsletter_test_"))

os.environ.setdefault("NEWSLETTER_DB_URL", f"sqlite:///{_TMP / 'test.db'}")
os.environ.setdefault("NEWSLETTER_SENDER_BACKEND", "file")
os.environ.setdefault("NEWSLETTER_OUTBOX_DIR", str(_TMP / "outbox"))
os.environ.setdefault("NEWSLETTER_HMAC_SECRET", "test-hmac-secret")
os.environ.setdefault("NEWSLETTER_BASE_URL", "http://testserver")
os.environ.setdefault("NEWSLETTER_RATE_PER_MIN", "1000")
os.environ.setdefault("NEWSLETTER_ADMIN_USER", "admin")
os.environ.setdefault("NEWSLETTER_ADMIN_PASSWORD", "admin")

# Import the package now that the env is pinned (must happen after the block above).
from newsletter.config import settings  # noqa: E402
from newsletter.db import SessionLocal, async_engine, init_db  # noqa: E402
from newsletter.main import app  # noqa: E402
from newsletter.models import Campaign, Send, Subscriber  # noqa: E402


# --- Paths helpers ------------------------------------------------------------

@pytest.fixture()
def outbox_dir() -> Path:
    """The FileSender output directory (shared temp dir for the session)."""
    return settings.outbox_dir


@pytest.fixture()
def eml_files(outbox_dir: Path) -> list[Path]:
    """Snapshot of the .eml files present in the outbox at call time."""
    outbox_dir.mkdir(parents=True, exist_ok=True)
    return sorted(outbox_dir.glob("*.eml"))


def _eml_bodies() -> list[str]:
    outbox_dir = settings.outbox_dir
    if not outbox_dir.exists():
        return []
    return [p.read_text(encoding="utf-8") for p in sorted(outbox_dir.glob("*.eml"))]


# --- Session-scoped table bootstrap -------------------------------------------

@pytest.fixture(scope="session", autouse=True)
def _bootstrap_db():
    """Create all tables once for the shared temp database."""
    init_db()
    yield


# --- Per-test cleanup ---------------------------------------------------------

@pytest.fixture(autouse=True)
def _clean_tables(_bootstrap_db):
    """Erase all rows before each test so every test starts from an empty DB
    (SQLite with the shared temp file; FK pruning is safe even on naive delete)."""
    with SessionLocal() as session:
        session.query(Send).delete()
        session.query(Campaign).delete()
        session.query(Subscriber).delete()
        session.commit()
    yield


# --- HTTP client --------------------------------------------------------------

@pytest.fixture()
def client():
    """A TestClient wired to the FastAPI app (lifespan runs ``ainit_db``)."""
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        yield c


@pytest.fixture()
def auth():
    """Admin basic-auth tuple for protected routes."""
    return (settings.admin_user, settings.admin_password)


# --- Helpers for tests --------------------------------------------------------

@pytest.fixture()
def db_sync():
    """A synchronous session (same temp DB)."""
    return SessionLocal()