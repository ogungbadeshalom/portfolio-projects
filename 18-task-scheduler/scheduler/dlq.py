"""Dead-letter queue: parking, inspecting, retrying and skipping tasks.

A task whose ``attempts`` reached its cap is parked in status ``dead``. This
module provides the DLQ operations the web UI and CLI need:

* :func:`list_dlq` — view parked tasks with their last error.
* :func:`retry_dlq` — move a dead task back to ``pending`` (fresh attempts).
* :func:`purge_dlq` — delete parked tasks (the "skip"/poison-pill action).
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import update

from scheduler.config import get_config
from scheduler.models import STATUS_DEAD, STATUS_PENDING, Task, TaskRun, now_utc
from scheduler.queue import ready_queue
from scheduler.store import get_session


def list_dlq(limit: int = 100) -> list[dict]:
    """Return parked tasks with last error + run history sizes."""
    session = get_session()
    try:
        rows = (
            session.query(Task)
            .filter(Task.status == STATUS_DEAD)
            .order_by(Task.id.desc())
            .limit(limit)
            .all()
        )
        out = []
        for t in rows:
            last_run = (
                session.query(TaskRun)
                .filter(TaskRun.task_id == t.id, TaskRun.error.isnot(None))
                .order_by(TaskRun.started_at.desc())
                .first()
            )
            out.append(
                {
                    "id": t.id,
                    "name": t.name,
                    "payload_json": t.payload_json,
                    "attempts": t.attempts,
                    "max_attempts": t.max_attempts,
                    "last_error": last_run.error if last_run else t.last_error,
                    "created_at": t.created_at,
                }
            )
        return out
    finally:
        session.close()


def retry_dlq(task_id: int) -> bool:
    """Reset a dead task to pending with a fresh attempt budget and schedule it."""
    session = get_session()
    cfg = get_config()
    claimed = session.execute(
        update(Task)
        .where(Task.id == task_id, Task.status == STATUS_DEAD)
        .values(
            status=STATUS_PENDING,
            attempts=0,
            last_error=None,
            due_at=now_utc(),
            completed_at=None,
        )
    )
    session.commit()
    session.close()
    ok = claimed.rowcount == 1
    if ok:
        ready_queue.signal(task_id)
    return ok


def purge_dlq(task_ids: list[int] | None = None) -> int:
    """Delete parked tasks (all of them when ``task_ids`` is None)."""
    session = get_session()
    query = session.query(Task).filter(Task.status == STATUS_DEAD)
    if task_ids:
        query = query.filter(Task.id.in_(task_ids))
    count = 0
    for task in query.all():
        session.delete(task)
        count += 1
    session.commit()
    session.close()
    return count


class DeadLetterQueue:
    """Object-oriented façade over the DLQ helpers (retained for naming symmetry)."""

    def __init__(self) -> None:
        self.store = get_session()

    def size(self) -> int:
        self.store.rollback()
        return self.store.query(Task).filter(Task.status == STATUS_DEAD).count()

    def list(self, limit: int = 100) -> list[dict]:
        return list_dlq(limit=limit)

    def retry(self, task_id: int) -> bool:
        return retry_dlq(task_id)

    def skip(self, task_id: int) -> bool:
        return purge_dlq([task_id]) > 0


__all__ = ["list_dlq", "retry_dlq", "purge_dlq", "DeadLetterQueue"]