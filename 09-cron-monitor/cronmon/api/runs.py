"""Run lifecycle endpoints: start a run, ping it, mark it done.

A run is created whenever a job starts. Ping extends its heartbeat (used by
the dead-man's-switch watchdog to see it's still alive). Done closes the run
with a final ``ok``/``fail`` status and, on failure, raises an alert.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from cronmon import alerting
from cronmon.api.deps import get_job_or_404, require_key
from cronmon.database import get_db
from cronmon.models import Alert, Job, Run, now_utc
from cronmon.schemas import RunDone, RunOut, RunStart

router = APIRouter(prefix="/runs", tags=["runs"], dependencies=[Depends(require_key)])


@router.post("/start", response_model=RunOut, status_code=status.HTTP_201_CREATED)
def start_run(payload: RunStart, db: Session = Depends(get_db)) -> Run:
    """Open a new run for a job.

    The caller identifies the job by name or id. A ``client_run_id`` lets the
    caller deduplicate (a retried HTTP call won't open two runs).
    """
    job = get_job_or_404(db, payload.job)
    if not job.enabled:
        raise HTTPException(status_code=409, detail=f"Job {job.name!r} is disabled")

    if payload.client_run_id:
        existing = (
            db.query(Run)
            .filter(Run.job_id == job.id, Run.client_run_id == payload.client_run_id)
            .first()
        )
        if existing is not None:
            # At-least-once: return the already-open run instead of creating one.
            return existing

    run = Run(
        job_id=job.id,
        started_at=payload.started_at or now_utc(),
        pinged_at=now_utc(),
        status="running",
        client_run_id=payload.client_run_id,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


@router.post("/{run_id}/ping", response_model=RunOut)
def ping_run(run_id: int, db: Session = Depends(get_db)) -> Run:
    """Update a run's heartbeat so the watchdog knows it's still alive."""
    run = db.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.ended_at is not None:
        raise HTTPException(status_code=409, detail="Run is already finished")
    run.pinged_at = now_utc()
    db.commit()
    db.refresh(run)
    return run


@router.post("/{run_id}/done", response_model=RunOut)
def done_run(run_id: int, payload: RunDone, db: Session = Depends(get_db)) -> Run:
    """Close a run with a final status. Failures raise an alert."""
    run = db.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.ended_at is not None:
        # Re-done is a no-op that returns the current state (idempotent).
        return run

    run.ended_at = payload.ended_at or now_utc()
    run.status = payload.status
    db.commit()

    if payload.status == "fail":
        job = db.get(Job, run.job_id)
        alert = Alert(
            job_id=job.id,
            run_id=run.id,
            type="run_failed",
            message=f"Job {job.name!r} finished with status 'fail' "
            f"(started {run.started_at.isoformat()}, duration "
            f"{run.duration_seconds}s).",
        )
        db.add(alert)
        db.commit()
        alerting.dispatch(db, alert)

    db.refresh(run)
    return run


@router.get("", response_model=list[RunOut])
def list_runs(
    limit: int = 100,
    job: str | None = None,
    db: Session = Depends(get_db),
) -> list[Run]:
    """List recent runs, optionally filtered to one job."""
    query = db.query(Run)
    if job:
        job_obj = get_job_or_404(db, job)
        query = query.filter(Run.job_id == job_obj.id)
    return query.order_by(Run.started_at.desc()).limit(min(limit, 500)).all()


__all__ = ["router"]