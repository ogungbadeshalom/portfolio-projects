"""Engine, session factory, and dependencies.

Kept as a tiny separate module so the FastAPI app, the usage batcher, and
tests can build and tear down the engine in one place. Uses the sync
SQLAlchemy API (SQLite by default; swap ``database_url`` for Postgres in
production).
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from gateway.config import settings
from gateway.models import Base


def make_engine(url: Optional[str] = None):
    url = url or settings.database_url
    kwargs = {}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(url, future=True, **kwargs)


def _default_engine():
    return make_engine()


_engine = None
_session_factory: Optional[sessionmaker] = None


def init_db(url: Optional[str] = None):
    """(Re)build the engine and session factory, then create tables."""
    global _engine, _session_factory
    _engine = make_engine(url)
    _session_factory = sessionmaker(bind=_engine, future=True, expire_on_commit=False)
    Base.metadata.create_all(_engine)
    return _engine


def get_engine():
    global _engine
    if _engine is None:
        init_db()
    return _engine


def get_session_factory() -> sessionmaker:
    global _session_factory
    if _session_factory is None:
        init_db()
    assert _session_factory is not None
    return _session_factory


def get_db():
    """FastAPI dependency yielding a Session (sync)."""
    db = get_session_factory()()
    try:
        yield db
    finally:
        db.close()


def dispose() -> None:
    """Close the global engine (tests call this between cases)."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None