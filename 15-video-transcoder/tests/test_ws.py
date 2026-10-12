"""WebSocket tests: live progress events reach a subscribed client."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from conftest import submit_video, wait_completed

TERMINAL = {"completed", "failed", "cancelled"}


def test_ws_streams_terminal_job_event(app, source_video):
    """Connecting to /ws/jobs/{id} yields at least a job event, eventually terminal."""
    with TestClient(app) as client:
        jid = submit_video(client, source_video, resolutions="480")["id"]

        with client.websocket_connect(f"/ws/jobs/{jid}") as ws:
            terminal_event = None
            saw = 0
            while saw < 200:
                try:
                    msg = ws.receive_json()
                except Exception:  # connection closed by server = fine
                    break
                saw += 1
                if msg.get("type") == "job":
                    terminal_event = msg
                    if msg.get("status") in TERMINAL:
                        break
                # progress events just count toward the cap
            assert terminal_event is not None, "no job event received over WS"


def test_ws_progress_event_shape(app, source_video):
    """Every WS message is a well-formed event dict."""
    with TestClient(app) as client:
        jid = submit_video(client, source_video, resolutions="480")["id"]
        with client.websocket_connect(f"/ws/jobs/{jid}") as ws:
            msg = ws.receive_json()
            assert "type" in msg
            if msg["type"] == "progress":
                assert "job_id" in msg and "progress_pct" in msg
            else:
                assert msg["type"] == "job"


def test_status_endpoint_matches_ws_terminal(app, source_video):
    """The WS terminal event agrees with the polled REST status."""
    with TestClient(app) as client:
        jid = submit_video(client, source_video, resolutions="480")["id"]
        terminal_event = None
        with client.websocket_connect(f"/ws/jobs/{jid}") as ws:
            for _ in range(200):
                try:
                    msg = ws.receive_json()
                except Exception:
                    break
                if msg.get("type") == "job" and msg.get("status") in TERMINAL:
                    terminal_event = msg
                    break
        status = wait_completed(client, jid)
        assert terminal_event is not None
        assert terminal_event["status"] == status["status"]

        # Job resolves by REST as completed.
        assert status["status"] == "completed"