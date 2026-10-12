"""Model-layer and watchdog behavior tests against fresh sqlite stores."""

from __future__ import annotations

from datetime import timedelta

import pytest

from cronmon.models import Alert, Job, Run, now_utc
from cronmon.watchdog import check


def _job(db, name="Nightly Backup", cron="0 2 * * *", expected=60, alert_after=5, **kw):
    job = Job(name=name, cron=cron, expected_duration=expected,
              alert_after_minutes=alert_after, **kw)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


class TestRunModel:
    def test_duration_seconds(self, db):
        job = _job(db)
        run = Run(job_id=job.id, started_at=now_utc() - timedelta(seconds=120))
        run.ended_at = run.started_at + timedelta(seconds=50)
        assert run.duration_seconds == 50

    def test_no_duration_for_open_run(self, db):
        job = _job(db)
        run = Run(job_id=job.id, started_at=now_utc())
        assert run.duration_seconds is None

    def test_is_overdue(self, db):
        job = _job(db, expected=10)
        overdue = Run(job_id=job.id, started_at=now_utc() - timedelta(seconds=100))
        db.add(overdue)
        db.flush()
        assert overdue.is_overdue
        not_overdue = Run(job_id=job.id, started_at=now_utc())
        db.add(not_overdue)
        db.flush()
        assert not not_overdue.is_overdue


class TestWatchdogOverDuration:
    def test_flags_overdue_run(self, db):
        job = _job(db, expected=10)
        db.add(Run(job_id=job.id, started_at=now_utc() - timedelta(minutes=5)))
        db.commit()
        created = check(db)
        assert created == 1
        alert = db.query(Alert).filter(Alert.type == "over_duration").first()
        assert alert is not None
        assert alert.job_id == job.id
        assert "job" in alert.message

    def test_no_alert_for_healthy_run(self, db):
        job = _job(db, expected=3600)
        db.add(Run(job_id=job.id, started_at=now_utc()))
        db.commit()
        assert check(db) == 0

    def test_idempotent_sweep(self, db):
        job = _job(db, expected=10)
        db.add(Run(job_id=job.id, started_at=now_utc() - timedelta(minutes=5)))
        db.commit()
        check(db)
        # Second sweep must not duplicate the alert.
        assert check(db) == 0
        assert db.query(Alert).count() == 1


class TestWatchdogDeadMansSwitch:
    def test_missed_schedule_raises_alert(self, db):
        # cron fires at 02:00 daily; we're long past, and no run exists.
        job = _job(db, cron="0 2 * * *", alert_after=5)
        created = check(db)
        assert created >= 1
        alert = db.query(Alert).filter(Alert.type == "missed_schedule").first()
        assert alert is not None
        assert alert.job_id == job.id

    def test_no_alert_when_run_fired(self, db):
        # A run started today satisfies the schedule check.
        job = _job(db, cron="0 2 * * *", alert_after=5)
        db.add(Run(job_id=job.id, started_at=now_utc()))
        db.commit()
        assert check(db) == 0
        assert db.query(Alert).filter(Alert.type == "missed_schedule").count() == 0

    def test_no_alert_before_grace(self, db):
        # alert_after very large => not yet missed.
        job = _job(db, cron="*/10 * * * *", alert_after=100000)
        assert check(db) == 0

    def test_manual_job_no_cron_never_missed(self, db):
        job = _job(db, cron=None)
        assert check(db) == 0

    def test_invalid_cron_is_surfaced_not_crashing(self, db):
        job = _job(db, cron="not a valid cron")
        created = check(db)
        assert created >= 1
        assert db.query(Alert).filter(Alert.type == "invalid_cron").first() is not None

    def test_acknowledged_alert_allows_reissue_after_new_fire(self, db):
        job = _job(db, cron="0 2 * * *", alert_after=5)
        check(db)
        alert = db.query(Alert).filter(Alert.type == "missed_schedule").first()
        alert.acknowledged = True
        db.commit()
        # Still no run, grace elapsed -> a new un-acked alert status is open.
        # Idempotency key is "un-acknowledged alert exists"; acked one doesn't block.
        created = check(db)
        assert created >= 1
        fresh = db.query(Alert).filter(Alert.acknowledged.is_(False)).count()
        assert fresh >= 1