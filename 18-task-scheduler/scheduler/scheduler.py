"""Dispatcher: scans the store for due tasks and signals the ready queue.

Runs continuously (or once, for tests) detecting:

* **One-time tasks** whose ``scheduled_at`` has passed.
* **Cron tasks** creating a new run instance whenever their next fire time has
  come and gone.

Each scan only signals tasks that are still ``pending``, so the dispatcher is
idempotent and safe to run from multiple threads/processes. Cron matching uses
the compact 5-field parser in :mod:`scheduler.cron`.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

from sqlalchemy import and_

from scheduler import cron
from scheduler.config import get_config
from scheduler.models import STATUS_PENDING, STATUS_RUNNING, Task, now_utc
from scheduler.queue import ready_queue
from scheduler.store import get_session

logger = logging.getLogger(__name__)


@dataclass
class DispatchStats:
    """Result of one scan."""

    scanned: int = 0
    signalled: int = 0
    cron_instances_created: int = 0


def scan_once() -> DispatchStats:
    """Find tasks that are due and signal them. Returns numbers dispatched."""
    session = get_session()
    stats = DispatchStats()
    try:
        now = now_utc()

        # 1) One-time tasks pending and due.
        due_tasks = (
            session.query(Task)
            .filter(
                Task.status == STATUS_PENDING,
                Task.cron.is_(None),
                and_(Task.due_at.is_(None) | (Task.due_at <= now)),
            )
            .order_by(Task.id)
            .all()
        )
        for task in due_tasks:
            stats.scanned += 1
            ready_queue.signal(task.id)
            stats.signalled += 1

        # 2) Cron tasks: mint the next instance when its next fire is due.
        stats.cron_instances_created = _mint_cron(session, now)
        session.commit()
        return stats
    finally:
        session.close()


def _mint_cron(session, now) -> int:
    """Create run-instances for cron tasks whose next fire time has arrived.

    A cron task has ``cron`` set and no ``due_at`` locking it to one shot. The
    next fire time is read from ``followup_at`` (stored in ``scheduled_at``),
    OR recomputed from ``cron`` when that column is empty.
    """
    created = 0
    cron_tasks = (
        session.query(Task)
        .filter(
            Task.cron.isnot(None),
            Task.status.in_([STATUS_PENDING, STATUS_RUNNING]),
        )
        .all()
    )
    for task in cron_tasks:
        if task.scheduled_at is None or task.scheduled_at > now:
            continue  # not due yet
        try:
            nxt = cron.next_fire(task.cron, task.scheduled_at)
        except ValueError:
            logger.warning("bad cron %r on task %s", task.cron, task.id)
            continue
        # Create a fresh pending run-instance for the next fire.
        follow = Task(
            name=task.name,
            payload_json=task.payload_json,
            scheduled_at=nxt,
            due_at=nxt,
            status=STATUS_PENDING,
            max_attempts=task.max_attempts,
            cron=task.cron,  # keep the recurrence on the follow-up
            depends_on=None,
            idempotency_key=None,
        )
        session.add(follow)
        session.flush()
        ready_queue.signal(follow.id)
        # Advance the source so we only mint once per fire window.
        task.scheduled_at = nxt
        created += 1
    return created


def run_dispatcher_loop(stop_event: threading.Event | None = None) -> None:
    """Block, scanning every ``scan_interval_seconds`` until ``stop_event`` set."""
    cfg = get_config()
    stop = stop_event or threading.Event()
    while not stop.is_set():
        try:
            scan_once()
        except Exception:  # noqa: BLE001 - the dispatcher survives transient errors
            logger.exception("dispatcher scan failed")
        stop.wait(cfg.scan_interval_seconds)


def start_dispatcher_thread() -> threading.Thread:
    """Start the background dispatcher thread; return the thread handle."""
    stop_event = threading.Event()
    thread = threading.Thread(
        target=run_dispatcher_loop,
        args=(stop_event,),
        name="scheduler-dispatcher",
        daemon=True,
    )
    thread._stop_event = stop_event  # type: ignore[attr-defined]
    thread.start()
    return thread


def stop_dispatcher_thread(thread: threading.Thread) -> None:
    stop_event = getattr(thread, "_stop_event", None)  # type: ignore[attr-defined]
    if stop_event is not None:
        stop_event.set()
    thread.join(timeout=2)


__all__ = [
    "scan_once",
    "run_dispatcher_loop",
    "start_dispatcher_thread",
    "stop_dispatcher_thread",
    "DispatchStats",
]