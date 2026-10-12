"""Alert endpoints: list alerts, acknowledge, webhook config read."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from cronmon.database import get_db
from cronmon.models import Alert, Job
from cronmon.schemas import AlertOut

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("", response_model=list[AlertOut])
def list_alerts(
    job: str | None = None,
    acknowledged: bool | None = None,
    limit: int = 200,
    db: Session = Depends(get_db),
) -> list[Alert]:
    query = db.query(Alert)
    if job:
        query = query.join(Alert.job).filter(Job.name == job)
    if acknowledged is not None:
        query = query.filter(Alert.acknowledged == acknowledged)
    return query.order_by(Alert.sent_at.desc()).limit(limit).all()


@router.post("/{alert_id}/ack", response_model=AlertOut)
def acknowledge(alert_id: int, db: Session = Depends(get_db)) -> Alert:
    alert = db.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.acknowledged = True
    db.commit()
    db.refresh(alert)
    return alert


@router.get("/unacked-count")
def unacked_count(db: Session = Depends(get_db)) -> dict:
    count = db.query(Alert).filter(Alert.acknowledged.is_(False)).count()
    return {"count": count}


__all__ = ["router"]