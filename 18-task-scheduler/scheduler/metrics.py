"""Prometheus metrics for the scheduler.

Uses ``prometheus_client`` (an official lightweight dependency) to expose a
:meth:`metrics_text` / :func:`/metrics` endpoint. All metrics are read from the
live store so the dashboard, CLI and URL all agree. A plain-JSON view is also
provided so the operator doesn't need Prometheus to see the numbers.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest
from sqlalchemy import func

from scheduler.config import get_config
from scheduler.models import (
    STATUS_DEAD,
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_RUNNING,
    STATUS_CANCELED,
    Task,
    TaskRun,
    Worker,
    now_utc,
)
from scheduler.store import get_session

registry = CollectorRegistry()

# --- Counters --------------------------------------------------------
tasks_total = Counter(
    "scheduler_tasks_total", "Tasks created", ["name"], registry=registry
)
tasks_finished_total = Counter(
    "scheduler_tasks_finished_total",
    "Tasks reaching a terminal state",
    ["status"],
    registry=registry,
)
# --- Gauges ----------------------------------------------------------
tasks_running = Gauge(
    "scheduler_tasks_running", "Tasks currently running", registry=registry
)
tasks_pending = Gauge(
    "scheduler_tasks_pending", "Tasks awaiting execution", registry=registry
)
tasks_dead = Gauge("scheduler_tasks_dead", "Tasks in the dead-letter queue", registry=registry)
dlq_size = Gauge("scheduler_dlq_size", "Dead-letter queue size", registry=registry)
workers_active = Gauge("scheduler_workers_active", "Workers reporting liveness", registry=registry)
# --- Histogram -------------------------------------------------------
task_duration = Histogram(
    "scheduler_task_duration_seconds",
    "Task execution duration in seconds",
    ["name"],
    registry=registry,
)


def _refresh() -> dict[str, Any]:
    """Recompute gauge values from the live store; return a summary dict."""
    session = get_session()
    cfg = get_config()
    try:
        counts = dict(
            session.query(Task.status, func.count(Task.id)).group_by(Task.status).all()
        )
        pending = counts.get(STATUS_PENDING, 0)
        running = counts.get(STATUS_RUNNING, 0)
        dead = counts.get(STATUS_DEAD, 0)

        recent_worker_cutoff = now_utc() - timedelta(seconds=cfg.worker_timeout_seconds)
        active_workers = (
            session.query(Worker)
            .filter(Worker.last_heartbeat >= recent_worker_cutoff)
            .count()
        )
        # Faster per-name counts.
        name_counts = dict(
            session.query(Task.name, func.count(Task.id)).group_by(Task.name).all()
        )

        tasks_pending.set(pending)
        tasks_running.set(running)
        tasks_dead.set(dead)
        dlq_size.set(dead)
        workers_active.set(active_workers)
        return {
            "tasks_pending": pending,
            "tasks_running": running,
            "tasks_dead": dead,
            "workers_active": active_workers,
            "tasks_by_name": name_counts,
        }
    finally:
        session.close()


def record_task_finished(status: str) -> None:
    tasks_finished_total.labels(status=status).inc()


def record_task_started(name: str) -> None:
    tasks_running.inc()


def record_task_completed(name: str, duration_seconds: float) -> None:
    tasks_running.dec()
    task_duration.labels(name=name).observe(duration_seconds)


def metrics_text() -> bytes:
    """Render Prometheus exposition text for the current in-process registry."""
    _refresh()
    return generate_latest(registry)


def metrics_json() -> dict[str, Any]:
    """Human-friendly JSON snapshot (the plain '/metrics?format=json' fallback)."""
    loaded = _refresh()
    return loaded


__all__ = [
    "metrics_text",
    "metrics_json",
    "record_task_started",
    "record_task_completed",
    "record_task_finished",
]