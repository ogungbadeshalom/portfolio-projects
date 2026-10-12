"""Async SQLAlchemy engine, session factory, and helper accessors.

SQLite persistence is provided by ``aiosqlite``. All access is async so the
event loop never blocks on database work. A single module-level engine is
created lazily so it can also be used from the Click CLI (which runs its own
asyncio loop) and from tests (which override the DB URL via ``init_db``).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .models import Base, CapturedRequest

# Default location next to this package: webtrap/webtrap.db
DEFAULT_DB_PATH = Path(__file__).resolve().parent / "webtrap.db"


def _default_url() -> str:
    override = os.environ.get("WEBTRAP_DB_URL")
    if override:
        return override
    return f"sqlite+aiosqlite:///{DEFAULT_DB_PATH.as_posix()}"


_engine: Optional[AsyncEngine] = None
_session_factory: Optional[async_sessionmaker[AsyncSession]] = None


def init_db(url: Optional[str] = None) -> AsyncEngine:
    """Build (or rebuild) the engine against ``url`` and run metadata create.

    Calling again with a different URL is only meaningful before any sessions
    are opened; tests replace the default SQLite file with an in-memory one.
    """
    global _engine, _session_factory
    url = url or _default_url()

    if url.startswith("sqlite") and url not in ("sqlite://", "sqlite:///:memory:"):
        # Ensure parent directory exists for file-backed SQLite URLs.
        url_path = url.split("///", 1)[-1]
        if url_path:
            parent = Path(url_path).parent
            parent.mkdir(parents=True, exist_ok=True)

    kwargs: Dict[str, Any] = {}
    if "sqlite" in url and (":memory:" in url or url == "sqlite://"):
        # One shared in-memory DB across all engine connections so a single
        # `:memory:` URL behaves like a real file for tests / embedded runs.
        from sqlalchemy.pool import StaticPool

        kwargs = {
            "poolclass": StaticPool,
            "connect_args": {"check_same_thread": False},
        }

    _engine = create_async_engine(url, echo=False, **kwargs)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def get_engine() -> AsyncEngine:
    if _engine is None:
        init_db()
    assert _engine is not None
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        init_db()
    assert _session_factory is not None
    return _session_factory


def session_factory() -> async_sessionmaker[AsyncSession]:
    return get_session_factory()


async def create_tables() -> None:
    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db():
    """FastAPI dependency yielding an AsyncSession, closing it afterwards."""
    async with get_session_factory()() as session:
        yield session


# --------------------------------------------------------------------------- #
# Read helpers shared by the web UI, API, and CLI.
# --------------------------------------------------------------------------- #


async def list_requests(
    session: AsyncSession, limit: int = 100, offset: int = 0
) -> List[CapturedRequest]:
    stmt = (
        select(CapturedRequest)
        .order_by(CapturedRequest.id.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def count_requests(session: AsyncSession) -> int:
    stmt = select(CapturedRequest)
    result = await session.execute(stmt)
    return len(result.scalars().all())


async def get_request(session: AsyncSession, request_id: int) -> Optional[CapturedRequest]:
    stmt = select(CapturedRequest).where(CapturedRequest.id == request_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def delete_request(session: AsyncSession, request_id: int) -> bool:
    obj = await get_request(session, request_id)
    if obj is None:
        return False
    await session.delete(obj)
    await session.commit()
    return True