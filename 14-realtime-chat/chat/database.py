"""Database setup for the chat application.

Uses a sync SQLAlchemy engine + SQLite. A sync engine is used deliberately:
sqlite3 is single-writer and the sync API avoids threading/event-loop surprises
in the tiny uvicorn worker we target, while staying simple and portable across
the constraint stack. If an async driver (aiosqlite) is available it could be
swapped in transparently by changing ``create_engine`` to ``create_async_engine``
and switching the session factory to ``async_sessionmaker``.
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

# Resolve the SQLite database file relative to the package directory so the
# file survives a server restart in the intended location.
_BASE_DIR = Path(__file__).resolve().parent.parent
DATABASE_URL = f"sqlite:///{(_BASE_DIR / 'chat.db').as_posix()}"

# ``check_same_thread=False`` is required when a sync engine is used from
# multiple threads (uvicorn can run endpoints across a threadpool).
ENGINE: Engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False,
)

SessionLocal = sessionmaker(bind=ENGINE, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    """Abstract base for all ORM models."""


def init_db() -> None:
    """Create all tables that do not yet exist. Idempotent."""
    from chat import models  # noqa: F401  (register models on Base.metadata)

    Base.metadata.create_all(bind=ENGINE)


def get_session() -> Session:
    """Provide a request-scoped DB session (FastAPI dependency)."""
    session: Session = SessionLocal()
    try:
        yield session
    finally:
        session.close()