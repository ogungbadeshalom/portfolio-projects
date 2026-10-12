"""Shared FastAPI dependencies (auth, DB session, common lookups)."""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from cronmon import auth
from cronmon.database import get_db
from cronmon.models import Job

#: Header the CLI/HTTP client sends its key in.
API_KEY_HEADER = "X-API-Key"


def require_key(x_api_key: str = Header(default="", alias=API_KEY_HEADER)) -> None:
    """Reject requests lacking the correct API key (used for run mutations)."""
    if not x_api_key or not auth.verify(x_api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid API key. Run `watchdog init` to get one.",
            headers={"WWW-Authenticate": "Bearer"},
        )


def get_job_or_404(db: Session, ident: str | int) -> Job:
    """Resolve a job by integer id or case-insensitive name."""
    if isinstance(ident, int) or (isinstance(ident, str) and ident.isdigit()):
        job = db.get(Job, int(ident))
    else:
        job = db.query(Job).filter(Job.name == ident).first()
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {ident!r} not found")
    return job


dep_db = Depends(get_db)


__all__ = ["require_key", "get_job_or_404", "get_db", "dep_db", "API_KEY_HEADER"]