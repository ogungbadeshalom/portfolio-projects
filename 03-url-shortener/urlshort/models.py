"""SQLAlchemy 2.0 models for the URL shortener."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base shared by every ORM model."""


class URLRecord(Base):
    """A single shortened URL record.

    Attributes:
        id: Internal auto-incrementing primary key.
        code: The public, unique short code (e.g. ``"abc1234"``).
        target_url: The original long URL the code redirects to.
        clicks: Number of times the short URL has been visited.
        created_at: Epoch (Unix) timestamp of when the record was created.
        expires_at: Optional epoch timestamp after which the link is dead.
    """

    __tablename__ = "urls"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    code: Mapped[str] = mapped_column(
        String(128), unique=True, index=True, nullable=False
    )
    target_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    clicks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )