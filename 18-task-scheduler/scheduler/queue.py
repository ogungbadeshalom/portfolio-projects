"""In-memory ready-queue + sqlite-backed claim/ack (at-least-once delivery).

Design
------
The scheduler keeps the durable truth (task rows) in sqlite. The dispatcher
finds tasks whose ``due_at`` has passed in status ``pending`` and signals the
in-memory :class:`ReadyQueue`. Workers call :meth:`ReadyQueue.dequeue`, which:

1. Blocks up to ``timeout`` for a ready task id.
2. Atomically claims it via a conditional SQL update
   (``status='pending' -> 'running'``). Only one worker wins the CAS, which is
   what gives at-least-once, single-consumer semantics without Redis locks.

After executing, the worker calls :meth:`ack` (success) or :meth:`nack`
(failure -> retry with backoff or DLQ). A ``nack`` before the claim was
observed would lose the task, so claiming and acking are both row-granular and
safe across threads and processes.

The in-memory queue exists purely to avoid busy-polling sqlite every few
hundred milliseconds; it carries no authoritative state.
"""

from __future__ import annotations

import queue as _queue
import threading
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import func, update
from sqlalchemy.orm import Session

from scheduler import retry as retry_mod
from scheduler.config import get_config
from scheduler.models import (
    STATUS_CANCELED,
    STATUS_DEAD,
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_RUNNING,
    Task,
    TaskRun,
    now_utc,
)
from scheduler.store import get_session


def _sleep(seconds: float) -> None:
    """Sleep helper (module-level so it is stubbable in tests)."""
    time.sleep(seconds)


@dataclass
class DequeueResult:
    """What a worker gets from :meth:`ReadyQueue.dequeue`."""

    task: Task  # object in a session scoped to the execution
    session: Session
    run: TaskRun

    task_id: int = 0

    def __post_init__(self) -> None:
        self.task_id = self.task.id


class ReadyQueue:
    """Thread-safe signal channel of task ids ready for execution."""

    def __init__(self) -> None:
        self._q: _queue.Queue[int] = _queue.Queue()
        self._enqueued: set[int] = set()
        self._lock = threading.Lock()

    def signal(self, task_id: int) -> None:
        """Mark ``task_id`` as ready-to-run (idempotent per in-flight window)."""
        with self._lock:
            if task_id in self._enqueued:
                return
            self._enqueued.add(task_id)
        self._q.put(task_id)

    def remove(self, task_id: int) -> None:
        with self._lock:
            self._enqueued.discard(task_id)

    def _pop(self, timeout: float | None) -> int | None:
        try:
            task_id = self._q.get(timeout=timeout)
        except _queue.Empty:
            return None
        # Drop from the enqueued set so a later `signal()` can re-add it.
        # Without this a popped-but-unclaimed task stays in `_enqueued` and
        # `signal()` becomes a no-op, stranding the task forever.
        with self._lock:
            self._enqueued.discard(task_id)
        return task_id

    def dequeue(
        self, *, timeout: float | None = None, worker_id: str | None = None
    ) -> DequeueResult | None:
        """Claim a pending task and mark it running. Returns None on timeout.

        The claim uses a conditional UPDATE on the store so two workers can
        never run the same task concurrently.
        """
        while True:
            task_id = self._pop(timeout)
            if task_id is None:
                return None

            session = get_session()
            # Atomically claim exactly one pending row.
            claimed = session.execute(
                update(Task)
                .where(
                    Task.id == task_id,
                    Task.status == STATUS_PENDING,
                    Task.due_at <= now_utc(),  # not before its due time
                )
                .values(status=STATUS_RUNNING)
            )
            session.commit()
            if claimed.rowcount != 1:
                # Either already taken by a peer, or not yet due (backoff/cron).
                # Not-yet-due tasks must stay in rotation for a later claim.
                fresh = session.get(Task, task_id)
                session.close()
                if fresh is None or fresh.status != STATUS_PENDING:
                    self.remove(task_id)
                    continue
                # Still pending but not yet due (backoff pushed `due_at` out).
                # Re-signal keeps it claimable later, then sleep a bounded slice
                # until it matures — avoids a busy spin on the same task.
                self.signal(task_id)
                wait = (fresh.due_at - now_utc()).total_seconds()
                if wait > 0:
                    _sleep(min(0.1, wait))
                continue  # try the next item

            task = session.get(Task, task_id)
            run = TaskRun(
                task_id=task_id,
                worker_id=worker_id or "unknown",
                status="running",
            )
            session.add(run)
            session.commit()
            self.remove(task_id)
            return DequeueResult(task=task, session=session, run=run)

    def ack(self, result: DequeueResult) -> None:
        """Record success for ``result.task`` and close its run."""
        session = result.session
        task = result.task
        task.status = STATUS_DONE
        task.attempts += 1
        task.completed_at = now_utc()
        task.last_error = None
        _close_run(session, result.run, "done")
        session.commit()
        result.session.close()

    def nack(self, result: DequeueResult, error: str) -> None:
        """Handle failure: retry with backoff, or move to the dead-letter queue."""
        session = result.session
        task = result.task
        task.attempts += 1
        task.last_error = error
        cfg = get_config()

        if task.attempts >= task.max_attempts:
            task.status = STATUS_DEAD
            _close_run(session, result.run, "failed", error)
            session.commit()
        else:
            delay = retry_mod.backoff_delay_seconds(
                task.attempts,
                base=cfg.backoff_base_seconds,
                max_seconds=cfg.backoff_max_seconds,
                jitter=cfg.backoff_jitter,
            )
            task.status = STATUS_PENDING
            task.due_at = now_utc() + timedelta(seconds=delay)
            task.cron = None  # a scheduled retry supersedes the cron window
            _close_run(session, result.run, "failed", error)
            session.commit()
            self.signal(task.id)
        result.session.close()

    def cancel(self, task_id: int) -> bool:
        """Mark a pending/unrun task canceled (no-op if already running)."""
        session = get_session()
        claimed = session.execute(
            update(Task)
            .where(Task.id == task_id, Task.status == STATUS_PENDING)
            .values(status=STATUS_CANCELED)
        )
        session.commit()
        session.close()
        return claimed.rowcount == 1


def _close_run(session: Session, run: TaskRun, status: str, error: str | None = None) -> None:
    run.status = status
    run.ended_at = now_utc()
    run.error = error


#: The process-wide ready queue shared by dispatcher and workers.
ready_queue = ReadyQueue()


def reset_ready_queue() -> ReadyQueue:
    """Rebuild the shared ready queue (used by tests for isolation)."""
    global ready_queue  # noqa: PLW0603
    ready_queue = ReadyQueue()
    return ready_queue


__all__ = ["ReadyQueue", "ready_queue", "DequeueResult", "reset_ready_queue"]