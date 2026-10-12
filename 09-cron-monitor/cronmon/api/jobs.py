"""Job registry endpoints: create, read, update, delete, trigger-now."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from cronmon.api.deps import get_job_or_404
from cronmon.database import get_db
from cronmon.models import Alert, Job, Run, now_utc
from cronmon.schemas import JobCreate, JobOut, JobUpdate, RunOut

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _job_out(job: Job) -> JobOut:
    """Build a JobOut with derived health/uptime fields."""
    latest = job.latest_run_obj()
    last_status = None
    last_duration = None
    last_run_at = None
    if latest is not None:
        last_run_at = latest.started_at
        last_duration = latest.duration_seconds
        last_status = latest.status if latest.ended_at else "running"

    idx_ok_7 = None
    if job.runs:
        seven_days = now_utc() - timedelta(days=7)
        recent = [r for r in job.runs if r.started_at >= seven_days]
        if recent:
            ok = sum(1 for r in recent if r.status == "ok")
            idx_ok_7 = round(100 * ok / len(recent), 2)

    # Health heuristic used by the dashboard badge.
    if not job.enabled:
        status_label = "disabled"
    elif latest is not None and latest.ended_at and latest.status == "fail":
        status_label = "failing"
    elif latest is not None and latest.ended_at is None:
        status_label = "running"
    else:
        status_label = "healthy"

    return JobOut(
        id=job.id,
        name=job.name,
        cron=job.cron,
        expected_duration=job.expected_duration,
        alert_after_minutes=job.alert_after_minutes,
        webhook_url=job.webhook_url,
        enabled=job.enabled,
        created_at=job.created_at,
        status=status_label,
        last_run_at=last_run_at,
        last_run_duration=last_duration,
        last_run_status=last_status,
        uptime_7d=idx_ok_7,
    )


@router.get("", response_model=list[JobOut])
def list_jobs(db: Session = Depends(get_db)) -> list[JobOut]:
    jobs = db.query(Job).order_by(Job.name).all()
    return [_job_out(j) for j in jobs]


@router.post("", response_model=JobOut, status_code=status.HTTP_201_CREATED)
def create_job(payload: JobCreate, db: Session = Depends(get_db)) -> JobOut:
    if db.query(Job).filter(Job.name == payload.name).first():
        raise HTTPException(status_code=409, detail="Job name already exists")
    job = Job(**payload.model_dump())
    db.add(job)
    db.commit()
    db.refresh(job)
    return _job_out(job)


@router.get("/{ident}", response_model=JobOut)
def get_job(ident: str, db: Session = Depends(get_db)) -> JobOut:
    return _job_out(get_job_or_404(db, ident))


@router.put("/{ident}", response_model=JobOut)
def update_job(ident: str, payload: JobUpdate, db: Session = Depends(get_db)) -> JobOut:
    job = get_job_or_404(db, ident)
    updates = {k: v for k, v in payload.model_dump(exclude_unset=True).items()}
    for key, value in updates.items():
        setattr(job, key, value)
    db.commit()
    db.refresh(job)
    return _job_out(job)


@router.delete("/{ident}", status_code=status.HTTP_204_NO_CONTENT)
def delete_job(ident: str, db: Session = Depends(get_db)) -> None:
    job = get_job_or_404(db, ident)
    db.delete(job)
    db.commit()


@router.post("/{ident}/trigger", response_model=RunOut)
def trigger_now(ident: str, db: Session = Depends(get_db)) -> Run:
    """Manual 'trigger now': opens a run as if the job had just started."""
    job = get_job_or_404(db, ident)
    run = Run(job_id=job.id, pinged_at=now_utc(), status="running")
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


@router.get("/{ident}/runs", response_model=list[RunOut])
def job_runs(
    ident: str,
    limit: int = Query(default=100, le=500),
    db: Session = Depends(get_db),
) -> list[Run]:
    job = get_job_or_404(db, ident)
    return (
        db.query(Run)
        .filter(Run.job_id == job.id)
        .order_by(Run.started_at.desc())
        .limit(limit)
        .all()
    )


__all__ = ["router", "_job_out"]