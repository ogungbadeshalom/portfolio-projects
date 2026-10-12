"""End-to-end API tests: run lifecycle, jobs, alerts, auth, dashboard pages."""

from __future__ import annotations

import time

from fastapi.testclient import TestClient


def _register(client: TestClient, name="Backup", cron="0 2 * * *"):
    r = client.post("/api/jobs", json={"name": name, "cron": cron})
    assert r.status_code == 201, r.text
    return r.json()


def _headers(key: str) -> dict:
    return {"X-API-Key": key}


class TestAuth:
    def test_run_mutation_requires_key(self, client):
        r = client.post("/api/runs/start", json={"job": "Backup"})
        assert r.status_code == 401

    def test_wrong_key_rejected(self, client, api_key):
        _register(client)
        r = client.post(
            "/api/runs/start", json={"job": "Backup"}, headers=_headers("wrong")
        )
        assert r.status_code == 401


class TestRunLifecycle:
    def test_start_run(self, client, api_key):
        _register(client)
        r = client.post(
            "/api/runs/start", json={"job": "Backup"}, headers=_headers(api_key)
        )
        assert r.status_code == 201
        body = r.json()
        assert body["status"] == "running"
        assert body["ended_at"] is None
        assert body["job_id"] >= 1

    def test_start_unknown_job_404(self, client, api_key):
        r = client.post(
            "/api/runs/start", json={"job": "nope"}, headers=_headers(api_key)
        )
        assert r.status_code == 404

    def test_dedup_client_run_id(self, client, api_key):
        _register(client)
        h = _headers(api_key)
        first = client.post(
            "/api/runs/start",
            json={"job": "Backup", "client_run_id": "abc"},
            headers=h,
        )
        second = client.post(
            "/api/runs/start",
            json={"job": "Backup", "client_run_id": "abc"},
            headers=h,
        )
        assert first.json()["id"] == second.json()["id"]

    def test_ping_and_done(self, client, api_key):
        _register(client)
        h = _headers(api_key)
        run = client.post("/api/runs/start", json={"job": "Backup"}, headers=h).json()
        ping = client.post(f"/api/runs/{run['id']}/ping", headers=h)
        assert ping.status_code == 200
        assert ping.json()["pinged_at"] is not None

        done = client.post(
            f"/api/runs/{run['id']}/done", json={"status": "ok"}, headers=h
        )
        body = done.json()
        assert body["status"] == "ok"
        assert body["ended_at"] is not None
        assert body["duration_seconds"] is not None

    def test_ping_finished_run_conflicts(self, client, api_key):
        _register(client)
        h = _headers(api_key)
        run = client.post("/api/runs/start", json={"job": "Backup"}, headers=h).json()
        client.post(f"/api/runs/{run['id']}/done", json={"status": "ok"}, headers=h)
        r = client.post(f"/api/runs/{run['id']}/ping", headers=h)
        assert r.status_code == 409

    def test_done_fail_creates_alert(self, client, api_key):
        _register(client)
        h = _headers(api_key)
        run = client.post("/api/runs/start", json={"job": "Backup"}, headers=h).json()
        client.post(f"/api/runs/{run['id']}/done", json={"status": "fail"}, headers=h)
        alerts = client.get("/api/alerts").json()
        assert any(a["type"] == "run_failed" for a in alerts)


class TestJobs:
    def test_create_get_update_delete(self, client):
        job = _register(client, name="Reindex", cron="30 3 * * *")
        jid = job["id"]
        got = client.get(f"/api/jobs/{jid}")
        assert got.json()["name"] == "Reindex"

        # Duplicate name -> 409
        assert client.post("/api/jobs", json={"name": "Reindex"}).status_code == 409

        upd = client.put(f"/api/jobs/{jid}", json={"expected_duration": 900})
        assert upd.json()["expected_duration"] == 900

        assert client.delete(f"/api/jobs/{jid}").status_code == 204
        assert client.get(f"/api/jobs/{jid}").status_code == 404

    def test_trigger_now_opens_run(self, client):
        job = _register(client)
        r = client.post(f"/api/jobs/{job['id']}/trigger")
        assert r.status_code == 200
        runs = client.get(f"/api/jobs/{job['id']}/runs").json()
        assert len(runs) == 1

    def test_uptime_derived(self, client):
        _register(client)
        jobs = client.get("/api/jobs").json()
        assert {"status", "last_run_at", "uptime_7d"} <= set(jobs[0].keys())


class TestAlerts:
    def test_acknowledge(self, client, api_key):
        _register(client)
        h = _headers(api_key)
        run = client.post("/api/runs/start", json={"job": "Backup"}, headers=h).json()
        client.post(f"/api/runs/{run['id']}/done", json={"status": "fail"}, headers=h)
        alert_id = client.get("/api/alerts").json()[0]["id"]
        r = client.post(f"/api/alerts/{alert_id}/ack")
        assert r.json()["acknowledged"] is True
        assert client.get("/api/alerts/unacked-count").json()["count"] == 0

    def test_filter_by_ack_state(self, client, api_key):
        _register(client)
        h = _headers(api_key)
        run = client.post("/api/runs/start", json={"job": "Backup"}, headers=h).json()
        client.post(f"/api/runs/{run['id']}/done", json={"status": "fail"}, headers=h)
        acked = client.get("/api/alerts?acknowledged=false").json()
        assert len(acked) >= 1


class TestDashboard:
    def test_home_renders(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert "Cron Monitor" in r.text

    def test_job_page_renders(self, client):
        job = _register(client)
        r = client.get(f"/jobs/{job['id']}")
        assert r.status_code == 200
        assert "Backup" in r.text

    def test_dashboard_api_shape(self, client):
        r = client.get("/api/dashboard")
        body = r.json()
        assert set(body.keys()) == {"jobs", "stats", "alerts"}
        assert "total_jobs" in body["stats"]


class TestWebhookDelivery:
    def test_dispatch_posts_json_and_returns_true(self, db, primed_webhook):
        """dispatch() POSTs a structured payload and reports success."""
        from cronmon.alerting import dispatch
        from cronmon.models import Alert, Job

        url = primed_webhook["url"]
        job = Job(name="HookJob", webhook_url=url)
        db.add(job)
        db.flush()
        alert = Alert(job_id=job.id, type="missed_schedule", message="hello")
        db.add(alert)
        db.commit()
        db.refresh(alert)

        ok = dispatch(db, alert)
        assert ok is True
        received = primed_webhook["received"]
        assert len(received) == 1
        assert received[0]["type"] == "missed_schedule"
        assert received[0]["job_name"] == "HookJob"

    def test_dispatch_returns_false_without_webhook(self, db):
        from cronmon.alerting import dispatch
        from cronmon.models import Alert, Job

        job = Job(name="NoHook", webhook_url=None)
        db.add(job)
        db.commit()
        alert = Alert(job_id=job.id, type="run_failed", message="x")
        db.add(alert)
        db.commit()
        assert dispatch(db, alert) is False