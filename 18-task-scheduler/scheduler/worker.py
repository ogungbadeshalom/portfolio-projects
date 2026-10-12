"""Worker: dequeues tasks, executes the registered handler, acks/nacks.

Each :class:`Worker` is one consuming thread (or process) that:

* Heartbeats to the store so the liveness monitor can spot dead workers.
* Loops on :meth:`scheduler.queue.ReadyQueue.dequeue` (blocking wait, no
  busy polling).
* Runs the task function with an optional timeout, then ``ack`` / ``nack``.
* Records per-attempt :class:`TaskRun` rows + Prometheus metrics.

A worker can be run in-process (``python -m scheduler.worker``) or as part of
the FastAPI app's lifespan.
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import json
import logging
import platform
import socket
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from datetime import timedelta
from typing import Callable, Any

from scheduler import metrics as metrics_mod
from scheduler.config import get_config
from scheduler.models import STATUS_FAILED, Worker as WorkerRow, now_utc
from scheduler.queue import DequeueResult, ReadyQueue, ready_queue as default_queue
from scheduler.registry import TaskNotFoundError, registry
from scheduler.store import get_session

logger = logging.getLogger(__name__)


def _resolve_handler(name: str) -> Callable[..., Any]:
    return registry.get(name).func


class Worker:
    """One consuming worker thread."""

    def __init__(
        self,
        worker_id: str | None = None,
        *,
        queue: ReadyQueue | None = None,
        tick_seconds: float = 0.5,
        timeout_seconds: float | None = None,
        config=None,
    ) -> None:
        self.config = config or get_config()
        self.id = worker_id or f"w-{socket.gethostname()}-{threading.get_ident()}"
        self.queue = queue or default_queue
        self.tick_seconds = tick_seconds
        self.timeout_seconds = timeout_seconds or self.config.task_timeout_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="task-run")

    # -- public lifecycle --------------------------------------------
    def start(self) -> "Worker":
        self._register_worker()
        self._thread = threading.Thread(
            target=self._run, name=f"worker-{self.id}", daemon=True
        )
        self._thread.start()
        return self

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    # -- heartbeats ---------------------------------------------------
    def _register_worker(self) -> None:
        session = get_session()
        try:
            row = session.get(WorkerRow, self.id)
            if row is None:
                row = WorkerRow(
                    id=self.id,
                    hostname=platform.node() or socket.gethostname(),
                    status="active",
                )
                session.add(row)
            else:
                row.status = "active"
            session.commit()
        finally:
            session.close()

    def _heartbeat(self) -> None:
        session = get_session()
        try:
            row = session.get(WorkerRow, self.id)
            if row is None:
                row = WorkerRow(id=self.id, hostname=platform.node(), status="active")
                session.add(row)
            row.last_heartbeat = now_utc()
            session.commit()
        finally:
            session.close()

    def _mark_offline(self) -> None:
        session = get_session()
        try:
            row = session.get(WorkerRow, self.id)
            if row is not None:
                row.status = "offline"
                session.commit()
        finally:
            session.close()

    # -- main loop ----------------------------------------------------
    def _run(self) -> None:
        next_beat = time.monotonic()
        try:
            while not self._stop.is_set():
                if time.monotonic() >= next_beat:
                    self._heartbeat()
                    next_beat = time.monotonic() + self.config.heartbeat_interval_seconds

                try:
                    claimed = self.queue.dequeue(timeout=self.tick_seconds, worker_id=self.id)
                except Exception:  # noqa: BLE001
                    logger.exception("dequeue error on worker %s", self.id)
                    continue
                if claimed is None:
                    continue
                self._process(claimed)
        finally:
            self._executor.shutdown(wait=False)
            self._mark_offline()

    def _process(self, claimed: DequeueResult) -> None:
        task = claimed.task
        session = claimed.session
        started = time.monotonic()
        task_id = task.id
        metrics_mod.record_task_started(task.name)
        self._update_current(task_id)

        try:
            handler = _resolve_handler(task.name)
        except TaskNotFoundError:
            error = f"No registered task handler for {task.name!r}"
            self.queue.nack(claimed, error)
            self._note_worker_failure()
            metrics_mod.record_task_finished(STATUS_FAILED)
            logger.error("task %s: %s", task_id, error)
            return

        try:
            payload = json.loads(task.payload_json or "{}")
            result = self._run_with_timeout(handler, payload)
            claimed.run.result = str(result)
            self.queue.ack(claimed)
            metrics_mod.record_task_completed(task.name, time.monotonic() - started)
            metrics_mod.record_task_finished("done")
            self._note_worker_success()
        except FutureTimeout:
            error = f"Task timed out after {self.timeout_seconds}s"
            self._abort(claimed, error)
            metrics_mod.record_task_completed(task.name, self.timeout_seconds)
            metrics_mod.record_task_finished(STATUS_FAILED)
            self._note_worker_failure()
        except Exception as exc:  # noqa: BLE001 - capture any task error
            error = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
            self.queue.nack(claimed, error)
            metrics_mod.record_task_completed(task.name, time.monotonic() - started)
            metrics_mod.record_task_finished(STATUS_FAILED)
            self._note_worker_failure()
            logger.error("task %s failed: %s", task_id, exc)

    def _run_with_timeout(self, func: Callable[..., Any], payload: dict) -> Any:
        """Run ``func(**payload)``, enforcing the configured timeout."""
        callable_ = _payload_call(func, payload)
        future = self._executor.submit(callable_)
        return future.result(timeout=self.timeout_seconds)

    def _abort(self, claimed: DequeueResult, error: str) -> None:
        claimed.task.status = STATUS_FAILED
        from scheduler.models import TaskRun

        claimed.run.status = "failed"
        claimed.run.error = error
        claimed.run.ended_at = now_utc()
        claimed.session.commit()
        claimed.session.close()

    # -- bookkeeping --------------------------------------------------
    def _update_current(self, task_id: int) -> None:
        session = get_session()
        try:
            row = session.get(WorkerRow, self.id)
            if row is not None:
                row.current_task_id = task_id
                session.commit()
        finally:
            session.close()

    def _note_worker_success(self) -> None:
        session = get_session()
        try:
            row = session.get(WorkerRow, self.id)
            if row is not None:
                row.tasks_completed = (row.tasks_completed or 0) + 1
                row.current_task_id = None
                session.commit()
        finally:
            session.close()

    def _note_worker_failure(self) -> None:
        session = get_session()
        try:
            row = session.get(WorkerRow, self.id)
            if row is not None:
                row.tasks_failed = (row.tasks_failed or 0) + 1
                row.current_task_id = None
                session.commit()
        finally:
            session.close()


def _payload_call(func: Callable[..., Any], payload: dict) -> Callable[[], Any]:
    """Build a zero-arg callable that invokes ``func`` with the payload.

    Payload keys are mapped onto the function's parameters (positional-or-keyword
    and ``**kwargs``). Sync and async functions are both supported.
    """
    has_kwargs = _accepts_kw(func)
    params = [
        p.name
        for p in inspect.signature(func).parameters.values()
        if p.kind == inspect.Parameter.POSITIONAL_OR_KEYWORD
    ]
    call_kwargs = {k: v for k, v in payload.items() if has_kwargs or k in params}

    if inspect.iscoroutinefunction(func):

        async def wrapped():
            return await func(**call_kwargs)

        def runner():
            return asyncio.new_event_loop().run_until_complete(wrapped())

        return runner

    click_partial = functools.partial(func, **call_kwargs)
    if call_kwargs:
        return click_partial
    return func


def _accepts_kw(func: Callable[..., Any]) -> bool:
    try:
        return any(
            p.kind == inspect.Parameter.VAR_KEYWORD
            for p in inspect.signature(func).parameters.values()
        )
    except (TypeError, ValueError):
        return False


def stop_all(workers: list[Worker]) -> None:
    for w in workers:
        w.stop()


def _main() -> None:  # pragma: no cover - invoked via `python -m scheduler.worker`
    """Run ``N`` worker threads until Ctrl-C. Entrypoint for the CLI."""
    import argparse
    import signal

    parser = argparse.ArgumentParser(description="Run scheduler worker(s).")
    parser.add_argument("--id", default=None, help="base worker id")
    parser.add_argument("--count", type=int, default=1, help="number of workers")
    args = parser.parse_args()

    from scheduler import example_tasks  # noqa: F401  (register handlers)
    from scheduler.store import ensure_store

    ensure_store()
    workers = []
    for i in range(args.count):
        wid = f"{args.id or 'w'}" + (f"-{i}" if args.count > 1 else "")
        workers.append(Worker(worker_id=wid).start())

    stop = [False]

    def _sig(*_args) -> None:
        stop[0] = True

    signal.signal(signal.SIGINT, _sig)
    try:
        signal.signal(signal.SIGTERM, _sig)
    except (ValueError, OSError):  # pragma: no cover - non-POSIX
        pass

    print(f"Running {len(workers)} worker(s); Ctrl-C to stop...")
    try:
        while not stop[0]:
            time.sleep(0.5)
    finally:
        stop_all(workers)
        print("workers stopped")


if __name__ == "__main__":
    _main()


__all__ = ["Worker", "stop_all"]