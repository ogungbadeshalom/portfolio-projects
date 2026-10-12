"""End-to-end analytics: ingest a realistic dataset, then assert real numbers
for funnel, retention, top-pages and dashboard counts.
"""

from __future__ import annotations

from analytics import query as q
from analytics.models import Event


def _ingest(client, model_events):
    """Ingest via the real API (async queue) into the app's store."""
    for e in model_events:
        client.post("/api/track", json=e.model_dump(mode="json"))
    client.app.state.pipe.flush()


def test_top_pages_counts_and_uniques(client):
    store = client.store
    _ingest(
        client,
        [
            Event(event="page_view", user_id="a", properties={"url": "/home"}),
            Event(event="page_view", user_id="b", properties={"url": "/home"}),
            Event(event="page_view", user_id="a", properties={"url": "/about"}),
        ],
    )
    pages = q.top_pages(store, limit=5)
    assert pages[0]["url"] == "/home"
    assert pages[0]["views"] == 2
    assert pages[0]["unique_users"] == 2
    assert pages[1]["url"] == "/about"
    assert pages[1]["views"] == 1


def test_top_pages_honors_time_window(store):
    # Historical event (old ts) must not appear in a recent window.
    import json

    old = 1_000_000  # 1970-ish
    store.execute(
        "INSERT INTO events (event_name,user_id,ts,ts_iso,url,properties) "
        "VALUES (?,?,?,?,?,?)",
        ("page_view", "a", old, "1970-01-01T00:00:00+00:00", "/old",
         json.dumps({})),
    )
    pages = q.top_pages(store, start=2_000_000, limit=5)
    assert pages == []
    pages_all = q.top_pages(store, limit=5)
    assert pages_all[0]["url"] == "/old"


def test_funnel_conversion(store):
    # funnel: 10 signup, 6 activate, 3 purchase -> 100/60/30
    for i in range(10):
        _row(store, "signup", f"u{i}", 1000 + i)
    for i in range(6):
        _row(store, "activate", f"u{i}", 2000 + i)
    for i in range(3):
        _row(store, "purchase", f"u{i}", 3000 + i)

    funnel = q.funnel(store, ["signup", "activate", "purchase"],
                      window_seconds=1000 * 60)
    assert [f["users"] for f in funnel] == [10, 6, 3]
    assert funnel[1]["conversion"] == 60.0
    assert funnel[2]["conversion"] == 30.0


def test_funnel_respects_step_order(store):
    # A user who purchases without activating must NOT count in activate.
    _row(store, "signup", "a", 1000)
    _row(store, "purchase", "a", 2000)  # skipped activate
    _row(store, "signup", "b", 1000)
    _row(store, "activate", "b", 2000)
    funnel = q.funnel(store, ["signup", "activate", "purchase"])
    assert funnel[0]["users"] == 2
    assert funnel[1]["users"] == 1
    assert funnel[2]["users"] == 0


def test_retention_percentage(store):
    DAY = 86400
    base = 10 * DAY  # a cohort "day 0"
    # u1 active on day 0 and day 1; u2 active on day 0 only
    _row(store, "signup", "u1", base)
    _row(store, "page_view", "u1", base + DAY)  # day 1
    _row(store, "signup", "u2", base)
    out = q.retention_cohorts(store, days=3)
    assert out, "expected at least one cohort"
    assert out[0]["retention"][0] == 100.0  # day 0 is everyone
    assert out[0]["retention"][1] == 50.0   # 1 of 2 returned on day 1
    assert out[0]["retention"][2] == 0.0


def test_dashboard_counts(client):
    # Three events now (fresh store).
    store = client.store
    for i in range(3):
        client.post("/api/track",
                    json={"event": "page_view", "user_id": f"u{i}",
                          "properties": {"url": "/x"}})
    client.app.state.pipe.flush()
    data = q.dashboard(store)
    assert data["counts"]["total"] == 3
    assert data["counts"]["last_24h"] == 3
    assert data["counts"]["last_5m"] == 3
    assert data["top_pages"][0]["views"] == 3


def _row(store, event_name, user_id, ts, url=None):
    import json
    import datetime as _dt

    iso = _dt.datetime.fromtimestamp(ts, tz=_dt.timezone.utc).isoformat()
    store.execute(
        "INSERT INTO events (event_name,user_id,ts,ts_iso,url,properties) "
        "VALUES (?,?,?,?,?,?)",
        (event_name, user_id, ts, iso, url, json.dumps({"url": url})),
    )