"""Alert dispatch: webhook delivery to Slack/Discord/generic endpoints.

The watchdog and the run-failure path both create :class:`Alert` rows; this
module is responsible for *delivering* them. A job may carry a ``webhook_url``
to which a JSON payload is POSTed. If no webhook is configured the alert is
retained in the DB (it still shows up in the dashboard / API) with a
``sent_at`` timestamp, which is the correct offline fallback.

Delivery is best-effort: failures are logged, never raised, so a broken
webhook can't take down the watchdog loop.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from sqlalchemy.orm import Session

from cronmon.models import Alert, Job
from cronmon.models import now_utc

logger = logging.getLogger("cronmon.alerting")


def alert_payload(alert: Alert, job: Job) -> dict[str, Any]:
    """Structured payload sent to webhooks + surfaced in the dashboard."""
    return {
        "alert_id": alert.id,
        "type": alert.type,
        "job_id": alert.id,
        "job_name": job.name,
        "message": alert.message,
        "run_id": alert.run_id,
        "sent_at": alert.sent_at.isoformat() + "Z",
    }


def dispatch(db: Session, alert: Alert) -> bool:
    """Deliver ``alert`` to its job's webhook (if any); always returns.

    Returns True when a webhook was successfully POSTed, False otherwise
    (no webhook configured, or delivery failed).
    """
    job = db.get(Job, alert.job_id)
    if job is None or not job.webhook_url:
        return False

    payload = alert_payload(alert, job)
    try:
        # Synchronous for simplicity + atomicity inside the request path;
        # a short timeout keeps a dead webhook from hanging the caller.
        resp = httpx.post(job.webhook_url, json=payload, timeout=5.0)
        success = 200 <= resp.status_code < 300
        if not success:
            logger.warning(
                "webhook returned %s for alert %s (job_id=%s)",
                resp.status_code,
                alert.id,
                job.id,
            )
        return success
    except httpx.HTTPError:
        logger.warning("webhook delivery failed for alert %s (job_id=%s)", alert.id, job.id)
        return False


def mark_sent(db: Session, alert: Alert) -> None:
    """Stamp ``sent_at`` for alerts retained without a webhook."""
    if alert.sent_at is None:
        alert.sent_at = now_utc()
        db.commit()


__all__ = ["dispatch", "mark_sent", "alert_payload"]