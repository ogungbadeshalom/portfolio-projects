"""Usage metering + logging.

Every proxied request is logged to ``usage_logs`` (tenant, endpoint, method,
status, latency). Logging is *batched*: rows are enqueued and flushed on an
interval or when the buffer is full, so the request hot path does not pay for
a DB write per request. ``flush_now`` is exposed so the webhook path / tests
can force a flush deterministically.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from gateway.config import settings
from gateway.database import get_session_factory
from gateway.models import UsageLog

logger = logging.getLogger(__name__)


class UsageBatcher:
    """Background-flushing queue of usage rows."""

    def __init__(
        self,
        batch_interval: float | None = None,
        max_rows: Optional[int] = None,
        start: bool = True,
    ) -> None:
        self._interval = batch_interval if batch_interval is not None else settings.usage_batch_interval_seconds
        self._max_rows = max_rows or settings.usage_batch_max_rows
        self._queue: "queue.Queue[Optional[Dict[str, Any]]]" = queue.Queue()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._enqueued = 0
        if start:
            self.start()

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="usage-batcher", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            self.flush_now()
            self._stop.wait(self._interval)

    def log(self, tenant_id: int, endpoint: str, method: str, status_code: int, latency_ms: Optional[int]) -> None:
        """Enqueue a usage row (never blocks the request thread)."""
        self._queue.put(
            {
                "tenant_id": tenant_id,
                "endpoint": endpoint,
                "method": method,
                "status_code": status_code,
                "latency_ms": latency_ms,
                "timestamp": datetime.now(timezone.utc),
            }
        )
        self._enqueued += 1

    def flush_now(self, max_rows: Optional[int] = None) -> int:
        """Drain the queue into the DB; return the number of rows written."""
        cap = max_rows or self._max_rows
        rows: List[Dict[str, Any]] = []
        while len(rows) < cap:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
            if item is None:
                continue
            rows.append(item)

        if not rows:
            return 0
        try:
            db: Session = get_session_factory()()
            try:
                db.bulk_insert_mappings(UsageLog, rows)
                db.commit()
            finally:
                db.close()
        except Exception:  # noqa: BLE001 - never let a logger crash the app
            logger.exception("Failed to flush %d usage rows", len(rows))
            return 0
        return len(rows)

    def close(self) -> None:
        self._stop.set()
        self.flush_now()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None


# Module-level singleton bound to the app's DB.
_batcher: Optional[UsageBatcher] = None


def get_batcher() -> UsageBatcher:
    global _batcher
    if _batcher is None:
        _batcher = UsageBatcher()
    return _batcher


def reset_batcher() -> None:
    """Shut down and drop the singleton (used by tests)."""
    global _batcher
    if _batcher is not None:
        _batcher.close()
    _batcher = None


def log_usage(tenant_id: int, endpoint: str, method: str, status_code: int, latency_ms: Optional[int] = None) -> None:
    """Enqueue a usage record via the singleton batcher."""
    get_batcher().log(tenant_id, endpoint, method, status_code, latency_ms)


def flush_now() -> int:
    """Force the singleton batcher to write pending rows (used by tests/CLI)."""
    if _batcher is None:
        return 0
    return _batcher.flush_now()


# --------------------------------------------------------------------------- #
# Query helpers (used by GET /api/usage and the dashboard)
# --------------------------------------------------------------------------- #
def usage_stats(db: Session, tenant_id: int) -> Dict[str, Any]:
    """Aggregate usage for one tenant: total, last 24h, error rate."""
    total = _count(db, tenant_id)
    last_24h = _since(db, tenant_id, hours=24)
    errors = (
        db.query(func.count(UsageLog.id))
        .filter(UsageLog.tenant_id == tenant_id)
        .filter(UsageLog.status_code >= 400)
        .scalar()
        or 0
    )
    return {
        "tenant_id": tenant_id,
        "total_requests": total,
        "last_24h": last_24h,
        "error_requests": errors,
    }


def _count(db: Session, tenant_id: int) -> int:
    return int(db.query(func.count(UsageLog.id)).filter(UsageLog.tenant_id == tenant_id).scalar() or 0)


def _since(db: Session, tenant_id: int, hours: int) -> int:
    from datetime import timedelta

    threshold = datetime.now(timezone.utc) - timedelta(hours=hours)
    return int(
        db.query(func.count(UsageLog.id))
        .filter(UsageLog.tenant_id == tenant_id)
        .filter(UsageLog.timestamp >= threshold)
        .scalar()
        or 0
    )


def endpoint_breakdown(db: Session, tenant_id: int, limit: int = 20) -> List[Dict[str, Any]]:
    """Top endpoints (by request count) for one tenant."""
    rows = (
        db.query(UsageLog.endpoint, UsageLog.method, func.count(UsageLog.id).label("count"))
        .filter(UsageLog.tenant_id == tenant_id)
        .group_by(UsageLog.endpoint, UsageLog.method)
        .order_by(func.count(UsageLog.id).desc())
        .limit(limit)
        .all()
    )
    return [{"endpoint": e, "method": m, "count": int(c)} for e, m, c in rows]