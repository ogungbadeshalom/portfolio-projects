"""Admin/API routers for the scheduler."""

from scheduler.routes.metrics import router as metrics_router
from scheduler.routes.tasks import router as tasks_router
from scheduler.routes.workers import router as workers_router

__all__ = ["tasks_router", "workers_router", "metrics_router"]