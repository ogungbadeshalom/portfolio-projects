"""POST /api/shorten — create a short URL from a long one."""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from urlshort.config import settings
from urlshort.database import get_db
from urlshort.id_generator import generate_code
from urlshort.models import URLRecord
from urlshort.schemas import ShortenRequest, ShortenResponse, serialize_dt
from urlshort.validation import normalize_url

router = APIRouter(tags=["shorten"])

#: Allow only URL-safe characters in a custom alias.
_CUSTOM_CODE_RE = re.compile(r"^[A-Za-z0-9_-]+$")


async def _collision_free_code(db: AsyncSession, length: int) -> str:
    """Generate a fresh code that does not already exist in ``db``."""
    while True:
        code = generate_code(length=length)
        existing = await db.scalar(select(URLRecord).where(URLRecord.code == code))
        if existing is None:
            return code


def _build_short_url(code: str, request: Request | None = None) -> str:
    """Return a short URL string honouring an absolute ``base_url`` if set."""
    if settings.base_url:
        base = settings.base_url.rstrip("/")
        return f"{base}/{code}"
    return f"/{code}"


@router.post(
    "/api/shorten",
    response_model=ShortenResponse,
    status_code=status.HTTP_201_CREATED,
)
async def shorten(
    payload: ShortenRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ShortenResponse:
    """Create a short link.

    Validates the target URL (SSRF-safe), generates (or honours) a unique
    code, persists the record, and returns the short URL.
    """
    # Validate URL safety first so we 422 before touching the DB.
    try:
        target_url = normalize_url(str(payload.url))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if payload.code is not None:
        code = payload.code
        if not _CUSTOM_CODE_RE.match(code):
            raise HTTPException(
                status_code=422,
                detail="Custom code may only contain letters, digits, '-' or '_'",
            )
        existing = await db.scalar(select(URLRecord).where(URLRecord.code == code))
        if existing is not None:
            raise HTTPException(
                status_code=409, detail="That short code is already taken"
            )
    else:
        code = await _collision_free_code(db, settings.code_length)

    record = URLRecord(code=code, target_url=target_url, clicks=0)
    db.add(record)
    await db.commit()
    await db.refresh(record)

    return ShortenResponse(
        code=record.code,
        short_url=_build_short_url(record.code, request),
        target_url=record.target_url,
        clicks=record.clicks,
        created_at=serialize_dt(record.created_at),
    )