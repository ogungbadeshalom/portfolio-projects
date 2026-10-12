"""Metadata persistence for uploaded files and in-progress multipart uploads.

The heavy bytes live on disk in ``storage/``; this module keeps a trivial
SQLite index mapping hashes to metadata and tracking open multipart uploads.
Using the stdlib :mod:`sqlite3` keeps the service dependency-free.

Every operation opens a fresh connection and **closes it** via a context
manager so no file handle lingers (important on Windows, where an open SQLite
connection locks the database file and blocks directory cleanup).
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from pydantic import BaseModel, ConfigDict, Field

from upload.config import settings


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class FileRecord(BaseModel):
    """Metadata for one stored (deduplicated) file."""

    model_config = ConfigDict(extra="forbid")

    hash: str
    filename: str
    size: int
    mime: str
    created_at: str = Field(default_factory=_now_iso)


class PartRecord(BaseModel):
    """One part of an in-progress multipart upload."""

    part_number: int
    size: int


class MultipartUpload(BaseModel):
    """An in-progress multipart upload."""

    model_config = ConfigDict(extra="forbid")

    upload_id: str
    filename: str
    parts: list[PartRecord] = Field(default_factory=list)
    created_at: str = Field(default_factory=_now_iso)


class _MetadataDB:
    """A small synchronous SQLite store, guarded by a per-process lock."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path
        self._lock = threading.Lock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def _session(self) -> Iterator[sqlite3.Connection]:
        """Yield an open connection, guaranteeing commit & close at the end."""
        conn = self._connect()
        try:
            with self._lock:
                yield conn
                conn.commit()
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._session() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS files (
                    hash TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    size INTEGER NOT NULL,
                    mime TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS uploads (
                    upload_id TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    parts_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

    # ---- files ----
    def insert_file(self, rec: FileRecord) -> None:
        with self._session() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO files VALUES (?, ?, ?, ?, ?)",
                (rec.hash, rec.filename, rec.size, rec.mime, rec.created_at),
            )

    def get_file(self, hash_: str) -> FileRecord | None:
        with self._session() as conn:
            row = conn.execute(
                "SELECT * FROM files WHERE hash = ?", (hash_,)
            ).fetchone()
        if row is None:
            return None
        return FileRecord(**dict(row))

    def delete_file(self, hash_: str) -> bool:
        with self._session() as conn:
            cur = conn.execute("DELETE FROM files WHERE hash = ?", (hash_,))
            return cur.rowcount > 0

    def list_files(self) -> list[FileRecord]:
        with self._session() as conn:
            rows = conn.execute("SELECT * FROM files ORDER BY created_at").fetchall()
        return [FileRecord(**dict(r)) for r in rows]

    # ---- multipart ----
    def upsert_upload(self, upload: MultipartUpload) -> None:
        parts_json = json.dumps([p.model_dump() for p in upload.parts])
        with self._session() as conn:
            conn.execute(
                """INSERT INTO uploads (upload_id, filename, parts_json, created_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(upload_id) DO UPDATE SET
                       parts_json = excluded.parts_json,
                       filename = excluded.filename""",
                (upload.upload_id, upload.filename, parts_json, upload.created_at),
            )

    def get_upload(self, upload_id: str) -> MultipartUpload | None:
        with self._session() as conn:
            row = conn.execute(
                "SELECT * FROM uploads WHERE upload_id = ?", (upload_id,)
            ).fetchone()
        if row is None:
            return None
        parts = [PartRecord(**p) for p in json.loads(row["parts_json"])]
        return MultipartUpload(
            upload_id=row["upload_id"],
            filename=row["filename"],
            parts=parts,
            created_at=row["created_at"],
        )

    def delete_upload(self, upload_id: str) -> bool:
        with self._session() as conn:
            cur = conn.execute("DELETE FROM uploads WHERE upload_id = ?", (upload_id,))
            return cur.rowcount > 0


def _default_db_path() -> Path:
    return settings.storage_dir / "metadata.db"


_metadata: Any = _MetadataDB(_default_db_path())


def get_metadata() -> _MetadataDB:
    """Return the process-wide metadata store (override in tests)."""
    return _metadata


def set_metadata(store: _MetadataDB) -> None:
    """Point the store at a custom instance (used by the test-suite)."""
    global _metadata  # noqa: PLW0603
    _metadata = store