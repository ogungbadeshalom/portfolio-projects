"""Pydantic v2 request/response schemas.

All API input and output passes through these models — no raw dicts or
untyped payloads cross the service boundary.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class ShortenRequest(BaseModel):
    """Request body for ``POST /api/shorten``.

    ``url`` is validated as an absolute ``http(s)`` URL. Loopback and private
    IP targets are rejected at the route layer to prevent SSRF.
    """

    model_config = ConfigDict(extra="forbid")

    url: HttpUrl = Field(description="Long URL to shorten (must be http/https)")
    code: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        description="Optional custom alias",
    )


class ShortenResponse(BaseModel):
    """Successful response of ``POST /api/shorten``."""

    code: str
    short_url: str
    target_url: str
    clicks: int = 0
    created_at: str | None = None

    @field_validator("short_url")
    @classmethod
    def _validate_short_url(cls, v: str) -> str:
        return v


class StatsResponse(BaseModel):
    """Response of ``GET /api/stats/{code}``."""

    code: str
    url: str
    clicks: int
    created_at: str


class ListItem(BaseModel):
    """A single URL row within the paginated listing."""

    code: str
    url: str
    clicks: int
    created_at: str


class ListResponse(BaseModel):
    """Response of ``GET /api/list`` (paginated)."""

    items: list[ListItem]
    total: int
    page: int
    page_size: int


class HealthResponse(BaseModel):
    """Response of ``GET /health``."""

    status: str
    database: str


def serialize_dt(value: Any) -> str:
    """Serialize a ``datetime`` (or ``None``) to an ISO-8601 string."""
    if value is None:
        return ""
    return value.isoformat()