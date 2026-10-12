"""FastAPI endpoint tests: API queries, dashboard pages, WS, SDK."""

from __future__ import annotations

import pytest

from analytics import query as q


def _seed(client):
    """Ingest a compact dataset via the API and force a flush."""
    spec = [
        ("signup", "a"), ("signup", "b"), ("signup", "c"),
        ("activate", "a"), ("activate", "b"),
        ("purchase", "a"),
        ("page_view", "a"), ("page_view", "a"),
    ]
    for event, uid in spec:
        client.post("/api/track", json={
            "event": event,
            "user_id": uid,
            "properties": {"url": {"page_view": "/home",
                                   "signup": "/pricing",
                                   "activate": "/welcome",
                                   "purchase": "/checkout"}.get(event, "/")},
        })
    client.app.state.pipe.flush()


class TestAPIEndpoints:
    def test_track_and_query_events(self, client):
        _seed(client)
        events = client.get("/api/events").json()
        assert len(events) == 8
        by_name = client.get("/api/events", params={"event": "page_view"}).json()
        assert len(by_name) == 2

    def test_events_filter_by_user(self, client):
        _seed(client)
        evs = client.get("/api/events", params={"user": "a"}).json()
        assert evs and all(e["user_id"] == "a" for e in evs)

    def test_funnel_endpoint(self, client):
        _seed(client)
        f = client.get("/api/funnel",
                       params={"steps": "signup,activate,purchase"}).json()
        assert [x["users"] for x in f] == [3, 2, 1]
        assert f[1]["conversion"] == pytest.approx(66.67, abs=0.5)

    def test_retention_endpoint_shape(self, client):
        _seed(client)
        out = client.get("/api/retention").json()
        assert isinstance(out, list)
        assert any(c["users"] >= 1 for c in out)
        assert "retention" in out[0]

    def test_top_pages_endpoint(self, client):
        _seed(client)
        pages = client.get("/api/top-pages").json()
        # signup occurred 3x (all /pricing) -> most-viewed.
        assert pages[0]["url"] == "/pricing"
        assert pages[0]["views"] == 3
        by_url = {p["url"]: p["views"] for p in pages}
        assert by_url["/home"] == 2

    def test_funnel_rejects_no_steps(self, client):
        r = client.get("/api/funnel", params={"steps": ""})
        assert r.status_code == 400


class TestPages:
    def test_dashboard_page_renders(self, client):
        r = client.get("/dashboard")
        assert r.status_code == 200
        assert "Analytics" in r.text

    def test_events_page_renders(self, client):
        _seed(client)
        r = client.get("/events")
        assert r.status_code == 200
        assert "page_view" in r.text

    def test_static_served(self, client):
        assert client.get("/static/style.css").status_code == 200
        assert client.get("/static/dashboard.js").status_code == 200
        assert client.get("/static/chart.umd.min.js").status_code == 200

    def test_sdk_served(self, client):
        r = client.get("/sdk/analytics.js")
        assert r.status_code == 200
        assert "analytics" in r.text


class TestDashboardAPI:
    def test_dashboard_json(self, client):
        _seed(client)
        data = client.get("/api/dashboard").json()
        assert data["counts"]["total"] == 8
        assert data["top_pages"]
        assert "retention" in data


class TestWebSocket:
    def test_ws_push_snapshot(self, client):
        _seed(client)
        with client.websocket_connect("/ws/dashboard") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "dashboard"
            assert msg["data"]["counts"]["total"] == 8