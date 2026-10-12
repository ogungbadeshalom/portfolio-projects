"""Shared fixtures: an isolated in-memory store and TestClient per test."""

from __future__ import annotations

import analytics.store as st
import pytest


@pytest.fixture(autouse=True)
def _isolate():
    """Always start/end with a fresh process store so tests never share rows."""
    st.reset_store()
    yield
    st.reset_store()


@pytest.fixture()
def store():
    """A standalone in-memory store (for pure query/unit tests, no app)."""
    s = st.ensure_store(":memory:")
    yield s
    st.reset_store()


@pytest.fixture()
def client():
    """A TestClient on its own in-memory store.

    ``batch=False`` leaves the real async flusher in charge; query tests call
    ``client.app.state.pipe.flush()`` on demand. The app's store is exposed as
    ``client.store`` so API-ingested data can be inspected directly.
    """
    from fastapi.testclient import TestClient

    from analytics.main import create_app

    store = st.ensure_store(":memory:")
    app = create_app(store=store, batch=False)
    with TestClient(app) as c:
        c.store = store
        yield c
    st.reset_store()