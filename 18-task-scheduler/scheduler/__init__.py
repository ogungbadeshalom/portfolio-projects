"""Distributed task scheduler: queue, worker pool, retry, DLQ, metrics.

Package version tracks the project release. The public entry points are
:mod:`scheduler.main` (FastAPI admin UI + API) and :mod:`scheduler.cli`
(the Click CLI).
"""

__version__ = "1.0.0"

__all__ = ["__version__"]