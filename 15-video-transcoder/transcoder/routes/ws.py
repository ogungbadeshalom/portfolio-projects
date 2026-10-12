"""WebSocket endpoint for live transcode progress.

``/ws/jobs/{id}`` streams ``{"type":"job"|"progress", ...}`` events produced
by the queue's in-memory subscriber for that job, so the browser renders live
progress bars without polling.

The endpoint is robust to *when* a client connects:

* job already terminal  -> send one terminal snapshot and close
* job in flight         -> stream progress then the terminal event, then close
* job still queued      -> an internal poll guards against a missed event
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter()

TERMINAL = {"completed", "failed", "cancelled"}
_POLL_SECONDS = 1.0


def _snapshot(session, job_id: str) -> dict | None:
    """Build a terminal ``job`` event from the DB, or ``None`` if not done."""
    from .. import models

    job = models.get_job(session, job_id)
    if job is None:
        return None
    return {"type": "job", "job_id": job_id, **job.to_dict()}


@router.websocket("/ws/jobs/{job_id}")
async def ws_job_progress(websocket: WebSocket, job_id: str):
    await websocket.accept()
    queue = websocket.app.state.queue
    q = await queue.wait_for_job(job_id)

    def db_snapshot():
        session = websocket.app.state.session_factory()
        try:
            return _snapshot(session, job_id)
        finally:
            session.close()

    try:
        # Already-terminal jobs: send the snapshot and finish immediately.
        snapshot = db_snapshot()
        if snapshot is not None and snapshot.get("status") in TERMINAL:
            await websocket.send_json(snapshot)
            return

        while True:
            try:
                # Wait for the next queued/published event.
                event = await asyncio.wait_for(q.get(), timeout=_POLL_SECONDS)
            except asyncio.TimeoutError:
                # No event in a while: poll the DB in case a completion was
                # missed (e.g. we connected right as the job finished).
                now = db_snapshot()
                if now is not None and now.get("status") in TERMINAL:
                    await websocket.send_json(now)
                    break
                continue

            await websocket.send_json(event)
            if event.get("type") == "job" and event.get("status") in TERMINAL:
                break
    except WebSocketDisconnect:
        pass
    finally:
        queue.close_subscriber(job_id)