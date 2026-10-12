"""FastAPI API tests: scheduling, workers, DLQ, metrics, dashboard pages."""

from __future__ import annotations

import time


class TestScheduling:
    def test_immediate_task_runs_to_done(self, client):
        task = client.post(
            "/api/tasks", json={"name": "add", "payload": {"a": 1, "b": 2}}
        ).json()
        tid = task["id"]
        status = task["status"]
        for _ in range(60):
            info = client.get(f"/api/tasks/{tid}").json()
            status = info["status"]
            if status in ("done", "failed", "dead"):
                break
            time.sleep(0.1)
        assert status == "done"
        assert client.get(f"/api/tasks/{tid}").json()["runs"][0]["result"] == "3.0"

    def test_unknown_task_rejected(self, client):
        r = client.post("/api/tasks", json={"name": "does_not_exist"})
        assert r.status_code == 400

    def test_schedule_future_task_is_pending(self, client):
        from datetime import datetime, timedelta, timezone

        fut = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        r = client.post(
            "/api/tasks", json={"name": "send_email", "payload": {"to": "a@b.co"}, "at": fut}
        )
        assert r.status_code == 200
        assert r.json()["status"] == "pending"

    def test_schedule_cron_task(self, client):
        r = client.post("/api/tasks", json={"name": "cleanup", "cron": "*/5 * * * *"})
        assert r.status_code == 200
        assert r.json()["cron"] == "*/5 * * * *"

    def test_list_and_show(self, client):
        client.post("/api/tasks", json={"name": "add", "payload": {"a": 1, "b": 2}})
        assert len(client.get("/api/tasks").json()) >= 1
        tasks = client.get("/api/tasks?name=add").json()
        assert tasks and tasks[0]["name"] == "add"

    def test_cancel_pending(self, client):
        from datetime import datetime, timedelta, timezone

        fut = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()
        tid = client.post("/api/tasks", json={"name": "cleanup", "at": fut}).json()["id"]
        r = client.post(f"/api/tasks/{tid}/cancel")
        assert r.status_code == 200
        assert client.get(f"/api/tasks/{tid}").json()["status"] == "canceled"


class TestDeadLetter:
    def test_dlq_flows(self, client):
        # A task that exhausts its attempts lands in the DLQ.
        tid = client.post(
            "/api/tasks", json={"name": "fail_task", "payload": {}, "max_attempts": 1}
        ).json()["id"]
        for _ in range(80):
            info = client.get(f"/api/tasks/{tid}").json()
            if info["status"] in ("dead", "done"):
                break
            time.sleep(0.15)
        assert info["status"] == "dead"

        dlq = client.get("/api/dlq").json()
        assert dlq and dlq[0]["last_error"]

        # Retry re-enqueues, fails again -> dead again (idempotent retry path ok).
        assert client.post(f"/api/dlq/{tid}/retry").status_code == 200

        # Wait for the auto-started worker to re-fail the retried task.
        for _ in range(80):
            info = client.get(f"/api/tasks/{tid}").json()
            if info["status"] in ("dead", "done"):
                break
            time.sleep(0.15)
        assert info["status"] == "dead"

        # Skip/purge removes it.
        r = client.post(f"/api/dlq/{tid}/skip")
        assert r.status_code == 200
        assert len(client.get("/api/dlq").json()) == 0

    def test_retry_unknown_dlq_404(self, client):
        assert client.post("/api/dlq/999999/retry").status_code == 404


class TestWorkers:
    def test_worker_listing(self, client):
        r = client.get("/api/workers")
        assert r.status_code == 200
        assert "workers" in r.json()
        assert r.json()["active"] >= 1  # auto-started pool heartbeats in


class TestMetrics:
    def test_metrics_text(self, client):
        r = client.get("/metrics")
        assert r.status_code == 200
        assert "prometheus" in r.text.lower() or "scheduler_" in r.text

    def test_metrics_json(self, client):
        r = client.get("/metrics?format=json")
        assert r.status_code == 200
        body = r.json()
        assert "tasks_pending" in body
        assert "workers_active" in body


class TestDashboard:
    def test_pages_render(self, client):
        assert client.get("/").status_code == 200
        assert client.get("/tasks").status_code == 200
        assert client.get("/dlq").status_code == 200
        assert client.get("/static/style.css").status_code == 200

    def test_task_detail_page(self, client):
        tid = client.post("/api/tasks", json={"name": "add", "payload": {"a": 1, "b": 2}}).json()["id"]
        assert client.get(f"/tasks/{tid}").status_code == 200
        assert client.get("/tasks/999999").status_code == 404