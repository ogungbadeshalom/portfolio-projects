"""Thread-safe SQLite store for the analytics pipeline.

A single ``sqlite3`` connection is shared process-wide and serialized with a
``threading.RLock``. This is safe for the multi-threaded lifecycle here — the
ingest flusher (background thread), FastAPI request handlers, the WebSocket
broadcaster and tests all hit the same connection — and it avoids the classic
pitfall where two connections to an in-memory database each get their own empty
private DB.

``:memory:`` (the default) is backed by a disposable temp file so WAL-style
concurrent readers/writers over a single lock behave identically to a real
file store; file-backed databases use regular SQLite journaling with WAL.
"""

from __future__ import annotations

import sqlite3
import tempfile
import threading
from pathlib import Path
from typing import Any, Iterable, List, Mapping, Optional, Sequence

from analytics.config import get_settings
from analytics.schema import apply_schema


class Store:
    """Lock-guarded wrapper around a single sqlite connection."""

    def __init__(self, database_path: str | Path | None = None) -> None:
        settings = get_settings()
        path = database_path if database_path is not None else settings.default_db_path
        self._path = path
        self.name = str(path)
        self._memfile: str | None = None

        if str(path) == ":memory:":
            # Disposable temp file -> a real sharable DB, kept for process life.
            tmp = tempfile.NamedTemporaryFile(suffix=".analytics.db", delete=False)
            tmp.close()
            self._memfile = tmp.name
            target = self._memfile
            self.name = ":memory:"
        else:
            target = str(path)
            parent = Path(path).parent
            if str(parent) not in (".", "") and not parent.exists():
                Path(path).parent.mkdir(parents=True, exist_ok=True)

        # check_same_thread=False is safe because every access goes through the
        # RLock below; even WAL makes cross-thread connections fine, but a single
        # connection + lock keeps in-memory semantics identical to file mode.
        self.conn = sqlite3.connect(target, check_same_thread=False, timeout=30.0)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        try:
            if str(path) != ":memory:":
                self.conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.Error:
            pass
        self._lock = threading.RLock()
        apply_schema(self.conn)

    # -- introspection ----------------------------------------------------
    @property
    def db_path(self) -> str:
        return self._memfile or self.name

    # -- execution (all serialized) --------------------------------------
    def execute(self, sql: str, params: Sequence[Any] | Mapping[str, Any] = ()):
        with self._lock:
            cur = self.conn.execute(sql, params)
            self.conn.commit()
            return cur

    def executemany(self, sql: str, seq: Iterable[Sequence[Any]]):
        with self._lock:
            cur = self.conn.executemany(sql, seq)
            self.conn.commit()
            return cur

    def query(self, sql: str, params: Sequence[Any] | Mapping[str, Any] = ()) -> List[sqlite3.Row]:
        with self._lock:
            cur = self.conn.execute(sql, params)
            return list(cur.fetchall())

    def query_one(self, sql: str, params: Sequence[Any] | Mapping[str, Any] = ()) -> Optional[sqlite3.Row]:
        with self._lock:
            cur = self.conn.execute(sql, params)
            return cur.fetchone()

    def scalar(self, sql: str, params: Sequence[Any] | Mapping[str, Any] = ()) -> Any:
        with self._lock:
            cur = self.conn.execute(sql, params)
            row = cur.fetchone()
            return row[0] if row is not None else None

    def close(self) -> None:
        with self._lock:
            self.conn.close()
        if self._memfile:
            try:
                Path(self._memfile).unlink(missing_ok=True)
            except OSError:
                pass


#: Process-wide lazily-created store.
_store: Store | None = None
_store_lock = threading.Lock()


def get_store() -> Store:
    """Return the shared process store, creating it on first use."""
    global _store
    if _store is None:
        return ensure_store()
    return _store


def ensure_store(database_path: str | Path | None = None) -> Store:
    """Create/replace the shared process store against ``database_path``."""
    global _store
    with _store_lock:
        # Re-read settings so an explicit path change is honoured.
        if database_path is not None:
            from analytics.config import reset_settings

            reset_settings()
            settings = get_settings()
        if _store is not None:
            _store.close()
        _store = Store(database_path)
        return _store


def reset_store() -> None:
    """Close and drop the shared store (used by tests for isolation)."""
    global _store
    with _store_lock:
        if _store is not None:
            _store.close()
            _store = None


__all__ = ["Store", "get_store", "ensure_store", "reset_store"]