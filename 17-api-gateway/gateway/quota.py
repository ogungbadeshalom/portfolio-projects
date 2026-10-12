"""Monthly quota tracking.

A tenant has a monthly allowance driven by their plan (see
``settings.plan_quotas``). Quota is metered from the ``usage_logs`` table: the
check is a *single aggregate query* over ``(tenant_id, month)`` which is
indexed by the composite ``ix_usage_tenant_month`` index defined on
``UsageLog``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from gateway.config import settings
from gateway.models import Tenant, UsageLog


def month_bounds(now: Optional[datetime] = None) -> Tuple[datetime, datetime]:
    """Return [start of month, start of next month) as aware UTC datetimes."""
    now = now or datetime.now(timezone.utc)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


def monthly_usage(db: Session, tenant_id: int) -> int:
    """Return the number of requests a tenant has used this calendar month."""
    start, end = month_bounds()
    total = (
        db.query(func.count(UsageLog.id))
        .filter(UsageLog.tenant_id == tenant_id)
        .filter(UsageLog.timestamp >= start)
        .filter(UsageLog.timestamp < end)
        .scalar()
    )
    return int(total or 0)


def plan_limit(plan: str) -> Optional[int]:
    """Return the monthly request limit for ``plan`` (None == unlimited)."""
    return settings.plan_quotas.get(plan)


def check_quota(db: Session, tenant: Tenant) -> "QuotaDecision":
    """Check whether ``tenant`` has remaining monthly quota.

    ``enterprise`` (None limit) is always allowed. Otherwise uses a single
    indexed aggregate over ``usage_logs``.
    """
    limit = plan_limit(tenant.plan)
    if limit is None:
        return QuotaDecision(allowed=True, used=0, limit=None)

    used = monthly_usage(db, tenant.id)
    allowed = used < limit
    return QuotaDecision(allowed=allowed, used=used, limit=limit)


class QuotaDecision:
    __slots__ = ("allowed", "used", "limit")

    def __init__(self, allowed: bool, used: int, limit: Optional[int]):
        self.allowed = allowed
        self.used = used
        self.limit = limit

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<QuotaDecision allowed={self.allowed} used={self.used}/{self.limit}>"