"""Pydantic request/response models for the cron-monitor API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


class AuthToken(BaseModel):
    """API key handed out by ``watchdog init``."""

    api_key: str = Field(description="Bearer token used for CLI/HTTP calls")


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------


class JobCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    cron: Optional[str] = Field(default=None, max_length=120)
    expected_duration: int = Field(default=3600, ge=0)
    alert_after_minutes: int = Field(default=120, ge=0)
    webhook_url: Optional[str] = Field(default=None, max_length=500)
    enabled: bool = True


class JobUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    cron: Optional[str] = Field(default=None, max_length=120)
    expected_duration: Optional[int] = Field(default=None, ge=0)
    alert_after_minutes: Optional[int] = Field(default=None, ge=0)
    webhook_url: Optional[str] = Field(default=None, max_length=500)
    enabled: Optional[bool] = None


class JobOut(BaseModel):
    id: int
    name: str
    cron: Optional[str]
    expected_duration: int
    alert_after_minutes: int
    webhook_url: Optional[str]
    enabled: bool
    created_at: datetime
    status: str = "unknown"
    last_run_at: Optional[datetime] = None
    last_run_duration: Optional[int] = None
    last_run_status: Optional[str] = None
    uptime_7d: Optional[float] = None


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


class RunStart(BaseModel):
    job: str = Field(description="Job name or numeric id")
    client_run_id: Optional[str] = Field(default=None, max_length=64)
    started_at: Optional[datetime] = None  # default: now


class RunDone(BaseModel):
    status: Literal["ok", "fail"] = "ok"
    ended_at: Optional[datetime] = None


class RunOut(BaseModel):
    id: int
    job_id: int
    started_at: datetime
    pinged_at: Optional[datetime]
    ended_at: Optional[datetime]
    status: str
    client_run_id: Optional[str]
    duration_seconds: Optional[int] = None


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------


class AlertOut(BaseModel):
    id: int
    job_id: int
    run_id: Optional[int]
    type: str
    message: str
    acknowledged: bool
    sent_at: datetime


class DashboardStats(BaseModel):
    total_jobs: int
    running: int
    healthy: int
    failing: int
    total_runs_24h: int
    active_alerts: int


__all__ = [
    "AuthToken",
    "JobCreate",
    "JobUpdate",
    "JobOut",
    "RunStart",
    "RunDone",
    "RunOut",
    "AlertOut",
    "DashboardStats",
]