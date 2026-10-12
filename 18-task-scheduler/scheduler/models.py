"""SQLAlchemy ORM models: Task, TaskRun, Worker.

Timestamps are naive UTC. Task state progress engines-managed; the sqlite store
gives crash durability (a task queued but not yet acknowledged still exists
across a scheduler restart).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    Boolean,
    Float,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def now_utc() -> datetime:
    """Naive UTC now for DB-agnostic timestamp storage."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


#: Task lifecycle statuses (mirrored by the enum-tolerant string column).
STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"
STATUS_DEAD = "dead"
STATUS_CANCELED = "canceled"


class Base(DeclarativeBase):
    """Declarative base for scheduler ORM models."""


class Task(Base):
    """A unit of work scheduled for future (or immediate) execution.

    ``payload_json`` holds arbitrary JSON-serializable arguments for the
    registered task function. ``cron`` is an optional 5-field cron expression;
    at most one of ``scheduled_at`` (one-time) or ``cron`` should be set.
    """

    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cron: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default=STATUS_PENDING, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(
        String(120), index=True, nullable=True
    )
    depends_on: Mapped[int | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    runs: Mapped[list["TaskRun"]] = relationship(
        back_populates="task", cascade="all, delete-orphan", order_by="TaskRun.started_at"
    )

    @property
    def last_run(self) -> "TaskRun | None":
        return self.runs[-1] if self.runs else None


class TaskRun(Base):
    """One execution attempt of a task."""

    __tablename__ = "task_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), index=True
    )
    worker_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="running")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)

    task: Mapped["Task"] = relationship(back_populates="runs")

    @property
    def duration_seconds(self) -> float | None:
        if self.ended_at is None:
            return None
        return max(0.0, (self.ended_at - self.started_at).total_seconds())


class Worker(Base):
    """A worker instance; liveness tracked via ``last_heartbeat``."""

    __tablename__ = "workers"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    hostname: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="active")
    last_heartbeat: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    current_task_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tasks_completed: Mapped[int] = mapped_column(Integer, default=0)
    tasks_failed: Mapped[int] = mapped_column(Integer, default=0)

    def is_dead(self, timeout_seconds: float) -> bool:
        from datetime import timedelta

        return (now_utc() - self.last_heartbeat) > timedelta(seconds=timeout_seconds)


__all__ = [
    "Base",
    "Task",
    "TaskRun",
    "Worker",
    "now_utc",
    "STATUS_PENDING",
    "STATUS_RUNNING",
    "STATUS_DONE",
    "STATUS_FAILED",
    "STATUS_DEAD",
    "STATUS_CANCELED",
]