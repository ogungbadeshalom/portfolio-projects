"""SQLAlchemy engine and session helpers.

Engine creation is isolated here so that both the FastAPI app (which needs an
async session per request) and the sync Click CLI share one database file
without pulling SQLAlchemy wiring into every module.
"""

from __future__ import annotations

from typing import AsyncIterator, Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from newsletter.models import Base
from newsletter.config import settings


def _async_url(db_url: str) -> str:
    """Translate a sqlite:// URL into the sqlite+aiosqlite form the async engine
    needs; leave any non-sqlite (e.g. postgres) URL untouched."""
    if db_url.startswith("sqlite:///"):
        return db_url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
    if db_url.startswith("sqlite://"):
        return db_url.replace("sqlite://", "sqlite+aiosqlite://", 1)
    return db_url


async_engine = create_async_engine(_async_url(settings.db_url), echo=False)
AsyncSessionLocal = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

# Synchronous engine/sessionmaker for the CLI (SQLite file sharing is safe).
_engine = create_engine(settings.db_url, echo=False)
SessionLocal = sessionmaker(bind=_engine, class_=Session, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding an :class:`AsyncSession` and closing it after
    the request.

    This is a plain async generator (not wrapped in ``@asynccontextmanager``)
    because FastAPI recognises plain async generators as generator dependencies
    and manages their lifetime itself. Committing is left to the caller; sessions
    are never committed implicitly.
    """
    async with AsyncSessionLocal() as session:
        yield session


def get_sync_session() -> Iterator[Session]:
    """Context manager yielding a synchronous session for the CLI."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def init_db() -> None:
    """Create all tables. Sync-safe and idempotent (used by CLI and app startup).

    Using the blocking engine here (rather than async) keeps startup simple and
    portable; SQLite is fast enough that blocking DDL is fine.
    """
    Base.metadata.create_all(bind=_engine)


async def ainit_db() -> None:
    """Async variant used at FastAPI lifespan startup."""
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)