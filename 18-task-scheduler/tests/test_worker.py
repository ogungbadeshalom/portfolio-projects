"""Worker + queue integration tests against sqlite + the real ready queue."""

from __future__ import annotations

import time

import pytest

from scheduler import example_tasks  # noqa: F401
from scheduler import service
from scheduler.config import get_config
from scheduler.models import (
    STATUS_DEAD,
    STATUS_DONE,
    STATUS_PENDING,
    STATUS_RUNNING,
    Task,
    Worker as WorkerRow,
)
from scheduler.queue import ReadyQueue
from scheduler.worker import Worker


def _wait_task(session, task_id, timeout=8.0, terminal=("done", "failed", "dead", "canceled")):
    """Poll until a task leaves the running/pending state."""
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        session.expire_all()
        task = session.get(Task, task_id)
        if task.status in terminal:
            return task
        time.sleep(0.05)
    session.expire_all()
    return session.get(Task, task_id)


class TestReadyQueue:
    def test_claim_is_at_least_once_and_single_consumer(self, store):
        q = ReadyQueue()
        task = service.schedule_task("add", payload={"a": 1, "b": 2})
        q.signal(task.id)
        r1 = q.dequeue(timeout=0.5, worker_id="w1")
        assert r1 is not None
        assert r1.task.id == task.id
        # No second consumer may claim the same task while it's running.
        r2 = q.dequeue(timeout=0.3, worker_id="w2")
        assert r2 is None

    def test_ack_sets_done(self, store):
        q = ReadyQueue()
        task = service.schedule_task("add", payload={"a": 1, "b": 2})
        q.signal(task.id)
        claimed = q.dequeue(timeout=0.5)
        q.ack(claimed)
        store.expire_all()
        assert store.get(Task, task.id).status == STATUS_DONE

    def test_nack_sets_pending_with_future_due(self, store):
        q = ReadyQueue()
        task = service.schedule_task("send_email", payload={"to": "a@b.co"}, max_attempts=10)
        q.signal(task.id)
        claimed = q.dequeue(timeout=0.5)
        q.nack(claimed, "boom")
        store.expire_all()
        t = store.get(Task, task.id)
        assert t.status == STATUS_PENDING
        assert t.attempts == 1
        assert t.due_at is not None and t.due_at > task.due_at  # backoff pushed it out

    def test_nack_exhausted_goes_dead(self, store):
        q = ReadyQueue()
        task = service.schedule_task("send_email", payload={"to": "a@b.co"}, max_attempts=1)
        q.signal(task.id)
        claimed = q.dequeue(timeout=0.5)
        q.nack(claimed, "boom")
        store.expire_all()
        assert store.get(Task, task.id).status == STATUS_DEAD


class TestWorkerExecution:
    def test_worker_executes_and_records_result(self, store):
        worker = Worker(worker_id="w-e2e").start()
        try:
            time.sleep(0.15)
            task = service.schedule_task("add", payload={"a": 40, "b": 2})
            done = _wait_task(store, task.id)
            assert done.status == STATUS_DONE
            assert done.last_run.result == "42.0"
        finally:
            worker.stop()

    def test_worker_heartbeats(self, store):
        worker = Worker(worker_id="w-hb").start()
        try:
            time.sleep(0.2)
            store.expire_all()
            row = store.get(WorkerRow, "w-hb")
            assert row is not None
            assert row.last_heartbeat is not None
            assert row.status == "active"
        finally:
            worker.stop()

    def test_retries_then_dead_letter(self, store):
        """A task that always fails reaches the DLQ after max_attempts."""
        worker = Worker(worker_id="w-flaky").start()
        try:
            task = service.schedule_task("fail_task", payload={}, max_attempts=2)
            # fail_task sleeps nothing; with backoff it retries until exhausted.
            done = _wait_task(store, task.id, timeout=10)
            assert done.status == STATUS_DEAD
            assert done.attempts >= 2
            assert store.query(Task).filter(Task.id == task.id).one().status == STATUS_DEAD
        finally:
            worker.stop()

    def test_worker_timeout_kills_slow_task(self, store):
        cfg = get_config()
        cfg.task_timeout_seconds = 0.2
        worker = Worker(worker_id="w-timeout", timeout_seconds=0.2).start()
        try:
            task = service.schedule_task("slow_task", payload={"seconds": 5.0})
            done = _wait_task(store, task.id, timeout=8)
            # Timeout marks the task failed (a retry could follow, but the
            # immediate effect is the current attempt ended without 'done').
            assert done.status != STATUS_RUNNING
            assert done.last_run.status == "failed"
        finally:
            worker.stop()


class TestDeadLetterRetry:
    def test_retry_reclaims_and_re_executes(self, store):
        import json

        from scheduler.dlq import list_dlq, retry_dlq

        # Register a handler that fails once then succeeds.
        from scheduler.registry import registry

        calls = []

        @registry.task(name="flip_once")
        def flip_once(**kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                raise RuntimeError("first try fails")
            return "ok"

        worker = Worker(worker_id="w-retry").start()
        try:
            task = service.schedule_task("flip_once", payload={"x": 1}, max_attempts=2)
            # Should fail then retry (succeeds on second call) -> done.
            done = _wait_task(store, task.id, timeout=10)
            assert done.status == STATUS_DONE
            assert len(calls) == 2
        finally:
            worker.stop()