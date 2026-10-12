"""SQLAlchemy models and database bootstrap for the transcoder queue.

Three tables persist job state across restarts:

* :class:`Job` -- a submitted video and its overall status/progress.
* :class:`Resolution` -- one output resolution (480/720/1080) for a job.
* :class:`OutputFile` -- a concrete file produced (mp4 / m3u8 / thumbnail).

Storage is SQLite via SQLAlchemy 2.0.  All IDs are strings (short, URL-safe,
test-friendly) handed out by the queue.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from sqlalchemy.pool import StaticPool

logger = logging.getLogger(__name__)

Base = declarative_base()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class JobStatus:
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Job(Base):
    """One submitted video and its overall transcode state."""

    __tablename__ = "jobs"

    id = Column(String(32), primary_key=True)
    filename = Column(String(320), nullable=False)
    source_path = Column(String(1024), nullable=False)
    status = Column(String(24), nullable=False, default=JobStatus.QUEUED)
    progress_pct = Column(Float, nullable=False, default=0.0)
    error = Column(Text, nullable=True)
    attempts = Column(Integer, nullable=False, default=0)
    duration_seconds = Column(Float, nullable=True)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    updated_at = Column(DateTime, nullable=False, default=_utcnow)

    resolutions = relationship(
        "Resolution", back_populates="job", cascade="all, delete-orphan", lazy="selectin"
    )

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "filename": self.filename,
            "status": self.status,
            "progress_pct": round(self.progress_pct or 0.0, 1),
            "error": self.error,
            "attempts": self.attempts,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "resolutions": [r.to_dict() for r in self.resolutions],
        }


class Resolution(Base):
    """A single target resolution for a job."""

    __tablename__ = "resolutions"
    __table_args__ = (UniqueConstraint("job_id", "height", name="uq_job_res"),)

    id = Column(Integer, primary_key=True)
    job_id = Column(String(32), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    height = Column(Integer, nullable=False)  # 480 / 720 / 1080
    status = Column(String(24), nullable=False, default=JobStatus.QUEUED)
    progress_pct = Column(Float, nullable=False, default=0.0)
    output_path = Column(String(1024), nullable=True)  # directory of outputs

    job = relationship("Job", back_populates="resolutions")

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "height": self.height,
            "status": self.status,
            "progress_pct": round(self.progress_pct or 0.0, 1),
            "output_path": self.output_path,
        }


class OutputFile(Base):
    """A concrete file produced for a resolution (mp4 / m3u8 / jpg)."""

    __tablename__ = "output_files"

    id = Column(Integer, primary_key=True)
    job_id = Column(String(32), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    resolution_id = Column(Integer, ForeignKey("resolutions.id", ondelete="CASCADE"), nullable=True)
    kind = Column(String(16), nullable=False)  # mp4 | hls | thumbnail
    filename = Column(String(320), nullable=False)
    size_bytes = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=_utcnow)


# --------------------------------------------------------------------------- #
# Engine / session bootstrap
# --------------------------------------------------------------------------- #


def create_engine_for(uri: str = "sqlite:///:memory:"):
    """Return a SQLAlchemy engine for ``uri`` (shares in-memory across connect)."""
    opts: Dict = {}
    if uri == "sqlite:///:memory:":
        opts["poolclass"] = StaticPool
        opts["connect_args"] = {"check_same_thread": False}
    else:
        opts["connect_args"] = {"check_same_thread": False}
    return create_engine(uri, **opts)


def make_session_factory(uri: str = "sqlite:///:memory:"):
    """Create tables (idempotent) and return a :class:`sessionmaker`."""
    engine = create_engine_for(uri)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


# --------------------------------------------------------------------------- #
# Query helpers
# --------------------------------------------------------------------------- #


def get_job(session, job_id: str) -> Optional[Job]:
    return session.get(Job, job_id)


def list_jobs(session, *, status: Optional[str] = None, limit: int = 100) -> List[Job]:
    query = session.query(Job)
    if status:
        if status == "active":
            query = query.filter(Job.status.in_([JobStatus.QUEUED, JobStatus.PROCESSING]))
        else:
            query = query.filter(Job.status == status)
    return query.order_by(Job.created_at.desc()).limit(limit).all()