"""SQLAlchemy ORM models.

Tenant, ApiKey, UsageLog — the three core tables.

Quota metering lives in ``UsageLog``: the monthly quota check is a single
aggregate query over ``(tenant_id, MONTH(timestamp))`` backed by the
composite index ``ix_usage_tenant_month``.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


def utcnow() -> datetime:
    """Timezone-aware UTC now for timestamp columns."""
    return datetime.now(timezone.utc)


class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    # Password stored as a salted hash. Using a work factor far heavier
    # than HMAC (300k+salt rounds) so credentials are not cheaply cracked.
    password_hash = Column(String(255), nullable=False)
    name = Column(String(255), nullable=False, default="")
    plan = Column(String(32), nullable=False, default="free")
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    keys = relationship(
        "ApiKey", back_populates="tenant", cascade="all, delete-orphan"
    )


class ApiKey(Base):
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(
        Integer, ForeignKey("tenants.id"), nullable=False, index=True
    )
    # Only the HMAC-SHA256 hash of the key is persisted. The plaintext is
    # shown exactly once at creation time, then discarded.
    key_hash = Column(String(128), unique=True, nullable=False, index=True)
    # Visible prefix, e.g. ``sk_live_``. Used for identification / listing.
    prefix = Column(String(64), nullable=False)
    name = Column(String(255), nullable=False, default="")
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    revoked = Column(Boolean, nullable=False, default=False)

    tenant = relationship("Tenant", back_populates="keys")


class UsageLog(Base):
    __tablename__ = "usage_logs"
    # Fast monthly-quota lookups: tenant + month composite index, with the
    # method/status columns appended for the covering dashboard queries.
    __table_args__ = (
        Index(
            "ix_usage_tenant_month",
            "tenant_id",
            "timestamp",
        ),
        Index(
            "ix_usage_tenant_status_timestamp",
            "tenant_id",
            "status_code",
            "timestamp",
        ),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(
        Integer, ForeignKey("tenants.id"), nullable=False, index=True
    )
    endpoint = Column(String(512), nullable=False)
    method = Column(String(16), nullable=False)
    status_code = Column(Integer, nullable=True)
    latency_ms = Column(Integer, nullable=True)
    timestamp = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    tenant = relationship("Tenant")