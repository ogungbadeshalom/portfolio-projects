"""Metrics endpoint: Prometheus text by default, JSON when asked."""

from __future__ import annotations

from fastapi import APIRouter, Request

from scheduler import metrics as metrics_mod

router = APIRouter(tags=["metrics"])


@router.get("/metrics")
def metrics(request: Request) -> object:
    """Expose Prometheus text via /metrics; ?format=json gives a JSON view.

    If ``prometheus_client`` is unavailable the text endpoint falls back to a
    hand-rolled exposition, so /metrics always answers.
    """
    fmt = request.query_params.get("format", "text")
    if fmt == "json":
        from fastapi.responses import JSONResponse

        return JSONResponse(metrics_mod.metrics_json())
    try:
        text = metrics_mod.metrics_text().decode()
    except Exception:  # noqa: BLE001 - never break /metrics
        text = _fallback_text()
    from fastapi.responses import PlainTextResponse

    return PlainTextResponse(text, media_type="text/plain; version=0.0.4")


def _fallback_text() -> str:
    """Minimal plain-text exposition if the prometheus client is unavailable."""
    data = metrics_mod.metrics_json()
    lines = [
        "# TYPE scheduler_tasks_pending gauge",
        f"scheduler_tasks_pending {data['tasks_pending']}",
        "# TYPE scheduler_tasks_running gauge",
        f"scheduler_tasks_running {data['tasks_running']}",
        "# TYPE scheduler_tasks_dead gauge",
        f"scheduler_tasks_dead {data['tasks_dead']}",
        "# TYPE scheduler_workers_active gauge",
        f"scheduler_workers_active {data['workers_active']}",
        "# TYPE scheduler_dlq_size gauge",
        f"scheduler_dlq_size {data['tasks_dead']}",
    ]
    return "\n".join(lines)


__all__ = ["router"]