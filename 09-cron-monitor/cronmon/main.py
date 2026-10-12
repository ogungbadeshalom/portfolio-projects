"""FastAPI application for the cron monitoring dashboard.

Serves the JSON API (jobs/runs/alerts), the Jinja2 web dashboard at ``/``,
and wires up the APScheduler background job that runs the watchdog sweep every
minute. Templates/static live inside the package so the app is relocatable.

Run::

    uvicorn cronmon.main:app --port 9000

The ``get_app`` factory makes test setups trivial (fresh DB, no scheduler).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from cronmon.api import alerts_router, jobs_router, runs_router
from cronmon.database import SessionLocal, init_db
from cronmon.models import Alert, Job, Run, now_utc
from cronmon.watchdog import check as watchdog_check

logger = logging.getLogger("cronmon.main")

PACKAGE_DIR = __import__("pathlib").Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(PACKAGE_DIR / "templates"))


def _dashboard_context(db: Session) -> dict:
    """Assemble the data the dashboard + dashboard JSON endpoint render."""
    jobs = db.query(Job).order_by(Job.name).all()

    job_rows = []
    for job in jobs:
        latest = job.latest_run_obj()
        row = {
            "id": job.id,
            "name": job.name,
            "cron": job.cron,
            "enabled": job.enabled,
            "expected_duration": job.expected_duration,
            "alert_after_minutes": job.alert_after_minutes,
            "status": "healthy",
            "last_run_at": None,
            "last_run_duration": None,
            "last_run_status": None,
            "uptime_7d": None,
        }
        if latest is not None:
            row["last_run_at"] = latest.started_at
            row["last_run_duration"] = latest.duration_seconds
            row["last_run_status"] = latest.status if latest.ended_at else "running"
            if not job.enabled:
                row["status"] = "disabled"
            elif latest.ended_at and latest.status == "fail":
                row["status"] = "failing"
            elif latest.ended_at is None:
                row["status"] = "running"
        seven = now_utc() - timedelta(days=7)
        recent = [r for r in job.runs if r.started_at >= seven]
        if recent and any(r.ended_at for r in recent):
            ok = sum(1 for r in recent if r.status == "ok" and r.ended_at)
            row["uptime_7d"] = round(100 * ok / sum(1 for r in recent if r.ended_at), 2)
        job_rows.append(row)

    stats = {
        "total_jobs": len(jobs),
        "running": sum(1 for r in job_rows if r["status"] == "running"),
        "healthy": sum(1 for r in job_rows if r["status"] == "healthy"),
        "failing": sum(1 for r in job_rows if r["status"] == "failing"),
        "total_runs_24h": db.query(Run)
        .filter(Run.started_at >= now_utc() - timedelta(hours=24))
        .count(),
        "active_alerts": db.query(Alert)
        .filter(Alert.acknowledged.is_(False))
        .count(),
    }

    alerts = (
        db.query(Alert)
        .order_by(Alert.sent_at.desc())
        .limit(50)
        .all()
    )
    return {"jobs": job_rows, "stats": stats, "alerts": alerts}


def create_app(*, enable_scheduler: bool = True) -> FastAPI:
    """Build a configured FastAPI instance.

    Parameters
    ----------
    enable_scheduler : bool
        When True (default), start the APScheduler watchdog loop on startup.
        Tests pass False so they can drive the watchdog explicitly.
    """
    scheduler = {"obj": None}

    # Tables are created synchronously so the app works even when a client
    # (e.g. a bare TestClient) never runs the lifespan startup.
    init_db(seed=True)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if enable_scheduler:
            scheduler["obj"] = _start_scheduler()
        try:
            yield
        finally:
            if scheduler["obj"] is not None:
                scheduler["obj"].shutdown(wait=False)

    app = FastAPI(title="Cron Monitor", version="0.1.0", lifespan=lifespan)

    # ------------------------------------------------------------------ API
    app.include_router(jobs_router, prefix="/api")
    app.include_router(runs_router, prefix="/api")
    app.include_router(alerts_router, prefix="/api")

    @app.get("/api/dashboard")
    def api_dashboard():
        db = SessionLocal()
        try:
            return _dashboard_context(db)
        finally:
            db.close()

    @app.get("/api/health")
    def health():
        return {"status": "ok", "time": now_utc().isoformat() + "Z"}

    # ---------------------------------------------------------------- Pages
    @app.get("/", response_class=HTMLResponse)
    def dashboard(request: Request):
        db = SessionLocal()
        try:
            ctx = _dashboard_context(db)
            return templates.TemplateResponse(
                request,
                "dashboard.html",
                {"request": request, **ctx},
            )
        finally:
            db.close()

    @app.get("/jobs/{ident}", response_class=HTMLResponse)
    def job_detail(request: Request, ident: str):
        db = SessionLocal()
        try:
            if ident.isdigit():
                job = db.get(Job, int(ident))
            else:
                job = db.query(Job).filter(Job.name == ident).first()
            if job is None:
                return HTMLResponse("Job not found", status_code=404)
            after = now_utc() - timedelta(days=7)
            runs = (
                db.query(Run)
                .filter(Run.job_id == job.id, Run.started_at >= after)
                .order_by(Run.started_at)
                .all()
            )
            alerts = (
                db.query(Alert)
                .filter(Alert.job_id == job.id)
                .order_by(Alert.sent_at.desc())
                .limit(20)
                .all()
            )
            # Build an uptime series: per day fractional "ok" share.
            chart = _uptime_series(runs)
            return templates.TemplateResponse(
                request,
                "job.html",
                {
                    "request": request,
                    "job": job,
                    "runs": list(reversed(runs[-100:])),
                    "alerts": alerts,
                    "chart": chart,
                },
            )
        finally:
            db.close()

    # ----------------------------------------------------------- Assets
    app.mount(
        "/static",
        StaticFiles(directory=str(PACKAGE_DIR / "static")),
        name="static",
    )

    return app


def _uptime_series(runs: list[Run]) -> dict[str, list]:
    """Per-day uptime (%) over the last 7 days for the job chart."""
    days = {}
    seen = set()
    for r in runs:
        day = r.started_at.date()
        seen.add(day)
        total, ok = days.get(day, (0, 0))
        if r.ended_at:
            total += 1
            if r.status == "ok":
                ok += 1
        days[day] = (total, ok)
    labels, values = [], []
    for offset in range(6, -1, -1):
        day = (now_utc() - timedelta(days=offset)).date()
        total, ok = days.get(day, (0, 0))
        labels.append(day.isoformat())
        values.append(round(100 * ok / total, 1) if total else 0)
    return {"labels": labels, "values": values}


def _start_scheduler():
    """Start an APScheduler thread running the watchdog sweep each minute."""
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.interval import IntervalTrigger
    except ImportError:  # pragma: no cover - apscheduler is a hard dep
        logger.warning("apscheduler not installed; watchdog not scheduled")
        return None

    def _tick():
        db = SessionLocal()
        try:
            watchdog_check(db)
        except Exception:  # noqa: BLE001 - never let the scheduler die
            logger.exception("watchdog sweep failed")
        finally:
            db.close()

    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(_tick, IntervalTrigger(minutes=1), id="watchdog", replace_existing=True)
    scheduler.start()
    logger.info("watchdog scheduler started (every 1 minute)")
    return scheduler


#: Module-level app instance used by uvicorn / tests.
app = create_app()


__all__ = ["app", "create_app"]