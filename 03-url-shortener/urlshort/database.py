"""Async SQLAlchemy engine and session management.

Exposes a module-level :data:`engine` bound to the configured database URL and
a :func:`get_db` FastAPI dependency that yields an async session per request.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from urlshort.config import settings
from urlshort.models import Base


def _ensure_sqlite_dir(database_url: str) -> None:
    """Create the parent directory of a SQLite database file, if any."""
    if not database_url.startswith("sqlite"):
        return
    rel = database_url.split("///", 1)[-1]
    # ``sqlite+aiosqlite:///:memory:`` -> rel == ``:memory:``, skip.
    if not rel or rel == ":" or rel.startswith(":memory"):
        return
    parent = Path(rel).parent
    parent.mkdir(parents=True, exist_ok=True)


_ensure_sqlite_dir(settings.database_url)


engine: AsyncEngine = create_async_engine(
    settings.database_url,
    echo=False,
    future=True,
)


SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def init_db() -> None:
    """Create tables and any missing database directory."""
    _ensure_sqlite_dir(settings.database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding an async session, rolling back on error."""
    async with SessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise