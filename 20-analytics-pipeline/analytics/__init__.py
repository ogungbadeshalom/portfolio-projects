"""Analytics pipeline: event ingestion -> OLAP -> dashboard.

Public API surface lives in :mod:`analytics.main` (FastAPI app factory).
"""

__version__ = "1.0.0"

from .main import app  # noqa: F401

__all__ = ["app", "__version__"]