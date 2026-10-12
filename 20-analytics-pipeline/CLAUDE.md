# Analytics Pipeline (Event Ingestion → OLAP → Dashboard)

## Project Title
Analytics Pipeline (Event Ingestion → OLAP → Dashboard)

## Goal
A complete analytics platform: high-volume event ingestion, storage in columnar OLAP format, query engine, dashboard with charts.

## Why this project
This is what companies like Mixpanel, Amplitude, PostHog build. Teaches: event schemas, ingestion patterns, time-series data, OLAP vs OLTP, query optimization, real-time dashboards.

## What You Build
A working analytics pipeline:

```
Client (browser):
  fetch('/api/track', {
    method: 'POST',
    body: JSON.stringify({
      event: 'page_view',
      user_id: 'user-123',
      properties: { url: '/home', referrer: 'google' },
      timestamp: '2026-07-15T10:00:00Z'
    })
  })

Server:
  POST /api/track                    # ingest event (async queue)
  GET  /api/events                    # query events (with filters)
  GET  /api/funnel                    # funnel analysis
  GET  /api/retention                 # retention cohorts
  GET  /api/top-pages                 # top pages by views
  GET  /api/dashboard                 # full dashboard data
  WS   /ws/dashboard                   # live updates
```

Web dashboard:
- Real-time event counter (last 5 minutes, 1 hour, 24 hours)
- Top pages table
- Funnel chart (signup → activation → purchase)
- Retention cohort heatmap
- Custom date range picker

## Tech
- **Python 3.11+**
- **FastAPI** (ingestion API + dashboard backend)
- **ClickHouse** (OLAP database, columnar, fast aggregations) OR **DuckDB** (embedded, easier setup)
- **asyncio.Queue** (in-memory event queue, batch write)
- **Redis** (session cache, rate limiting, optional)
- **HTMX + Alpine.js** (dashboard frontend, no React)
- **Chart.js** (charts)
- **WebSocket** (live updates)

## Architecture

```
analytics/
├── analytics/
│   ├── __init__.py
│   ├── main.py             # FastAPI entry
│   ├── ingestion.py        # POST /api/track, async batching
│   ├── query.py            # GET endpoints (funnel, retention, top pages)
│   ├── schema.py           # ClickHouse table DDL
│   ├── models.py           # Pydantic models for events
│   ├── ws.py               # live dashboard updates
│   ├── templates/
│   │   ├── base.html
│   │   ├── dashboard.html
│   │   └── widget.html
│   ├── static/
│   │   ├── chart.min.js
│   │   ├── alpine.min.js
│   │   └── dashboard.js
│   ├── sdk/
│   │   └── analytics.js   # browser SDK to embed
│   └── config.py
├── tests/
└── CLAUDE.md
```

## Build Order

1. **`schema.py`** — ClickHouse table: events (timestamp DateTime, user_id String, event_name LowCardinality(String), properties JSON, session_id String, ip IPv4)
2. **`models.py`** — Pydantic Event model with validation
3. **`ingestion.py`** — POST /api/track, enqueues event to asyncio.Queue, batch flush every 100ms or 1000 events
4. **`schema.py`** — materialized views for hourly/daily aggregations
5. **`query.py`** — query functions: `events_by_name`, `top_pages`, `funnel(steps)`, `retention_cohorts`
6. **`main.py`** — FastAPI with /api/track, /api/dashboard endpoints
7. **`templates/dashboard.html`** — Alpine.js + HTMX dashboard with live counters
8. **`ws.py`** — WebSocket broadcasts new event counts every 5 seconds
9. **`sdk/analytics.js`** — browser SDK: `analytics.track(event, props)`, auto page views
10. **Tests** — ingestion batching, query correctness, dashboard render

## Requirements

- Ingestion endpoint accepts JSON events with flexible schema
- Events batch-written to OLAP (100ms flush interval or 1000 events)
- Query endpoint supports filters: date range, user_id, event_name
- Funnel analysis: define steps, get conversion rate between each
- Retention: cohort table showing % users returning N days after signup
- Top pages: most-viewed URLs in time window
- Real-time counter: events per second/minute/hour (last 24h)
- Dashboard renders without page reload (HTMX + Alpine.js)
- Browser SDK: drop-in script that tracks page views, clicks, custom events
- Auto-flush on server shutdown (don't lose events)

## Code Standards

- All ingestion is async (don't block on DB write)
- Events validated server-side (Pydantic) — reject malformed
- Batch insert into OLAP (not row-by-row)
- Queries use materialized views (pre-aggregated)
- Date filtering uses timezone-aware timestamps (UTC storage, local display)
- Session ID generated client-side (cookie + fingerprint)
- Properties stored as JSON (flexible schema per event)
- IP addresses anonymized (last octet zeroed for GDPR)
- All queries parameterized (no SQL injection)
- WebSocket reconnects automatically on disconnect

## Verification

```bash
# Start ClickHouse
docker run -d -p 8123:8123 -p 9000:9000 clickhouse/clickhouse-server

# Start server
uvicorn analytics.main:app --port 8080

# Send test events
for i in {1..1000}; do
  curl -X POST http://localhost:8080/api/track \
    -H "Content-Type: application/json" \
    -d "{\"event\":\"page_view\",\"user_id\":\"user-$((RANDOM%100))\",\"properties\":{\"url\":\"/page-$((RANDOM%10))\"},\"timestamp\":\"$(date -Iseconds)\"}"
done

# Query
curl "http://localhost:8080/api/top-pages?hours=1"

# Dashboard
open http://localhost:8080/dashboard

# Browser SDK test
echo '<script src="http://localhost:8080/sdk/analytics.js"></script>' > /tmp/test.html
open /tmp/test.html

# Run tests
pytest tests/ -v
```

## Stretch Goals

- Custom event properties in query builder
- A/B test analysis (split users into cohorts, compare metrics)
- Cohort retention heatmap visualization
- Real-time alerting (send Slack notification if conversions drop)
- Multi-tenant (separate projects with isolated data)
- Data export (CSV/JSON for compliance)
- Anomaly detection (alert on unusual traffic patterns)
- Funnel comparison (compare funnels across time periods)
- Sampling (track only 10% of events for cost reduction)

## What You'll Learn

- Event ingestion patterns (async batching)
- OLAP vs OLTP databases (columnar storage, aggregations)
- Time-series data handling
- Funnel and retention analysis
- Real-time dashboard updates via WebSocket
- Browser SDK patterns (global object, auto-events)
- Materialized views for query performance
- Anonymization for GDPR compliance

## Time Estimate
16-20 hours for MVP. 30-40 hours with funnel + retention + browser SDK + live dashboard.