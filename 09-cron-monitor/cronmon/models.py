"""SQLAlchemy ORM models for the cron monitoring watchdog.

Classes
-------
Job
    A scheduled task the watchdog keeps an eye on.
Run
    A single invocation lifecycle (start -> ping... -> done).
Alert
    A watchdog-detected condition sent to the operator (dead man's
    switch miss, over-duration run, ...).

All timestamps are stored as naive UTC ``datetime`` objects. The
application layer is responsible for producing/consuming UTC values
(see ``database.py`` / helper ``now_utc``).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def now_utc() -> datetime:
    """Naive UTC ``datetime`` for consistent storage across DB drivers."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    """Declarative base for all cronmon ORM models."""


class Job(Base):
    """A registered job with an optional cron schedule.

    ``expected_duration`` is the maximum seconds a run may last before the
    watchdog flags it as over-duration. ``alert_after_minutes`` is how many
    minutes past the job's next scheduled fire time the watchdog waits
    before raising a dead-man's-switch (missed schedule) alert.
    """

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True, nullable=False)
    cron: Mapped[str | None] = mapped_column(String(120), nullable=True)
    expected_duration: Mapped[int] = mapped_column(Integer, default=3600)  # seconds
    alert_after_minutes: Mapped[int] = mapped_column(Integer, default=120)  # minutes
    webhook_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)

    runs: Mapped[list["Run"]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="Run.started_at",
    )
    alerts: Mapped[list["Alert"]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="Alert.sent_at",
    )

    @property
    def latest_run(self) -> "Run | None":
        return self.runs[-1] if self.runs else None

    def latest_run_obj(self) -> "Run | None":
        """Public alias so callers don't rely on ORM ordering quirks."""
        return self.runs[-1] if self.runs else None


class Run(Base):
    """One run lifecycle: created on ``start``, closed on ``done``.

    A run with ``ended_at`` null and status ``running`` is considered live.
    The watchdog flags it when it exceeds the job's ``expected_duration``.
    """

    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)
    pinged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="running", nullable=False)
    client_run_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)

    job: Mapped["Job"] = relationship(back_populates="runs")

    @property
    def duration_seconds(self) -> int | None:
        if self.ended_at is None:
            return None
        return max(0, int((self.ended_at - self.started_at).total_seconds()))

    @property
    def is_overdue(self) -> bool:
        """True when the run is live and has run longer than expected."""
        if self.ended_at is not None:
            return False
        elapsed = (now_utc() - self.started_at).total_seconds()
        return elapsed > self.job.expected_duration


class Alert(Base):
    """A condition the watchdog detected for a job.

    ``type`` is one of ``missed_schedule``, ``over_duration`` or a custom
    tag. ``sent_at`` is the UTC time the alert was created.
    """

    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    run_id: Mapped[int | None] = mapped_column(
        ForeignKey("runs.id", ondelete="SET NULL"), nullable=True
    )
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)

    job: Mapped["Job"] = relationship(back_populates="alerts")
    run: Mapped["Run | None"] = relationship()