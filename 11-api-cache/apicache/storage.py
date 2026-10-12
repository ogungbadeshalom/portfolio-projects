"""Async SQLite storage backend for :mod:`apicache`.

Provides CRUD around the ``entries`` table plus tag-matching and expired-entry
accounting. Uses :mod:`aiosqlite` so every public method is ``async`` and can
live on the same event loop as the httpx calls it caches.

Schema (one row per cache entry)::

    key         TEXT PRIMARY KEY
    value_json  TEXT            -- JSON serialization of the payload
    expires_at  REAL            -- epoch seconds, or NULL for no expiry
    tags        TEXT            -- tags joined by ``TAG_DELIMITER``
    etag        TEXT            -- optional HTTP ETag from origin
    created_at  REAL            -- epoch seconds when written
"""
from __future__ import annotations

import hashlib
from typing import Any, AsyncIterator, Optional

import aiosqlite

from apicache.models import TAG_DELIMITER, CacheEntry, now as _now

_SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    key         TEXT PRIMARY KEY,
    value_json  TEXT NOT NULL,
    expires_at  REAL,
    tags        TEXT NOT NULL DEFAULT '',
    etag        TEXT,
    created_at  REAL NOT NULL
)
"""


class SQLiteStorage:
    """An asyncio-native SQLite cache store.

    Args:
        db_path: Path to the database file, or ``":memory:"``.
    """

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._conn: Optional[aiosqlite.Connection] = None

    async def open(self) -> None:
        """Open the connection and ensure the schema exists."""
        if self._conn is not None:
            return
        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute(_SCHEMA)
        await self._conn.commit()

    async def close(self) -> None:
        """Close the underlying connection, if open."""
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def _execute(self, sql: str, params: tuple[Any, ...] = ()) -> aiosqlite.Cursor:
        assert self._conn is not None
        cur = await self._conn.execute(sql, params)
        await self._conn.commit()
        return cur

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    async def get(self, key: str) -> CacheEntry | None:
        """Fetch one entry by key, or ``None`` if absent.

        Does **not** filter on expiry — callers apply TTL logic so they can
        count the entry as a miss while still knowing it existed.
        """
        cur = await self._execute("SELECT * FROM entries WHERE key = ?", (key,))
        row = await cur.fetchone()
        if row is None:
            return None
        return CacheEntry.from_row(tuple(row))

    async def set(self, entry: CacheEntry) -> None:
        """Upsert a cache entry (replaces any existing row with the same key)."""
        await self._execute(
            """INSERT INTO entries (key, value_json, expires_at, tags, etag, created_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET
                   value_json = excluded.value_json,
                   expires_at = excluded.expires_at,
                   tags = excluded.tags,
                   etag = excluded.etag,
                   created_at = excluded.created_at""",
            (
                entry.key,
                entry.value_bytes().decode("utf-8"),
                entry.expires_at,
                entry.tags_delimited(),
                entry.etag,
                entry.created_at,
            ),
        )

    async def delete(self, key: str) -> bool:
        """Remove one key. Returns ``True`` if a row was deleted."""
        cur = await self._execute("DELETE FROM entries WHERE key = ?", (key,))
        return cur.rowcount > 0

    async def list_keys(self) -> list[str]:
        """Return every stored key."""
        cur = await self._execute("SELECT key FROM entries ORDER BY key")
        rows = await cur.fetchall()
        return [row["key"] for row in rows]

    async def get_entries(self) -> list[CacheEntry]:
        """Return all stored entries (used by the CLI's ``inspect``)."""
        cur = await self._execute(
            "SELECT * FROM entries ORDER BY created_at DESC"
        )
        rows = await cur.fetchall()
        return [CacheEntry.from_row(tuple(r)) for r in rows]

    async def clear(self) -> int:
        """Delete every entry. Returns the number of removed rows."""
        cur = await self._execute("DELETE FROM entries")
        return cur.rowcount

    async def count(self) -> int:
        """Total stored rows."""
        cur = await self._execute("SELECT COUNT(*) AS c FROM entries")
        row = await cur.fetchone()
        return int(row["c"])

    # ------------------------------------------------------------------
    # Expiry / tags
    # ------------------------------------------------------------------
    async def cleanup_expired(self, at: Optional[float] = None) -> int:
        """Delete rows whose ``expires_at`` is at/past ``at`` (default now)."""
        at = _now() if at is None else at
        cur = await self._execute(
            "DELETE FROM entries WHERE expires_at IS NOT NULL AND expires_at <= ?",
            (at,),
        )
        return cur.rowcount

    async def count_expired(self, at: Optional[float] = None) -> int:
        """Count rows currently past their expiry (not yet cleaned up)."""
        at = _now() if at is None else at
        cur = await self._execute(
            "SELECT COUNT(*) AS c FROM entries "
            "WHERE expires_at IS NOT NULL AND expires_at <= ?",
            (at,),
        )
        row = await cur.fetchone()
        return int(row["c"])

    async def delete_by_tag(self, tag: str) -> int:
        """Delete every entry carrying the exact ``tag``. Returns row count."""
        # Match any entry whose tag-delimited string contains ``tag`` as a
        # standalone token (avoiding ``user-1`` matching ``user-12``).
        token = _escape_like(tag)
        pattern = f"%{TAG_DELIMITER}{token}{TAG_DELIMITER}%"
        cur = await self._execute(
            "DELETE FROM entries WHERE tags LIKE ? ESCAPE '\\' "
            "OR tags LIKE ? ESCAPE '\\' OR tags LIKE ? ESCAPE '\\' OR tags = ?",
            (pattern, f"{token}{TAG_DELIMITER}%", f"%{TAG_DELIMITER}{token}", tag),
        )
        return cur.rowcount

    async def iter_keys_tagged(self, tag: str) -> AsyncIterator[str]:
        """Yield keys whose entries carry ``tag`` (used for stats/audits)."""
        rows = await self.get_entries()
        for entry in rows:
            if tag in entry.tags:
                yield entry.key


def _escape_like(value: str) -> str:
    """Escape LIKE wildcards so a tag is matched literally."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def content_hash(key: str, value: Any) -> str:
    """A stable hash for an entry's key+value (used to derive an ETag)."""
    digest = hashlib.blake2b()
    digest.update(key.encode("utf-8"))
    digest.update(repr(value).encode("utf-8"))
    return digest.hexdigest()