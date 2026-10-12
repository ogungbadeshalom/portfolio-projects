"""Task admin endpoints: list, show, schedule, cancel, retry, DLQ ops."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from scheduler import service
from scheduler.dlq import list_dlq, purge_dlq, retry_dlq
from scheduler.models import STATUS_PENDING, Task
from scheduler.store import get_session

router = APIRouter(prefix="/api", tags=["tasks"])


class ScheduleRequest(BaseModel):
    name: str
    payload: dict[str, Any] = {}
    at: datetime | None = None
    cron: str | None = None
    max_attempts: int | None = Field(default=None, ge=1)
    idempotency_key: str | None = None
    depends_on: int | None = None


@router.get("/tasks")
def list_tasks(
    status: str | None = None,
    name: str | None = None,
    limit: int = Query(default=100, le=1000),
) -> list[dict]:
    session = get_session()
    try:
        query = session.query(Task).order_by(Task.created_at.desc())
        if status:
            query = query.filter(Task.status == status)
        if name:
            query = query.filter(Task.name == name)
        return [service.task_summary(session, t) for t in query.limit(limit).all()]
    finally:
        session.close()


@router.get("/tasks/{task_id}")
def show_task(task_id: int) -> dict:
    session = get_session()
    try:
        task = session.get(Task, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="task not found")
        return service.task_summary(session, task)
    finally:
        session.close()


@router.post("/tasks")
def create_task(payload: ScheduleRequest) -> dict:
    try:
        task = service.schedule_task(
            payload.name,
            payload=payload.payload,
            at=payload.at,
            cron_expr=payload.cron,
            max_attempts=payload.max_attempts,
            idempotency_key=payload.idempotency_key,
            depends_on=payload.depends_on,
        )
    except service.TaskError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    session = get_session()
    try:
        task = session.get(Task, task.id)
        return service.task_summary(session, task)
    finally:
        session.close()


@router.post("/tasks/{task_id}/cancel")
def cancel_task(task_id: int) -> dict:
    if not service.cancel_task(task_id):
        raise HTTPException(status_code=409, detail="task not pending or missing")
    return {"id": task_id, "status": "canceled"}


@router.post("/tasks/{task_id}/retry")
def retry_task(task_id: int) -> dict:
    """Re-enqueue a dead-lettered task (alias of the DLQ retry)."""
    if not retry_dlq(task_id):
        raise HTTPException(status_code=409, detail="task not in dead-letter queue")
    return {"id": task_id, "status": "retried"}


# --------------------------------------------------------------------- DLQ
@router.get("/dlq")
def dlq(limit: int = Query(default=100, le=500)) -> list[dict]:
    return list_dlq(limit=limit)


@router.post("/dlq/{task_id}/retry")
def dlq_retry(task_id: int) -> dict:
    if not retry_dlq(task_id):
        raise HTTPException(status_code=404, detail="task not in DLQ")
    return {"id": task_id, "status": "retried"}


@router.post("/dlq/{task_id}/skip")
def dlq_skip(task_id: int) -> dict:
    if purge_dlq([task_id]) != 1:
        raise HTTPException(status_code=404, detail="task not in DLQ")
    return {"id": task_id, "status": "skipped"}


__all__ = ["router"]