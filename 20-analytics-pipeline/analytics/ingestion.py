"""Async event ingestion: a bounded queue drained by a background flusher.

The ingestion endpoint is non-blocking: a POST to ``/api/track`` validates the
event, anonymizes the IP, and pushes it onto an :class:`asyncio.Queue`. A single
flusher task drains the queue in batches, writing to the OLAP store either every
``flush_interval_seconds`` or every ``batch_size`` events — whichever comes
first — and updates the pre-aggregated rollups (SQLite materialized views).

The flusher runs inside the FastAPI lifespan so it is cancelled *and flush()ed*
on shutdown, guaranteeing no queued event is dropped. See :class:`IngestPipe`.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, List, Optional

from analytics.config import get_settings
from analytics.models import Event
from analytics.store import Store

logger = logging.getLogger(__name__)

_INSERT_EVENT = """
    INSERT INTO events (event_name, user_id, session_id, ts, ts_iso, url,
                        referrer, ip_anon, properties)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
"""
_UPSERT_HOURLY = """
    INSERT INTO events_hourly (bucket, event_name, cnt) VALUES (?, ?, ?)
    ON CONFLICT(bucket, event_name) DO UPDATE SET cnt = cnt + excluded.cnt
"""
_UPSERT_DAILY = """
    INSERT INTO events_daily (bucket, event_name, cnt) VALUES (?, ?, ?)
    ON CONFLICT(bucket, event_name) DO UPDATE SET cnt = cnt + excluded.cnt
"""


def _hour_bucket(unix_ts: int) -> int:
    return unix_ts - (unix_ts % 3600)


def _day_bucket(unix_ts: int) -> int:
    return unix_ts - (unix_ts % 86400)


def event_row(event: Event) -> tuple:
    """Flatten a validated Event into an insert tuple."""
    ts = event.unix_ts
    props = event.properties
    return (
        event.event,
        event.user_id,
        event.session_id,
        ts,
        event.ts_iso,
        props.get("url"),
        props.get("referrer"),
        event.ip,  # already anonymized by the caller
        json.dumps(props),
    )


class IngestPipe:
    """Co-ordinated event queue + background flusher.

    Usage (inside a FastAPI lifespan)::

        pipe = IngestPipe(store)
        flusher = asyncio.create_task(pipe.run())
        ...
        await pipe.enqueue(validated_event)
        ...
        await pipe.close()      # cancels + final flush

    ``asyncio.Queue`` is C-implemented and thread-safe only for the event loop;
    all calls to :meth:`enqueue` and :meth:`run` must happen on the same loop
    (the app's lifespan loop). SQLite writes are performed directly on that
    loop's thread through the shared lock-guarded :class:`Store`.
    """

    def __init__(self, store: Store, *, settings=None) -> None:
        self.store = store
        self.settings = settings or get_settings()
        self.queue: "asyncio.Queue[Event]" = asyncio.Queue(
            maxsize=self.settings.queue_maxsize
        )
        self._task: Optional[asyncio.Task] = None
        self._pending: List[tuple] = []
        self._closed = False

    @property
    def estimated_size(self) -> int:
        return self.queue.qsize() + len(self._pending)

    # -- lifecycle --------------------------------------------------------
    def start(self) -> "IngestPipe":
        self._task = asyncio.create_task(self._run())
        return self

    async def close(self) -> None:
        """Signal shutdown, then flush whatever is queued (no dropped events)."""
        if self._closed:
            return
        self._closed = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None
        # Drain anything still queued (flush() drains the queue itself).
        self.flush()

    # -- public API ---------------------------------------------------------
    async def enqueue(self, event: Event) -> None:
        """Push a validated, anonymized event onto the queue (non-blocking-ish)."""
        # If the queue is full we wait briefly for the flusher to drain, which
        # provides natural backpressure instead of unbounded memory growth.
        await self.queue.put(event)
        self.maybe_flush_for_batch_size()

    # -- internal ------------------------------------------------------------
    def maybe_flush_for_batch_size(self) -> None:
        if self.queue.qsize() >= self.settings.batch_size:
            while self.queue.qsize():
                try:
                    item = self.queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                self._pending.append(event_row(item))
            self.flush()

    async def _run(self) -> None:
        interval = self.settings.flush_interval_seconds
        while True:
            try:
                # Wait up to `interval` for the first event of a batch.
                item = await asyncio.wait_for(self.queue.get(), timeout=interval)
            except asyncio.TimeoutError:
                self.flush()
                continue
            except asyncio.CancelledError:
                raise
            self._pending.append(event_row(item))
            # Drain whatever else arrived in this window (up to batch_size).
            self.maybe_flush_for_batch_size()
            if len(self._pending) >= self.settings.batch_size:
                self.flush()
            else:
                # Small sleep so a tight burst still lands in one commit.
                if not self.queue.empty():
                    continue
                await asyncio.sleep(0)

    def flush(self) -> int:
        """Write all pending rows in one transaction; returns rows written.

        Any events still sitting in the queue are drained first so an explicit
        flush (tests, or shutdown) never leaves un-persisted events behind.
        """
        self._drain_queue()
        if not self._pending:
            return 0
        rows, self._pending = self._pending, []
        try:
            self.store.executemany(_INSERT_EVENT, rows)
            self._rollup(rows)
            return len(rows)
        except Exception:  # noqa: BLE001 - never let the flusher die
            logger.exception("flush failed; %d events kept in memory", len(rows))
            self._pending = rows + self._pending
            return 0

    def _drain_queue(self) -> None:
        while True:
            try:
                item = self.queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            self._pending.append(event_row(item))

    def _rollup(self, rows: List[tuple]) -> None:
        hourly: dict = {}
        daily: dict = {}
        for _e, _u, _s, ts, *_rest in rows:
            hb = _hour_bucket(ts)
            hourly[(hb, None)] = hourly.get((hb, None), 0) + 1
            db = _day_bucket(ts)
            daily[(db, None)] = daily.get((db, None), 0) + 1
        self.store.executemany(
            _UPSERT_HOURLY, [(b, "any", c) for (b, _n), c in hourly.items()]
        )
        self.store.executemany(
            _UPSERT_DAILY, [(b, "any", c) for (b, _n), c in daily.items()]
        )


__all__ = ["IngestPipe", "event_row"]