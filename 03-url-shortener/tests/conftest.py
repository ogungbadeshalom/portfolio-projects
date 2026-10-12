"""Shared fixtures for the URL shortener test-suite.

Each test gets a fresh app backed by its own in-memory async SQLite database.
The ``get_db`` dependency is overridden so request handling uses the temp
engine/session rather than the global one.
"""
from __future__ import annotations

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from urlshort.database import get_db
from urlshort.main import create_app
from urlshort.models import Base


@pytest_asyncio.fixture
async def db_engine():
    """An isolated in-memory async SQLite engine with tables created."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def client(db_engine):
    """An ``httpx.AsyncClient`` wired to the app with the temp DB override."""
    SessionLocal = async_sessionmaker(
        bind=db_engine, class_=AsyncSession, expire_on_commit=False
    )

    async def override_get_db():
        async with SessionLocal() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c