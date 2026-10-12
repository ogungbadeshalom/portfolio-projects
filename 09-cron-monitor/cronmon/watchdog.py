"""Dead-man's-switch + over-duration watchdog.

The watchdog is a periodic sweep (run every minute via APScheduler in the
server, or invoked directly by the CLI / tests) that looks for two classes of
problem and raises :class:`Alert` rows for them:

* **Over-duration** — a run that is still open but has outlived its job's
  ``expected_duration``.
* **Dead man's switch (missed schedule)** — a cron-scheduled job that should
  have fired (≥ ``alert_after_minutes`` past its latest scheduled fire time)
  but has no run at all since then.

The sweep is deliberately **idempotent**: running it twice never creates a
duplicate alert, because we skip creating an alert if an un-acknowledged alert
of the same type already exists for the same job. This is what makes it safe to
fire from multiple processes or on a schedule that overlaps.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Sequence

from sqlalchemy.orm import Session

from cronmon import alerting
from cronmon.crontab import CronExpr
from cronmon.models import Alert, Job, Run, now_utc

logger = logging.getLogger("cronmon.watchdog")


#: Maximum minutes the watchdog will step back when hunting for a run that
#: satisfies a missed schedule. Prevents pathological scans on old jobs.
_LOOKBACK_DAYS = 60


def _open_overdue_run(db: Session, run: Run, job: Job) -> bool:
    """Raise an over-duration alert for a run. Returns True if newly created."""
    if _has_live_alert(db, job.id, "over_duration", run_id=run.id):
        return False
    alert = Alert(
        job_id=job.id,
        run_id=run.id,
        type="over_duration",
        message=(
            f"Run #{run.id} of job {job.name!r} is still running {run.duration_seconds or 0}s "
            f"after the expected max duration of {job.expected_duration}s "
            f"(started {run.started_at.isoformat()})."
        ),
    )
    db.add(alert)
    db.commit()
    alerting.dispatch(db, alert)
    logger.warning("over_duration alert for job_id=%s run_id=%s", job.id, run.id)
    return True


def _has_live_alert(db: Session, job_id: int, al_type: str, run_id: int | None = None) -> bool:
    """True when an un-acknowledged alert of this type already exists for the job."""
    query = db.query(Alert).filter(
        Alert.job_id == job_id,
        Alert.type == al_type,
        Alert.acknowledged.is_(False),
    )
    if run_id is not None:
        query = query.filter(Alert.run_id == run_id)
    return query.first() is not None


def _missed_schedule(db: Session, job: Job) -> bool:
    """Raise a dead-man's-switch alert if a cron job missed its schedule.

    Returns True if an alert was newly created.
    """
    if not job.cron:
        return False
    try:
        expr = CronExpr(job.cron)
    except ValueError as exc:
        # Bad cron shouldn't crash the sweep; surface it once as an alert.
        if not _has_live_alert(db, job.id, "invalid_cron"):
            db.add(
                Alert(
                    job_id=job.id,
                    type="invalid_cron",
                    message=f"Job {job.name!r} has an invalid cron {job.cron!r}: {exc}",
                )
            )
            db.commit()
            return True
        return False

    now = now_utc()
    # Latest scheduled fire time strictly before now.
    try:
        latest = expr.prev_fire(now)
    except ValueError:
        return False
    due_at = latest + timedelta(minutes=job.alert_after_minutes)
    if now < due_at:
        return False

    # A run started at/after the missed fire time means the job did fire.
    # A live open run also counts as fired (it hasn't checked in done yet).
    recent = (
        db.query(Run)
        .filter(Run.job_id == job.id, Run.started_at >= latest)
        .order_by(Run.started_at.desc())
        .first()
    )
    if recent is not None:
        return False
    if _has_live_alert(db, job.id, "missed_schedule"):
        return False

    alert = Alert(
        job_id=job.id,
        type="missed_schedule",
        message=(
            f"Dead man's switch: job {job.name!r} (cron {job.cron!r}) was due at "
            f"{latest.isoformat()} but has not started a run {job.alert_after_minutes} "
            f"minutes later (checked {now.isoformat()})."
        ),
    )
    db.add(alert)
    db.commit()
    alerting.dispatch(db, alert)
    logger.warning("missed_schedule alert for job_id=%s", job.id)
    return True


def check(db: Session) -> int:
    """Run one full watchdog sweep; returns the number of alerts *created*.

    Idempotent: repeated sweeps on unchanged state create no new alerts and
    return 0.
    """
    created = 0
    jobs: Sequence[Job] = db.query(Job).filter(Job.enabled.is_(True)).all()
    for job in jobs:
        # 1) Over-duration open runs.
        open_runs = (
            db.query(Run)
            .filter(Run.job_id == job.id, Run.ended_at.is_(None))
            .order_by(Run.started_at)
            .all()
        )
        for run in open_runs:
            if run.is_overdue and _open_overdue_run(db, run, job):
                created += 1

        # 2) Dead-man's switch for cron jobs.
        if _missed_schedule(db, job):
            created += 1

    return created


def run(database: str | None = None) -> int:
    """Convenience entry: open a fresh session on ``database`` and sweep.

    Used by the CLI subcommand and by tests that want a standalone sweep.
    Returns the number of alerts created.
    """
    from cronmon.database import init_db

    session = init_db(database, seed=False)
    try:
        return check(session)
    finally:
        session.close()


__all__ = ["check", "run"]