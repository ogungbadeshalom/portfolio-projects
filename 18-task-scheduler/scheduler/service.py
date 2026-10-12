"""Operational service: what the CLI and HTTP API both call.

Centralises the "write a task and signal the ready queue" logic so the CLI and
the web app behave identically: schedule a one-time or cron task, enqueue an
immediate run, cancel a pending task, and query state.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from scheduler import cron
from scheduler.config import get_config
from scheduler.models import (
    STATUS_CANCELED,
    STATUS_DEAD,
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_RUNNING,
    Task,
    now_utc,
)
from scheduler.queue import ready_queue
from scheduler.registry import registry
from scheduler.store import get_session


class TaskError(ValueError):
    """Raised for invalid scheduling requests (unknown task, bad cron)."""


def schedule_task(
    name: str,
    *,
    payload: dict[str, Any] | None = None,
    at: datetime | None = None,
    cron_expr: str | None = None,
    max_attempts: int | None = None,
    idempotency_key: str | None = None,
    depends_on: int | None = None,
    session: Session | None = None,
) -> Task:
    """Create a task for immediate, one-shot, or cron execution.

    * ``at`` set + ``cron_expr`` None  -> one-time task
    * ``cron_expr`` set -> recurring cron task (first fire at its next slot)
    * neither -> run immediately

    Returns the persisted :class:`Task`. The task is signalled to the ready
    queue only if it's immediately runnable.
    """
    if name not in registry:
        raise TaskError(f"unknown task {name!r}; known: {registry.names()}")
    payload_json = json.dumps(payload or {})
    own = session is None
    session = session or get_session()

    dedup_key = idempotency_key
    if dedup_key:
        existing = session.query(Task).filter(Task.idempotency_key == dedup_key).first()
        if existing is not None:
            if own:
                session.close()
                raise TaskError(f"duplicate idempotency_key {dedup_key!r} (task {existing.id})")
            return existing

    now = now_utc()
    # Normalize any timezone-aware client timestamp to naive UTC for storage.
    if isinstance(at, datetime) and at.tzinfo is not None:
        at = at.astimezone(timezone.utc).replace(tzinfo=None)

    due_at: datetime | None = now
    scheduled_at: datetime | None = None
    status = STATUS_PENDING
    if cron_expr:
        try:
            nxt = cron.next_fire(cron_expr, now)
        except cron.CronError as exc:
            if own:
                session.close()
            raise TaskError(str(exc)) from exc
        scheduled_at = nxt
        due_at = nxt  # wait until the first fire
        status = STATUS_PENDING
    elif at is not None:
        scheduled_at = at
        due_at = at if at > now else now  # fire immediately if already past
    else:
        scheduled_at = now
        due_at = now

    task = Task(
        name=name,
        payload_json=payload_json,
        scheduled_at=scheduled_at,
        due_at=due_at,
        status=status,
        max_attempts=max_attempts or get_config().max_attempts,
        cron=cron_expr,
        idempotency_key=dedup_key,
        depends_on=depends_on,
    )
    session.add(task)
    session.commit()
    session.refresh(task)
    if own:
        session.close()
    if due_at <= now_utc():
        ready_queue.signal(task.id)
    return task


def cancel_task(task_id: int) -> bool:
    """Cancel a pending task. Returns True if it was still pending."""
    session = get_session()
    try:
        task = session.get(Task, task_id)
        if task is None or task.status != STATUS_PENDING:
            return False
        task.status = STATUS_CANCELED
        session.commit()
        return True
    finally:
        session.close()


def task_summary(session: Session, task: Task) -> dict:
    """Shape a Task for API/CLI output with derived fields."""
    runs = []
    for r in task.runs[-5:]:
        runs.append(
            {
                "id": r.id,
                "worker_id": r.worker_id,
                "status": r.status,
                "started_at": r.started_at,
                "ended_at": r.ended_at,
                "duration_seconds": r.duration_seconds,
                "result": r.result,
                "error": r.error,
            }
        )
    return {
        "id": task.id,
        "name": task.name,
        "status": task.status,
        "payload_json": task.payload_json,
        "scheduled_at": task.scheduled_at,
        "due_at": task.due_at,
        "cron": task.cron,
        "attempts": task.attempts,
        "max_attempts": task.max_attempts,
        "last_error": task.last_error,
        "idempotency_key": task.idempotency_key,
        "depends_on": task.depends_on,
        "created_at": task.created_at,
        "completed_at": task.completed_at,
        "runs": runs,
    }


__all__ = ["schedule_task", "cancel_task", "task_summary", "TaskError"]