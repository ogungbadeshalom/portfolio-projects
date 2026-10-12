"""GET /{code} — redirect to the original URL and count the click.

The click increment uses a single atomic ``UPDATE`` statement so concurrent
requests never lose counts (no read-modify-write race).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from urlshort.database import get_db
from urlshort.models import URLRecord

router = APIRouter(tags=["redirect"])


@router.get("/{code}")
async def redirect_to_url(
    code: str,
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """Look up ``code``, atomically bump its click counter, and 302 redirect.

    Returns 302 with the target URL, or 404 if the code is unknown.
    """
    record = await db.scalar(select(URLRecord).where(URLRecord.code == code))
    if record is None:
        raise HTTPException(status_code=404, detail="Short URL not found")

    target = record.target_url

    # Atomic increment — safe under concurrent requests.
    await db.execute(
        update(URLRecord)
        .where(URLRecord.code == code)
        .values(clicks=URLRecord.clicks + 1)
    )
    await db.commit()

    return RedirectResponse(target, status_code=302)