"""ORM models and Pydantic schemas for webtrap.

Bodies are stored as raw bytes (never assumed to be JSON). Headers are stored
as a JSON dict where every value is a list, so multi-value headers (e.g.
``Set-Cookie``, duplicate ``Accept``) survive exactly as received.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field
from sqlalchemy import BLOB, DateTime, Integer, LargeBinary, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# --------------------------------------------------------------------------- #
# ORM
# --------------------------------------------------------------------------- #


class Base(DeclarativeBase):
    pass


class CapturedRequest(Base):
    """A single webhook that was delivered to some /incoming/{token} trap."""

    __tablename__ = "requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token: Mapped[str] = mapped_column(
        String(200), index=True, nullable=False
    )  # which trap this hit
    method: Mapped[str] = mapped_column(String(16), nullable=False)
    path: Mapped[str] = mapped_column(String(2000), nullable=False)
    headers_json: Mapped[str] = mapped_column(Text, nullable=False)  # str -> list[str]
    body: Mapped[Optional[bytes]] = mapped_column(BLOB, nullable=True)
    query_json: Mapped[str] = mapped_column(Text, nullable=False)  # str -> list[str]
    source_ip: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    def to_dict(self) -> Dict[str, Any]:
        import json

        return {
            "id": self.id,
            "token": self.token,
            "method": self.method,
            "path": self.path,
            "headers": json.loads(self.headers_json),
            "body": self.body,
            "query": json.loads(self.query_json),
            "source_ip": self.source_ip,
            "received_at": self.received_at.isoformat(),
        }

    def headers_dict(self) -> Dict[str, List[str]]:
        import json

        try:
            return json.loads(self.headers_json)
        except (TypeError, ValueError):
            return {}

    def query_dict(self) -> Dict[str, List[str]]:
        import json

        try:
            return json.loads(self.query_json)
        except (TypeError, ValueError):
            return {}


# --------------------------------------------------------------------------- #
# Pydantic schemas
# --------------------------------------------------------------------------- #


class HeaderDict(BaseModel):
    """A request/response header map. Values are always lists of strings so
    multi-value headers are representable.
    """

    values: Dict[str, List[str]] = Field(default_factory=dict)

    def flat(self) -> List[Tuple[str, str]]:
        """Yield (name, value) pairs, one per value, in stable order."""
        out: List[Tuple[str, str]] = []
        for name, vals in self.values.items():
            for v in vals:
                out.append((name, v))
        return out


class ReplayRequest(BaseModel):
    """What the caller wants a replay to look like."""

    target: str = Field(..., min_length=1)
    delay_ms: int = Field(default=0, ge=0, le=3600_000)
    # Override the stored host/path. By default the original host is replaced
    # with ``target`` and the original path is preserved.
    path: Optional[str] = None


class ReplayResponse(BaseModel):
    """The response received from replaying a captured request."""

    status_code: int
    headers: Dict[str, List[str]] = Field(default_factory=dict)
    body: Optional[bytes] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status_code": self.status_code,
            "headers": self.headers,
            "body_raw": self.body,
        }


class CaptureOut(BaseModel):
    """JSON shape returned when a request is captured."""

    id: int
    token: str
    received_at: str