"""Shared fixtures for the apicache test-suite.

Each test gets a fresh in-memory :class:`APICache` so tests are isolated and
need no real SQLite file on disk.
"""
from __future__ import annotations

import pytest_asyncio

from apicache import APICache


@pytest_asyncio.fixture
async def cache():
    """A fresh in-memory :class:`APICache`, opened and closed per test."""
    c = APICache(":memory:")
    await c.open()
    try:
        yield c
    finally:
        await c.close()