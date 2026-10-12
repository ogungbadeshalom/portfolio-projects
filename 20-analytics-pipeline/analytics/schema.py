"""OLAP schema: DDL + materialized-style rollup tables.

The canonical store is SQLite (chosen because DuckDB/ClickHouse are optional
deps in this environment). SQLite is a row store, so the "columnar" story here
is:

* a wide ``events`` table with dedicated, indexed columns for the fields we
  filter/group by most (``ts``, ``event_name``, ``user_id``, ``url``);
* pre-aggregated rollup tables (``events_hourly`` / ``events_daily``) that the
  ingester maintains during batch flush — the SQLite stand-in for ClickHouse
  materialized views. Dashboard counters read these instead of re-scanning
  raw events.

Timestamps are stored as Unix seconds (UTC) under ``ts`` — a single comparable
integer — while ``ts_iso`` keeps the original ISO string for display. Date
range queries are plain ``ts BETWEEN ? AND ?``, fully parameterized.

All DDL here is idempotent and executed by :func:`apply_schema`.
"""

from __future__ import annotations

from typing import List

SCHEMA_STATEMENTS: List[str] = [
    # Events (facts). Properties are kept as flexible JSON.
    """
    CREATE TABLE IF NOT EXISTS events (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        event_name  TEXT    NOT NULL,
        user_id     TEXT    NOT NULL,
        session_id  TEXT,
        ts          INTEGER NOT NULL,            -- unix seconds, UTC
        ts_iso      TEXT    NOT NULL,            -- ISO-8601 UTC for display
        url         TEXT,
        referrer    TEXT,
        ip_anon     TEXT,                        -- anonymized (last octet zeroed)
        properties  TEXT    NOT NULL DEFAULT '{}'
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_events_ts ON events (ts)",
    "CREATE INDEX IF NOT EXISTS idx_events_user ON events (user_id, ts)",
    "CREATE INDEX IF NOT EXISTS idx_events_name ON events (event_name, ts)",
    # Pre-aggregated counts by hour — the "materialized view" for counters.
    """
    CREATE TABLE IF NOT EXISTS events_hourly (
        bucket      INTEGER NOT NULL,            -- unix seconds of the hour start
        event_name  TEXT    NOT NULL,
        cnt         INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (bucket, event_name)
    )
    """,
    # Pre-aggregated counts by day — used by the 24h / cohort views.
    """
    CREATE TABLE IF NOT EXISTS events_daily (
        bucket      INTEGER NOT NULL,            -- unix seconds of the day start (UTC)
        event_name  TEXT    NOT NULL,
        cnt         INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (bucket, event_name)
    )
    """,
]


def apply_schema(conn) -> None:
    """Apply all DDL statements to ``conn`` (idempotent; caller owns conn)."""
    for statement in SCHEMA_STATEMENTS:
        conn.execute(statement)
    conn.commit()


__all__ = ["SCHEMA_STATEMENTS", "apply_schema"]