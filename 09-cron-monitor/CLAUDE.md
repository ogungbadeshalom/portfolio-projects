# Cron Monitoring Dashboard

## Project Title
Cron Monitoring Dashboard (Python)

## Goal
Watchdog service that monitors scheduled jobs (cron, scheduled tasks). Each job pings the watchdog on start/end. Dashboard shows status, last run, duration, failures.

## Why this project
Operations engineering. Teaches: uptime monitoring, alerting, time-series data, status page generation, dead man's switch patterns.

## What You Build

A watchdog service + dashboard:

```bash
watchdog init                          # generate API key
watchdog ping JOB_ID                   # mark job as alive
watchdog start JOB_ID                  # job starting
watchdog done JOB_ID --status ok|fail  # job finished
watchdog schedule JOB_ID --cron "0 * * * *"
```

Plus a web dashboard at `http://localhost:9000/` showing:
- All registered jobs
- Last run time, duration, status
- 7-day uptime graph (per job)
- Alert history
- Manual "trigger now" button

## Tech
- **Python 3.11+**
- **FastAPI** (web + API)
- **SQLAlchemy** + **SQLite** (event storage)
- **Jinja2** (dashboard HTML templates)
- **HTMX** (dashboard interactivity, no React)
- **Chart.js** (uptime graph)
- **APScheduler** (check for missed heartbeats)

## Architecture

```
cronmon/
├── cronmon/
│   ├── __init__.py
│   ├── main.py             # FastAPI entry
│   ├── cli.py              # Click CLI for ping/start/done
│   ├── models.py           # Job, Run, Alert
│   ├── database.py
│   ├── watchdog.py         # Dead man's switch checker
│   ├── api/
│   │   ├── jobs.py         # CRUD for jobs
│   │   ├── runs.py         # Run lifecycle
│   │   └── alerts.py       # Alert endpoints
│   ├── templates/
│   │   ├── base.html
│   │   ├── dashboard.html
│   │   └── job.html
│   └── static/
│       └── chart.min.js
├── tests/
└── CLAUDE.md
```

## Build Order

1. **`models.py`** — Job (id, name, cron, expected_duration, alert_after_minutes), Run (id, job_id, started_at, ended_at, status), Alert (id, job_id, type, message, sent_at)
2. **`database.py`** — async engine, `get_db()` dep
3. **`cli.py`** — Click commands (init, ping, start, done, schedule)
4. **`api/runs.py`** — POST /runs/start, POST /runs/done, POST /runs/ping
5. **`watchdog.py`** — APScheduler job that checks for missed runs every minute, creates alerts
6. **`api/jobs.py`** — CRUD for jobs
7. **`templates/dashboard.html`** — job list with status indicators
8. **`templates/job.html`** — single job view with run history + uptime chart
9. **Alerts** — webhook to Slack/Discord/email when job fails

## Requirements

- Job registration: name, cron schedule, expected max duration, alert timeout
- Run lifecycle: start (creates run), ping (heartbeat), done (closes run with status)
- Auto-alert if job misses its schedule (dead man's switch)
- Auto-alert if run exceeds expected_duration
- Dashboard at `/` shows all jobs + status
- Job detail page at `/jobs/{id}` shows run history + uptime graph
- Auth: simple API key in header for CLI calls
- Web dashboard: read-only, no auth needed for MVP
- Webhook support: POST alert to Slack/Discord URL when alert fires
- Retention: keep last 90 days of runs

## Code Standards

- All API endpoints return JSON (no XML)
- Timestamps stored as UTC, displayed in user's local timezone
- Use `apscheduler` for background tasks (not threading)
- Watchdog is idempotent (safe to run multiple times concurrently)
- Errors logged with job_id + run_id context

## Verification

```bash
# Start watchdog server
uvicorn cronmon.main:app --port 9000

# Register a job
cronmon init
cronmon schedule --name "Backup" --cron "0 2 * * *" --max-duration 3600 --alert-after 7200

# Simulate a job lifecycle
cronmon start Backup
sleep 5
cronmon done Backup --status ok

# Visit dashboard
open http://localhost:9000/jobs/Backup

# Trigger watchdog to detect missed job
# (wait > 7200 minutes or shorten alert timeout)
```

## Stretch Goals

- Multi-tenant (multiple teams in one watchdog)
- Webhook to Slack/Discord/email with run logs
- Anomaly detection (run took 10x longer than usual)
- Maintenance windows (pause alerts during known downtime)
- Run dependencies (alert if Job B fails because Job A failed)
- Export run history to CSV/JSON
- Calendar view of all runs
- SLA tracking (% uptime per job)

## What You'll Learn

- Scheduled task monitoring
- Dead man's switch patterns
- Time-series data storage
- Status page generation
- Alert routing
- APScheduler background tasks
- HTMX for interactivity without React

## Time Estimate
8-12 hours for MVP with dashboard. 16-20 hours with alerting + auth + retention + tests.