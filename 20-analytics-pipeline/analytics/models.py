"""Pydantic models + validation for ingested events.

Clients send a flexible JSON event with a stable core and an arbitrary
``properties`` blob. Server-side validation here guards the ingestion path:
unknown/mismatched types are rejected before they ever reach the queue.

Privacy: the raw client IP is never stored. :class:`Event` carries an optional
``ip`` that is anonymized (last octet zeroed, GDPR-style) by :meth:`anonymize`
before the event is enqueued.
"""

from __future__ import annotations

import ipaddress
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: A missing client timestamp means "now"; stored UTC.
_TIMESTAMP_FORMATS = ("iso", "unix")


class Event(BaseModel):
    """A single analytic event as submitted by the client/SDK.

    ``timestamp`` is optional; when omitted the server stamps arrival time in
    UTC. ``properties`` is a free-form dict and is stored as JSON.
    """

    model_config = ConfigDict(extra="allow")

    event: str = Field(min_length=1, max_length=200)
    user_id: str = Field(min_length=1, max_length=200)
    session_id: Optional[str] = Field(default=None, max_length=200)
    timestamp: Optional[str | int | float] = None
    properties: Dict[str, Any] = Field(default_factory=dict)
    # Optional raw IP, anonymized before storage (never persisted verbatim).
    ip: Optional[str] = Field(default=None, max_length=45)

    @field_validator("event")
    @classmethod
    def _event_norm(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("event name must not be blank")
        return v

    @field_validator("user_id")
    @classmethod
    def _user_norm(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("user_id must not be blank")
        return v

    @field_validator("properties")
    @classmethod
    def _properties_json(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        import json

        try:
            json.dumps(v)
        except (TypeError, ValueError) as exc:
            raise ValueError("properties must be JSON-serializable") from exc
        return v

    @property
    def unix_ts(self) -> int:
        """Resolve the event timestamp to unix seconds (UTC)."""
        ts = self.timestamp
        if ts is None or ts == "":
            return int(datetime.now(timezone.utc).timestamp())
        if isinstance(ts, (int, float)):
            # Already unix (seconds, may be fractional).
            return int(ts)
        if isinstance(ts, str):
            try:
                parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError:
                raise ValueError(f"invalid timestamp {ts!r}")
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)  # naive == UTC
            return int(parsed.timestamp())
        raise ValueError(f"unsupported timestamp type {type(ts).__name__}")

    @property
    def ts_iso(self) -> str:
        """ISO-8601 UTC string derived from the core timestamp."""
        return datetime.fromtimestamp(self.unix_ts, tz=timezone.utc).isoformat(
            timespec="seconds"
        )

    def anonymize(self) -> "Event":
        """Return a copy with a GDPR-anonymized IP (no in-place mutation)."""
        if not self.ip:
            return self
        try:
            ip = ipaddress.ip_address(self.ip)
            if isinstance(ip, ipaddress.IPv4Address):
                anon = str(ipaddress.ip_address(int(ip) & 0xFFFFFF00))
            else:
                anon = f"{ip.exploded.rsplit(':', 1)[0]}::"
        except ValueError:
            anon = ""  # unparseable IP -> drop entirely
        return self.model_copy(update={"ip": anon})


__all__ = ["Event"]