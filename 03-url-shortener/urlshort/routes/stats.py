"""GET /api/stats/{code} and GET /api/list — stats and paginated listing."""
from __future__ import annotations

import math

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from urlshort.database import get_db
from urlshort.models import URLRecord
from urlshort.schemas import ListItem, ListResponse, StatsResponse, serialize_dt

router = APIRouter(tags=["stats"])


@router.get("/api/stats/{code}", response_model=StatsResponse)
async def get_stats(
    code: str,
    db: AsyncSession = Depends(get_db),
) -> StatsResponse:
    """Return click count and metadata for a short code."""
    record = await db.scalar(select(URLRecord).where(URLRecord.code == code))
    if record is None:
        raise HTTPException(status_code=404, detail="Short URL not found")
    return StatsResponse(
        code=record.code,
        url=record.target_url,
        clicks=record.clicks,
        created_at=serialize_dt(record.created_at),
    )


@router.get("/api/list", response_model=ListResponse)
async def list_urls(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> ListResponse:
    """List all short URLs, newest first, paginated."""
    total = await db.scalar(select(func.count()).select_from(URLRecord)) or 0

    rows = (
        await db.execute(
            select(URLRecord)
            .order_by(URLRecord.created_at.desc(), URLRecord.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()

    items = [
        ListItem(
            code=r.code,
            url=r.target_url,
            clicks=r.clicks,
            created_at=serialize_dt(r.created_at),
        )
        for r in rows
    ]
    return ListResponse(
        items=items,
        total=int(total),
        page=page,
        page_size=page_size,
    )