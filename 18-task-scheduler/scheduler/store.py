"""SQLAlchemy engine/session management for the scheduler.

The store is the source of truth for task/run/worker state. A thread-safe
engine is created from the :class:`~scheduler.config.Config`; workers, the
dispatcher and the FastAPI app all share it via :func:`get_session`.
"""

from __future__ import annotations

import threading

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from scheduler.config import get_config
from scheduler.models import Base, Task, TaskRun, Worker

#: Per-process default engine (replaced by tests via make_engine/store()).
engine = None
SessionLocal: sessionmaker | None = None

#: Guards engine/session setup.
_lock = threading.Lock()


def make_engine(database: str | None = None):
    """Build a SQLAlchemy engine for ``database`` (or the configured store).

    ``:memory:``/``sqlite://`` turn into a disposable **temp-file** database so
    that every OS thread opens its own connection (SQLAlchemy's default
    ``QueuePool``). A single shared in-memory connection (`StaticPool`) is NOT
    safe here: workers, the dispatcher and the API all hit the store from
    different threads, and a single physical connection used concurrently races
    sessions into corrupt states (``NULL identity key`` / ``Could not refresh``).
    """
    path = database if database is not None else get_config().effective_db_path
    kwargs: dict = {"connect_args": {"check_same_thread": False}}
    if path == ":memory:":
        # Disposable per-process temp file; a fresh engine maps to a fresh file.
        import tempfile

        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        url = f"sqlite:///{tmp.name}"
    elif path.startswith("sqlite"):
        return create_engine(path, **kwargs)
    else:
        from pathlib import Path

        parent = Path(path).parent
        if str(parent) not in (".", ""):
            parent.mkdir(parents=True, exist_ok=True)
        url = f"sqlite:///{path}"

    eng = create_engine(url, **kwargs)

    @event.listens_for(eng, "connect")
    def _fk(dbapi_connection, connection_record):  # noqa: ARG001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return eng


def init_store(database: str | None = None) -> Session:
    """(Re)create tables on the target store and return a session.

    Call once at process start / per test store to switch the default engine.
    """
    global engine, SessionLocal  # noqa: PLW0603
    with _lock:
        engine = make_engine(database)
        SessionLocal = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
        Base.metadata.create_all(bind=engine)
        return SessionLocal()


def get_session() -> Session:
    """Open a fresh session for the current process scope."""
    if SessionLocal is None:
        init_store()
    return SessionLocal()


def ensure_store() -> None:
    """Idempotently create tables on the default store (lazy init)."""
    if SessionLocal is None:
        init_store()


__all__ = ["make_engine", "init_store", "get_session", "ensure_store", "engine", "SessionLocal"]