"""Read-side analytics: events, top pages, funnels and retention cohorts.

Every function is fully parameterized (no string-interpolated SQL) and takes an
optional ``start``/``end`` window of unix seconds so callers can slice by time.
Funnel and retention are computed with SQL between well-defined steps.

Timestamps are stored as UTC Unix seconds; date-range filters are plain
``ts BETWEEN ? AND ?`` bounds.
"""

from __future__ import annotations

from typing import Any, List, Mapping, Optional, Sequence

from analytics.store import Store


def events_query(
    store: Store,
    *,
    event_name: Optional[str] = None,
    user_id: Optional[str] = None,
    start: Optional[int] = None,
    end: Optional[int] = None,
    limit: int = 200,
) -> List[Mapping[str, Any]]:
    """Query raw events with optional filters (date range, user, event name)."""
    clauses: List[str] = []
    params: List[Any] = []
    if event_name:
        clauses.append("event_name = ?")
        params.append(event_name)
    if user_id:
        clauses.append("user_id = ?")
        params.append(user_id)
    if start is not None:
        clauses.append("ts >= ?")
        params.append(int(start))
    if end is not None:
        clauses.append("ts < ?")
        params.append(int(end))
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(min(max(limit, 1), 1000))
    sql = (
        "SELECT id, event_name, user_id, session_id, ts, ts_iso, url, referrer, "
        "ip_anon, properties FROM events" + where + " ORDER BY ts DESC LIMIT ?"
    )
    rows = store.query(sql, params)
    return [dict(r) for r in rows]


def top_pages(
    store: Store,
    *,
    start: Optional[int] = None,
    end: Optional[int] = None,
    limit: int = 10,
) -> List[Mapping[str, Any]]:
    """Most-viewed URLs in the optional time window."""
    clauses = ["url IS NOT NULL AND url != ''"]
    params: List[Any] = []
    if start is not None:
        clauses.append("ts >= ?")
        params.append(int(start))
    if end is not None:
        clauses.append("ts < ?")
        params.append(int(end))
    params.append(min(max(limit, 1), 100))
    sql = (
        "SELECT url, COUNT(*) AS views, COUNT(DISTINCT user_id) AS unique_users "
        "FROM events WHERE "
        + " AND ".join(clauses)
        + " GROUP BY url ORDER BY views DESC LIMIT ?"
    )
    return [dict(r) for r in store.query(sql, params)]


def total_events(
    store: Store,
    *,
    start: Optional[int] = None,
    end: Optional[int] = None,
) -> int:
    """Total events in the window (falls back to the daily rollup)."""
    if start is None and end is None:
        return int(store.scalar("SELECT COUNT(*) FROM events") or 0)
    clauses = []
    params: List[Any] = []
    if start is not None:
        clauses.append("ts >= ?")
        params.append(int(start))
    if end is not None:
        clauses.append("ts < ?")
        params.append(int(end))
    return int(
        store.scalar(
            "SELECT COUNT(*) FROM events WHERE " + " AND ".join(clauses), params
        )
        or 0
    )


def funnel(
    store: Store,
    steps: Sequence[str],
    *,
    start: Optional[int] = None,
    end: Optional[int] = None,
    window_seconds: int = 3600 * 24,
) -> List[Mapping[str, Any]]:
    """Funnel analysis: conversions across an ordered set of event steps.

    For each step we report how many distinct users reached it, and the
    step-over-step conversion rate. A user counts toward step *i* (i >= 1) only
    if they reached all previous steps first (within ``window_seconds`` of the
    first step). Returns a row per step with ``users`` and ``conversion``.

    The algorithm is faithful and parametric: it fetches, per user+event, the
    earliest timestamp in window, then walks the steps in Python, tracking the
    earliest time each user completed each step so user-time monotonicity is
    preserved without unbounded SQL.
    """
    if not steps:
        return []
    start_v = start
    end_v = end

    # Build, per step, a dict user_id -> earliest event_ts (within window).
    step_first: List[dict[str, int]] = []
    for step in steps:
        sql = (
            "SELECT user_id, MIN(ts) AS ts FROM events "
            "WHERE event_name = ?"
        )
        params: List[Any] = [step]
        if start_v is not None:
            sql += " AND ts >= ?"
            params.append(int(start_v))
        if end_v is not None:
            sql += " AND ts < ?"
            params.append(int(end_v))
        sql += " GROUP BY user_id"
        first: dict[str, int] = {}
        for row in store.query(sql, params):
            first[row["user_id"]] = row["ts"]
        step_first.append(first)

    reached_before: dict[str, int] = {}  # user -> earliest ts after prev step
    result: List[Mapping[str, Any]] = []
    total_at_first = len(step_first[0]) if step_first else 0

    for idx, step in enumerate(steps):
        first_map = step_first[idx]
        if idx == 0:
            reached_before = dict(first_map)  # everyone who did step 0 qualifies
            users = len(reached_before)
        else:
            reached: dict[str, int] = {}
            for user, prev_ts in reached_before.items():
                ft = first_map.get(user)
                if ft is None:
                    continue
                # Must advance within the window after the previous step.
                if 0 <= ft - prev_ts <= window_seconds:
                    reached[user] = ft
            users = len(reached)
            reached_before = reached
        conversion = (users / total_at_first * 100) if total_at_first else 0.0
        result.append(
            {
                "step": step,
                "users": users,
                "conversion": round(conversion, 2),
            }
        )
    return result


def retention_cohorts(
    store: Store,
    *,
    start: Optional[int] = None,
    end: Optional[int] = None,
    days: int = 7,
) -> List[Mapping[str, Any]]:
    """Day-0 cohort retention: % of each signup-day cohort active on day N.

    A user's cohort is the UTC day of their first ``signup`` (or ``activate``)
    event. Active on day *N* means they emitted **any** event on the
    cohort-start + N calendar day. Returns one row per cohort with a list of
    percentages length ``days+1`` (day 0 is always 100%).
    """
    cohort_event = "signup"  # primary anchor; fall back if absent
    # Determine the signup cohort per user.
    sql = (
        "SELECT user_id, MIN(ts) AS ts FROM events "
        "WHERE event_name = ? GROUP BY user_id"
    )
    params: List[Any] = [cohort_event]
    if start is not None:
        sql = sql.replace(" GROUP BY user_id", " AND ts >= ? GROUP BY user_id")
        params.append(int(start))
    if end is not None:
        sql = sql.replace(" GROUP BY user_id", " AND ts < ? GROUP BY user_id")
        params.append(int(end))

    cohort_day: dict[str, int] = {}
    for row in store.query(sql, params):
        cohort_day[row["user_id"]] = _day(row["ts"])

    if not cohort_day:
        return []

    # All (user, day) pairs of activity from these users, for indicators.
    user_ids = list(cohort_day.keys())
    placeholders = ",".join("?" * len(user_ids))
    activity_sql = (
        "SELECT user_id, ts FROM events WHERE user_id IN ({})".format(placeholders)
    )
    if start is not None:
        activity_sql += " AND ts >= ?"
        user_ids = list(user_ids) + [int(start)]
    if end is not None:
        activity_sql += " AND ts < ?"
        user_ids = list(user_ids) + [int(end)]
    active_days: dict[str, set[int]] = {}
    for row in store.query(activity_sql, user_ids):
        active_days.setdefault(row["user_id"], set()).add(_day(row["ts"]))

    group: dict[int, list[str]] = {}
    for user, day in cohort_day.items():
        group.setdefault(day, []).append(user)

    output: List[Mapping[str, Any]] = []
    for day, users in sorted(group.items()):
        total = max(len(users), 1)
        cohort: dict[str, int] = {}
        for user in users:
            cohort[user] = 1
        retention = []
        for n in range(days + 1):
            target_day = day + n * 86400
            active = sum(1 for u in users if target_day in active_days.get(u, set()))
            retention.append(round(active / total * 100, 2))
        output.append(
            {
                "cohort_day": day,
                "cohort_date": _iso_day(day),
                "users": len(users),
                "retention": retention,
            }
        )
    return output


# -- dashboard ----------------------------------------------------------------
def dashboard(
    store: Store,
    *,
    window_seconds: int = 86400,
) -> Mapping[str, Any]:
    """One call that aggregates everything the dashboard needs."""
    now = _now_utc()
    start_24h = now - 86400
    start_1h = now - 3600
    start_5m = now - 300
    # Windows are lower-bounded (ts >= start) rather than upper-bounded so an
    # event stamped "now" is included even when queried within the same second.
    return {
        "now": now,
        "window_seconds": window_seconds,
        "counts": {
            "last_5m": total_events(store, start=start_5m),
            "last_1h": total_events(store, start=start_1h),
            "last_24h": total_events(store, start=start_24h),
            "total": total_events(store),
        },
        "top_pages": top_pages(store, start=start_24h, limit=10),
        "retention": retention_cohorts(
            store, start=start_24h - 30 * 86400, days=7
        ),
    }


# -- small helpers ------------------------------------------------------------
def _day(unix_ts: int) -> int:
    return int(unix_ts) - (int(unix_ts) % 86400)


def _iso_day(unix_day: int) -> str:
    import datetime as _dt
    import time

    return _dt.datetime.fromtimestamp(
        unix_day, tz=_dt.timezone.utc
    ).strftime("%Y-%m-%d")


def _now_utc() -> int:
    import time

    return int(time.time())


__all__ = [
    "events_query",
    "top_pages",
    "total_events",
    "funnel",
    "retention_cohorts",
    "dashboard",
]