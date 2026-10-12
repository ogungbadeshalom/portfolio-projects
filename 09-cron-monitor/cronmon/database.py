"""Database engine, session factory, and app-lifetime management.

The cron monitor uses a single SQLite database for all state (jobs, runs,
alerts). SQLite handles concurrent readers well and is fully in-process, so
the watchdog and FastAPI can share one engine without external infrastructure.

Two helpers are exported for the rest of the package:

``get_db``
    FastAPI dependency yielding a SQLAlchemy ``Session`` bound to the
    configured engine.
``init_db``
    Idempotently create tables and (optionally) seed a demo job so a fresh
    CLI/dashboard has something to look at.

Every ``datetime`` stored is naive UTC; :func:`cronmon.models.now_utc` is the
single source of truth for producing those values.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from cronmon.models import Alert, Base, Job, Run, now_utc

#: Environment variable toggles the database used by the whole package.
#: ``:memory:`` gives a fresh DB per connection; the default is a real file so
#: state survives restarts when the server is run normally.
DEFAULT_DB_PATH = ":memory:"


def db_path() -> str:
    """Resolve the database connection string from the environment."""
    return os.getenv("CRONMON_DB", DEFAULT_DB_PATH)


def _is_memory(path: str) -> bool:
    """True for the ``:memory:`` sentinel or a sqlite ``mode=memory`` URI."""
    return path == ":memory:" or ("mode=memory" in path and path.startswith("file:"))


def make_engine(database: str | None = None):
    """Build a SQLAlchemy engine for ``database`` (falls back to env)."""
    path = str(database or db_path() or ":memory:")

    kwargs: dict = {"connect_args": {"check_same_thread": False}}
    if _is_memory(path):
        # An in-memory DB needs StaticPool so the single engine holds the sole
        # connection (otherwise each connection gets its own empty store).
        from sqlalchemy.pool import StaticPool

        kwargs["poolclass"] = StaticPool
        url = "sqlite://"
    elif path.startswith("sqlite"):
        # Caller already passed a full sqlalchemy URL (incl. file: URIs).
        return create_engine(path, **kwargs)
    else:
        parent = Path(path).parent
        if str(parent) not in (".", ""):
            parent.mkdir(parents=True, exist_ok=True)
        url = f"sqlite:///{path}"

    engine = create_engine(url, **kwargs)

    # Serialize writes and set foreign keys on for SQLite integrity.
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):  # noqa: ARG001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


#: Module-level default engine. Tests replace this by calling
#: ``make_engine`` + ``init_db`` and injecting their own ``get_db`` override.
engine = make_engine()

SessionLocal = sessionmaker(
    autocommit=False, autoflush=False, bind=engine, class_=Session
)


def init_db(database: str | None = None, seed: bool = True) -> Session:
    """Create all tables and return a session bound to ``database``.

    If ``database`` is provided (or ``CRONMON_DB`` is set) ``SessionLocal`` is
    reconfigured onto that store so every subsequent call shares it. This makes
    a CLI invocation, the server, and a test all agree on the same sqlite file.
    """
    global engine, SessionLocal  # noqa: PLW0603
    engine = make_engine(database)  # rebuilds from env when database is None
    SessionLocal.configure(bind=engine)
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    if seed and seed_required(session):
        _seed_demo(session)
    return session


def seed_required(session: Session) -> bool:
    """True when there are no jobs yet (determines whether to seed)."""
    return session.query(Job.id).first() is None


def _seed_demo(session: Session) -> None:
    """Insert a couple of demo jobs so the dashboard isn't empty on first run."""
    demo = [
        Job(
            name="Nightly Backup",
            cron="0 2 * * *",
            expected_duration=3600,
            alert_after_minutes=120,
        ),
        Job(
            name="DB Reindex",
            cron="30 3 * * *",
            expected_duration=600,
            alert_after_minutes=30,
        ),
    ]
    session.add_all(demo)
    session.commit()


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a scoped read/write session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def now() -> "now_utc.__class__":
    """Alias for the models' UTC now helper (import convenience)."""
    return now_utc()


__all__ = [
    "engine",
    "SessionLocal",
    "init_db",
    "get_db",
    "db_path",
    "make_engine",
    "now",
    "Alert",
    "Base",
    "Job",
    "Run",
]