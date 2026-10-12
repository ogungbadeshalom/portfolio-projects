"""FastAPI application: JSON API + web UI for the task scheduler.

On startup it (re)creates the store, registers example tasks, and boots a
dispatcher thread plus ``N`` worker threads so the system is self-contained
with a single process (no external Redis/Celery).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func

from scheduler import example_tasks  # noqa: F401  (registers handlers)
from scheduler import scheduler as dispatcher
from scheduler.config import PACKAGE_DIR
from scheduler.models import (
    STATUS_DEAD,
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_RUNNING,
    Task,
)
from scheduler.routes import metrics_router, tasks_router, workers_router
from scheduler.routes.workers import worker_liveness
from scheduler.store import ensure_store, get_session
from scheduler.worker import Worker

logger = logging.getLogger(__name__)

templates = Jinja2Templates(directory=str(PACKAGE_DIR / "templates"))


def _dashboard_context() -> dict:
    session = get_session()
    try:
        counts = dict(
            session.query(Task.status, func.count(Task.id)).group_by(Task.status).all()
        )
        total = sum(counts.values())
        recent = (
            session.query(Task).order_by(Task.created_at.desc()).limit(50).all()
        )
        rows = []
        for t in recent:
            rows.append(
                {
                    "id": t.id,
                    "name": t.name,
                    "status": t.status,
                    "payload_json": t.payload_json,
                    "scheduled_at": t.scheduled_at,
                    "cron": t.cron,
                    "attempts": t.attempts,
                    "max_attempts": t.max_attempts,
                }
            )
        workers, active, dead = worker_liveness()
        return {
            "stats": {
                "total": total,
                STATUS_PENDING: counts.get(STATUS_PENDING, 0),
                STATUS_RUNNING: counts.get(STATUS_RUNNING, 0),
                STATUS_DONE: counts.get(STATUS_DONE, 0),
                STATUS_FAILED: counts.get(STATUS_FAILED, 0),
                STATUS_DEAD: counts.get(STATUS_DEAD, 0),
            },
            "tasks": rows,
            "workers": workers,
            "workers_active": active,
            "workers_dead": dead,
        }
    finally:
        session.close()


def create_app(*, workers: int | None = None, auto_start: bool = True) -> FastAPI:
    """Build the scheduler app.

    Parameters
    ----------
    workers : int | None
        Number of worker threads to boot (default: 2, or 0 to disable).
    auto_start : bool
        When False the dispatcher/workers are not started (tests control them).
    """
    worker_count = workers if workers is not None else 2

    booted = {"dispatcher": None, "workers": []}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        ensure_store()
        if auto_start:
            booted["dispatcher"] = dispatcher.start_dispatcher_thread()
            for _ in range(worker_count):
                booted["workers"].append(Worker().start())
        try:
            yield
        finally:
            if booted["dispatcher"] is not None:
                dispatcher.stop_dispatcher_thread(booted["dispatcher"])
            for w in booted["workers"]:
                w.stop()

    app = FastAPI(title="Distributed Task Scheduler", version="1.0.0", lifespan=lifespan)

    app.include_router(tasks_router)
    app.include_router(workers_router)
    app.include_router(metrics_router)

    # ------------------------------------------------------------------ UI
    @app.get("/", response_class=HTMLResponse)
    def dashboard(request: Request):
        return templates.TemplateResponse(
            request, "dashboard.html", {"request": request, **_dashboard_context()}
        )

    @app.get("/tasks", response_class=HTMLResponse)
    def tasks_page(request: Request):
        return templates.TemplateResponse(
            request, "tasks.html", {"request": request, **_dashboard_context()}
        )

    @app.get("/tasks/{task_id}", response_class=HTMLResponse)
    def task_detail(request: Request, task_id: int):
        from scheduler.routes import tasks as task_routes

        session = get_session()
        try:
            task = session.get(Task, task_id)
            if task is None:
                return HTMLResponse("Task not found", status_code=404)
            runs = sorted(task.runs, key=lambda r: r.started_at, reverse=True)
            return templates.TemplateResponse(
                request,
                "task_detail.html",
                {
                    "request": request,
                    "task": task,
                    "runs": runs,
                },
            )
        finally:
            session.close()

    @app.get("/dlq", response_class=HTMLResponse)
    def dlq_page(request: Request):
        from scheduler.dlq import list_dlq

        return templates.TemplateResponse(
            request,
            "dlq.html",
            {"request": request, "dlq": list_dlq()},
        )

    app.mount("/static", StaticFiles(directory=str(PACKAGE_DIR / "static")), name="static")
    return app


#: Module-level instance for `uvicorn scheduler.main:app`.
app = create_app()


__all__ = ["app", "create_app"]