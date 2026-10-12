"""Ingestion behaviour: validation, IP anonymization, async batching/flush."""

from __future__ import annotations

import asyncio
import json

import pytest
from pydantic import ValidationError

from analytics.ingestion import IngestPipe
from analytics.models import Event
from analytics.store import ensure_store


class TestEventValidation:
    def test_blank_user_rejected(self):
        with pytest.raises(ValidationError):
            Event(event="page_view", user_id=" ")

    def test_blank_event_rejected(self):
        with pytest.raises(ValidationError):
            Event(event="", user_id="u1")

    def test_unsupported_timestamp_rejected(self):
        with pytest.raises(ValidationError):
            Event(event="page_view", user_id="u1", timestamp=object())

    def test_naive_timestamp_assumed_utc(self):
        e = Event(event="page_view", user_id="u1", timestamp="2026-01-01T00:00:00")
        assert e.unix_ts == int(
            __import__("datetime").datetime(2026, 1, 1, tzinfo=__import__("datetime").timezone.utc).timestamp()
        )


class TestAnonymize:
    def test_ipv4_last_octet_zeroed(self):
        e = Event(event="page_view", user_id="u1", ip="203.0.113.42")
        anon = e.anonymize()
        assert anon.ip == "203.0.113.0"

    def test_missing_ip_touches_nothing(self):
        e = Event(event="page_view", user_id="u1")
        assert e.anonymize().ip is None


class TestBatchFlush:
    def test_asyncio_flusher_writes_in_background(self):
        """A running flusher drains the queue to the store without an explicit
        flush() call (the real ingestion path)."""
        store = ensure_store(":memory:")
        pipe = IngestPipe(store, settings=_small_settings(interval=0.05))
        asyncio.run(_flush_in_background(pipe, 5))
        store.close()

    def test_flush_writes_all_events(self):
        store = ensure_store(":memory:")
        pipe = IngestPipe(store, settings=_small_settings(interval=1000))
        asyncio.run(_enqueue(pipe, ["a", "b", "c"]))
        pipe.flush()
        assert store.scalar("SELECT COUNT(*) FROM events") == 3

    def test_flush_never_loses_on_empty(self):
        store = ensure_store(":memory:")
        pipe = IngestPipe(store, settings=_small_settings(interval=1000))
        assert pipe.flush() == 0  # no-op, no error

    def test_flush_updates_hourly_rollup(self):
        store = ensure_store(":memory:")
        pipe = IngestPipe(store, settings=_small_settings(interval=1000))
        asyncio.run(_enqueue(pipe, ["x", "x"]))
        pipe.flush()
        assert store.scalar("SELECT cnt FROM events_hourly "
                            "WHERE event_name='any'") == 2


def test_api_ip_is_anonymized(client):
    client.post("/api/track", json={"event": "page_view", "user_id": "u1",
                                    "ip": "203.0.113.42"})
    client.app.state.pipe.flush()
    row = client.app.state.store.query_one("SELECT ip_anon FROM events")
    assert row["ip_anon"] == "203.0.113.0"


def test_api_rejects_malformed(client):
    r = client.post("/api/track", json={"event": "x", "user_id": ""})
    assert r.status_code == 422


def test_api_batch_endpoint(client):
    events = [
        {"event": "page_view", "user_id": f"u{i}", "properties": {"url": "/p"}}
        for i in range(4)
    ]
    r = client.post("/api/track/batch", json=events)
    assert r.status_code == 200
    assert r.json()["queued"] == 4


# -- helpers ----------------------------------------------------------------
def _small_settings(interval=1000):
    class _S:
        queue_maxsize = 1000
        flush_interval_seconds = interval
        batch_size = 1000
        broadcast_interval_seconds = 1.0

    return _S()


async def _enqueue(pipe, names):
    for n in names:
        await pipe.enqueue(Event(event=n, user_id="u0"))


async def _flush_in_background(pipe, count):
    async def wait_for(pipe, count):
        store = pipe.store
        while store.scalar("SELECT COUNT(*) FROM events") < count:
            await asyncio.sleep(0.01)

    flusher = asyncio.create_task(pipe._run())
    waiter = asyncio.create_task(wait_for(pipe, count))
    for n in range(count):
        await pipe.enqueue(Event(event=f"e{n}", user_id="u0"))
    await asyncio.wait_for(waiter, timeout=3)
    flusher.cancel()
    try:
        await flusher
    except (asyncio.CancelledError, Exception):  # noqa: BLE001
        pass