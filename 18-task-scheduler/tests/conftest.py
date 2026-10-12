"""Shared fixtures: isolated in-memory store + fresh queues per test."""

from __future__ import annotations

import os
from collections.abc import Generator

import pytest

os.environ["SCHEDULER_DB"] = ":memory:"

from scheduler.config import reset_config  # noqa: E402
from scheduler.queue import reset_ready_queue  # noqa: E402
import scheduler.store as store_mod  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_env():
    """Resets config, store and ready-queue before every test for isolation."""
    reset_config()
    reset_ready_queue()
    yield


@pytest.fixture()
def store():
    """A session to a fresh in-memory store (tables created)."""
    session = store_mod.init_store(":memory:")
    yield session
    session.close()


@pytest.fixture()
def client():
    """TestClient with auto-started workers (small pool) on an in-memory store."""
    from fastapi.testclient import TestClient

    from scheduler.main import create_app

    app = create_app(workers=1, auto_start=True)
    with TestClient(app) as c:
        yield c