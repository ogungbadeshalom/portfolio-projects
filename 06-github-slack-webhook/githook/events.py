"""Event persistence for the GitHub -> Slack notifier.

This module exposes a single ``EventStore`` class with a small interface
(``record()``, ``mark_delivered()``, ``mark_failed()``, ``recent()``,
``exists()``) that is backend-agnostic. Two implementations are provided:

* ``SqlAlchemyEventStore`` -- the primary backend, used whenever SQLAlchemy is
  importable (the default on this project's runtime, where SQLAlchemy 2.x is
  installed).
* ``SqliteEventStore`` -- a stdlib-only ``sqlite3`` fallback behind the exact
  same interface, used only if SQLAlchemy cannot be imported.

``EventStore`` is a convenience factory that picks the best available backend
based on imports, so the rest of the code never needs to know which one is in
use.
"""

from __future__ import annotations

import calendar
import contextlib
import json
import logging
import sqlite3
import threading
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Record type
# --------------------------------------------------------------------------- #
class EventRecord:
    """A single stored webhook event with its delivery/send status."""

    __slots__ = (
        "id",
        "delivery_id",
        "event_type",
        "payload",
        "status",
        "created_at",
        "processed_at",
    )

    def __init__(
        self,
        delivery_id: str,
        event_type: str,
        payload: Dict[str, Any],
        status: str = "received",
        id: Optional[int] = None,
        created_at: Optional[str] = None,
        processed_at: Optional[str] = None,
    ) -> None:
        self.id = id
        self.delivery_id = delivery_id
        self.event_type = event_type
        self.payload = payload
        self.status = status
        self.created_at = created_at or _now_iso()
        self.processed_at = processed_at

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "delivery_id": self.delivery_id,
            "event_type": self.event_type,
            "payload": self.payload,
            "status": self.status,
            "created_at": self.created_at,
            "processed_at": self.processed_at,
        }

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<EventRecord id={self.id} delivery_id={self.delivery_id!r} "
            f"type={self.event_type!r} status={self.status!r}>"
        )


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _epoch_iso(epoch: float) -> str:
    """Convert a unix-epoch float (from github payloads) to ISO-8601 UTC."""
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _iso_epoch(iso: str) -> float:
    """Convert an ISO-8601 timestamp to a unix-epoch float."""
    try:
        dt = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        return calendar.timegm(dt.timetuple())
    except ValueError:
        return 0.0


# --------------------------------------------------------------------------- #
# Base interface
# --------------------------------------------------------------------------- #
class EventStore(ABC):
    """Abstract persistence contract used by the rest of the app."""

    @abstractmethod
    def record(self, delivery_id: str, event_type: str, payload: Dict[str, Any]) -> EventRecord:
        """Insert a new event. Raises ``DuplicateDeliveryError`` if the
        ``delivery_id`` already exists (guards idempotency)."""

    @abstractmethod
    def exists(self, delivery_id: str) -> bool:
        """Return True if the delivery has already been stored."""

    @abstractmethod
    def mark_delivered(self, delivery_id: str) -> None:
        """Mark the event as successfully delivered to Slack."""

    @abstractmethod
    def mark_failed(self, delivery_id: str, attempts: int) -> None:
        """Mark the event as failed after exhausting retries."""

    @abstractmethod
    def recent(self, limit: int = 100) -> List[EventRecord]:
        """Return the most recent events, newest first."""
        raise NotImplementedError


class DuplicateDeliveryError(Exception):
    """Raised when an already-processed delivery id is submitted again."""


def event_store(database_url: Optional[str] = None) -> EventStore:
    """Pick the best available backend and return a configured store.

    Prefers SQLAlchemy; falls back to a stdlib sqlite3 store if SQLAlchemy is
    not importable on this runtime.
    """
    url = database_url or "sqlite:///githook.db"
    try:
        import sqlalchemy  # noqa: F401

        return SqlAlchemyEventStore(url)
    except Exception as exc:  # pragma: no cover - rare runtime without SQLAlchemy
        logger.warning("SQLAlchemy unavailable (%s); using stdlib sqlite3 store.", exc)
        return SqliteEventStore(url)


# --------------------------------------------------------------------------- #
# SQLAlchemy backend
# --------------------------------------------------------------------------- #
class SqlAlchemyEventStore(EventStore):
    """Persistence backed by SQLAlchemy + SQLite."""

    def __init__(self, url: str) -> None:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        self._url = url
        self._engine = create_engine(url, future=True)
        self._Session = sessionmaker(bind=self._engine, future=True)

        from sqlalchemy import (
            DateTime,
            Integer,
            String,
            Text,
            Column,
            Index,
        )
        from sqlalchemy.ext.declarative import declarative_base

        Base = declarative_base()

        class Event(Base):  # type: ignore[misc, valid-type]
            __tablename__ = "events"
            id = Column(Integer, primary_key=True, autoincrement=True)
            delivery_id = Column(String(128), unique=True, nullable=False)
            event_type = Column(String(64), nullable=False)
            payload = Column(Text, nullable=False)
            status = Column(String(32), nullable=False, default="received")
            created_at = Column(String(32), nullable=False)
            processed_at = Column(String(32), nullable=True)
            Index("ix_events_delivery_id", delivery_id, unique=True)

        self._Event = Event
        Base.metadata.create_all(self._engine)

    def record(self, delivery_id: str, event_type: str, payload: Dict[str, Any]) -> EventRecord:
        from sqlalchemy.exc import IntegrityError

        session = self._Session()
        try:
            ev = self._Event(
                delivery_id=delivery_id,
                event_type=event_type,
                payload=_json_dumps(payload),
                status="received",
                created_at=_now_iso(),
            )
            session.add(ev)
            session.commit()
            return EventRecord(
                id=ev.id,
                delivery_id=ev.delivery_id,
                event_type=ev.event_type,
                payload=_json_loads(ev.payload),
                status=ev.status,
                created_at=ev.created_at,
                processed_at=ev.processed_at,
            )
        except IntegrityError:
            session.rollback()
            raise DuplicateDeliveryError(delivery_id) from None
        finally:
            session.close()

    def exists(self, delivery_id: str) -> bool:
        session = self._Session()
        try:
            row = (
                session.query(self._Event)
                .filter(self._Event.delivery_id == delivery_id)
                .first()
            )
            return row is not None
        finally:
            session.close()

    def _update_status(self, delivery_id: str, status: str, processed_at: Optional[str]) -> None:
        session = self._Session()
        try:
            row = (
                session.query(self._Event)
                .filter(self._Event.delivery_id == delivery_id)
                .first()
            )
            if row is not None:
                row.status = status
                if processed_at is not None:
                    row.processed_at = processed_at
                session.commit()
        finally:
            session.close()

    def mark_delivered(self, delivery_id: str) -> None:
        self._update_status(delivery_id, "delivered", _now_iso())

    def mark_failed(self, delivery_id: str, attempts: int) -> None:
        self._update_status(delivery_id, "failed", _now_iso())

    def recent(self, limit: int = 100) -> List[EventRecord]:
        session = self._Session()
        try:
            rows = (
                session.query(self._Event)
                .order_by(self._Event.id.desc())
                .limit(limit)
                .all()
            )
            return [
                EventRecord(
                    id=r.id,
                    delivery_id=r.delivery_id,
                    event_type=r.event_type,
                    payload=_json_loads(r.payload),
                    status=r.status,
                    created_at=r.created_at,
                    processed_at=r.processed_at,
                )
                for r in rows
            ]
        finally:
            session.close()


# --------------------------------------------------------------------------- #
# stdlib sqlite3 backend
# --------------------------------------------------------------------------- #
class SqliteEventStore(EventStore):
    """Persistence backed entirely by the standard library ``sqlite3`` module.

    Mirrors the ``SqlAlchemyEventStore`` behaviour behind the same interface;
    used only when SQLAlchemy is unavailable.
    """

    def __init__(self, url: str) -> None:
        path = _sqlite_path_from_url(url)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                delivery_id TEXT NOT NULL UNIQUE,
                event_type TEXT NOT NULL,
                payload TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'received',
                created_at TEXT NOT NULL,
                processed_at TEXT
            )
            """
        )
        self._conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_events_delivery_id "
            "ON events (delivery_id)"
        )
        self._conn.commit()

    def _execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur

    def record(self, delivery_id: str, event_type: str, payload: Dict[str, Any]) -> EventRecord:
        try:
            cur = self._execute(
                "INSERT INTO events (delivery_id, event_type, payload, status, "
                "created_at) VALUES (?, ?, ?, 'received', ?)",
                (delivery_id, event_type, _json_dumps(payload), _now_iso()),
            )
            rid = cur.lastrowid
        except sqlite3.IntegrityError:
            raise DuplicateDeliveryError(delivery_id) from None
        return EventRecord(
            id=rid,
            delivery_id=delivery_id,
            event_type=event_type,
            payload=payload,
            status="received",
            created_at=_now_iso(),
        )

    def exists(self, delivery_id: str) -> bool:
        cur = self._execute("SELECT 1 FROM events WHERE delivery_id = ?", (delivery_id,))
        return cur.fetchone() is not None

    def _update_status(self, delivery_id: str, status: str) -> None:
        self._execute(
            "UPDATE events SET status = ?, processed_at = ? WHERE delivery_id = ?",
            (status, _now_iso(), delivery_id),
        )

    def mark_delivered(self, delivery_id: str) -> None:
        self._update_status(delivery_id, "delivered")

    def mark_failed(self, delivery_id: str, attempts: int) -> None:
        self._update_status(delivery_id, "failed")

    def recent(self, limit: int = 100) -> List[EventRecord]:
        cur = self._execute(
            "SELECT id, delivery_id, event_type, payload, status, created_at, "
            "processed_at FROM events ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        rows = cur.fetchall()
        return [
            EventRecord(
                id=r[0],
                delivery_id=r[1],
                event_type=r[2],
                payload=_json_loads(r[3]),
                status=r[4],
                created_at=r[5],
                processed_at=r[6],
            )
            for r in rows
        ]


def _sqlite_path_from_url(url: str) -> Path:
    """Convert ``sqlite:///relative.db`` / ``sqlite:////abs/path.db`` to a Path."""
    prefix = "sqlite:///"
    if url.startswith(prefix):
        rest = url[len(prefix):]
        return Path(rest)
    return Path("githook.db")


def _json_dumps(obj: Any) -> str:
    return json.dumps(obj, separators=(",", ":"))


def _json_loads(text: str) -> Any:
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        logger.error("Stored event payload is corrupt; replacing with {}.")
        return {}