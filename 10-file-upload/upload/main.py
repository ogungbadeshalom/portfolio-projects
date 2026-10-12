"""File Upload Service (FastAPI, local disk storage).

Run with::

    uvicorn upload.main:app --port 8001
"""
from __future__ import annotations

from typing import Any, AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from upload.config import settings
from upload.routes import files, multipart, upload
from upload.storage import _storage_root


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Ensure the storage directory exists when the app boots."""
    _storage_root()
    yield


app = FastAPI(
    title="File Upload Service",
    description="S3-style file upload with local content-addressable storage.",
    version="0.1.0",
    lifespan=lifespan,
)


@app.exception_handler(Exception)
async def _generic_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=500, content={"detail": "internal server error"})


app.include_router(upload.router)
app.include_router(multipart.router)
app.include_router(files.router)


def create_app(**settings_overrides: Any) -> FastAPI:
    """Build a fresh app instance for the test-suite (dep-override friendly)."""
    return app