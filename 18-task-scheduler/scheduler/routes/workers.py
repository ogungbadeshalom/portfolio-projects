"""Worker status endpoints + dead-worker sweep."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter
from sqlalchemy import func

from scheduler.config import get_config
from scheduler.models import Worker, now_utc
from scheduler.store import get_session

router = APIRouter(prefix="/api", tags=["workers"])


def worker_liveness() -> tuple[list[dict], int, int]:
    """Snapshot workers: [rows], active count, dead count."""
    session = get_session()
    cfg = get_config()
    try:
        cutoff = now_utc() - timedelta(seconds=cfg.worker_timeout_seconds)
        rows = session.query(Worker).order_by(Worker.last_heartbeat.desc()).all()
        active = sum(1 for w in rows if w.last_heartbeat >= cutoff)
        out = [
            {
                "id": w.id,
                "hostname": w.hostname,
                "status": "active" if w.last_heartbeat >= cutoff else "dead",
                "last_heartbeat": w.last_heartbeat,
                "current_task_id": w.current_task_id,
                "tasks_completed": w.tasks_completed,
                "tasks_failed": w.tasks_failed,
            }
            for w in rows
        ]
        return out, active, len(rows) - active
    finally:
        session.close()


@router.get("/workers")
def list_workers() -> dict:
    workers, active, dead = worker_liveness()
    return {"workers": workers, "active": active, "dead": dead}


@router.post("/workers/sweep")
def sweep_workers() -> dict:
    """Mark stale workers offline (dead-worker detection)."""
    session = get_session()
    cfg = get_config()
    try:
        cutoff = now_utc() - timedelta(seconds=cfg.worker_timeout_seconds)
        stale = (
            session.query(Worker)
            .filter(Worker.last_heartbeat < cutoff, Worker.status != "offline")
            .all()
        )
        for w in stale:
            w.status = "offline"
        session.commit()
        return {"marked_offline": len(stale)}
    finally:
        session.close()


__all__ = ["router", "worker_liveness"]