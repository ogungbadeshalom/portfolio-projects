"""REST API for submitting and inspecting transcode jobs."""

from __future__ import annotations

import secrets
import shutil
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from .. import config, models
from ..models import Job, JobStatus

router = APIRouter()

templates = Jinja2Templates(directory=str(config.BASE_DIR / "transcoder" / "templates"))


def _get_session(request: Request) -> Session:
    session_factory = request.app.state.session_factory
    return session_factory()


def _get_queue(request: Request):
    return request.app.state.queue


def _job_or_404(session: Session, job_id: str) -> Job:
    job = models.get_job(session, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return job


# --------------------------------------------------------------------------- #
# Submit
# --------------------------------------------------------------------------- #


@router.post("/api/jobs")
async def submit_job(
    request: Request,
    file: UploadFile = File(...),
    resolutions: str = Form("480,720,1080"),
    session: Session = Depends(_get_session),
):
    """Accept an uploaded video, persist it, and enqueue a transcode job."""
    job_id = secrets.token_hex(3)  # 6-char id, URL-safe
    config.INPUT_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = Path(file.filename or "video.mp4").name[:160]
    dest = config.INPUT_DIR / f"{job_id}_{safe_name}"

    with dest.open("wb") as out:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            out.write(chunk)

    if dest.stat().st_size == 0:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Empty upload rejected")

    try:
        heights = [int(r) for r in resolutions.replace(" ", "").split(",") if r != ""]
    except ValueError:
        heights = config.RESOLUTIONS

    job = Job(
        id=job_id,
        filename=safe_name,
        source_path=str(dest),
        status=JobStatus.QUEUED,
        progress_pct=0.0,
    )
    for h in heights:
        job.resolutions.append(models.Resolution(height=h, status=JobStatus.QUEUED))
    session.add(job)
    session.commit()

    request.app.state.queue.enqueue(job_id)
    return {"id": job_id, "status": JobStatus.QUEUED, "resolutions": heights}


# --------------------------------------------------------------------------- #
# Listing & status
# --------------------------------------------------------------------------- #


@router.get("/api/jobs")
def list_jobs(request: Request, status: Optional[str] = None, session: Session = Depends(_get_session)):
    jobs = models.list_jobs(session, status=status, limit=100)
    return {"jobs": [j.to_dict() for j in jobs]}


@router.get("/api/jobs/{job_id}")
def job_detail(job_id: str, session: Session = Depends(_get_session)):
    return _job_or_404(session, job_id).to_dict()


@router.get("/api/jobs/{job_id}/status")
def job_status(job_id: str, session: Session = Depends(_get_session)):
    job = _job_or_404(session, job_id)
    return {
        "id": job.id,
        "status": job.status,
        "progress_pct": round(job.progress_pct or 0.0, 1),
        "attempts": job.attempts,
        "error": job.error,
    }


@router.delete("/api/jobs/{job_id}")
def cancel_job(job_id: str, request: Request, session: Session = Depends(_get_session)):
    """Cancel a job that has not finished."""
    job = _job_or_404(session, job_id)
    if job.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
        raise HTTPException(status=409, detail="Job already terminal")
    job.status = JobStatus.CANCELLED
    session.commit()
    request.app.state.queue.publish(
        {"type": "job", "job_id": job_id, **job.to_dict()}
    )
    return {"id": job_id, "status": JobStatus.CANCELLED}


# --------------------------------------------------------------------------- #
# Output serving (HLS + thumbnail)
# --------------------------------------------------------------------------- #


@router.get("/output/{job_id}/master.m3u8")
def serve_master(job_id: str, session: Session = Depends(_get_session)):
    _job_or_404(session, job_id)
    master = config.OUTPUT_DIR / job_id / "master.m3u8"
    if not master.exists():
        # Fall back to the first variant playlist if no master was built.
        fallback = _first_playlist(config.OUTPUT_DIR / job_id)
        if fallback is None:
            raise HTTPException(status=404, detail="No HLS output yet")
        return FileResponse(str(fallback), media_type="application/vnd.apple.mpegurl")
    return FileResponse(str(master), media_type="application/vnd.apple.mpegurl")


@router.get("/output/{job_id}/thumbnail.jpg")
def serve_thumbnail(job_id: str, session: Session = Depends(_get_session)):
    _job_or_404(session, job_id)
    thumb = config.OUTPUT_DIR / job_id / "thumbnail.jpg"
    if not thumb.exists():
        raise HTTPException(status=404, detail="No thumbnail yet")
    return FileResponse(str(thumb), media_type="image/jpeg")


@router.get("/output/{job_id}/{path:path}")
def serve_output_file(job_id: str, path: str, session: Session = Depends(_get_session)):
    """Serve any produced file under a job's output directory (segments etc.)."""
    _job_or_404(session, job_id)
    base = config.OUTPUT_DIR / job_id
    target = (base / path).resolve()
    if not str(target.resolve()).startswith(str(base.resolve())) or not target.exists():
        raise HTTPException(status=404, detail="File not found")
    content_types = {
        ".ts": "video/mp2t",
        ".m3u8": "application/vnd.apple.mpegurl",
        ".mp4": "video/mp4",
        ".jpg": "image/jpeg",
    }
    return FileResponse(str(target), media_type=content_types.get(target.suffix.lower()))


@router.get("/api/jobs/{job_id}/download")
def download_all(job_id: str, session: Session = Depends(_get_session)):
    """Zip every produced file for a job into one archive."""
    _job_or_404(session, job_id)
    job_dir = config.OUTPUT_DIR / job_id
    if not job_dir.exists():
        raise HTTPException(status=404, detail="No output yet")
    archive = config.STORAGE_DIR / "downloads" / f"{job_id}.zip"
    archive.parent.mkdir(parents=True, exist_ok=True)
    if archive.exists():
        archive.unlink()
    shutil.make_archive(str(archive.with_suffix("")), "zip", root_dir=str(job_dir.parent), base_dir=job_id)
    return FileResponse(str(archive), media_type="application/zip",
                        filename=f"{job_id}.zip")


# --------------------------------------------------------------------------- #
# Web UI (simple HTML pages, not SPA)
# --------------------------------------------------------------------------- #


@router.get("/")
def web_index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")


@router.get("/jobs")
def web_jobs(request: Request):
    return templates.TemplateResponse(request=request, name="jobs.html")


def _first_playlist(job_dir: Path) -> Optional[Path]:
    for res_dir in sorted(job_dir.glob("*p")):
        p = res_dir / "playlist.m3u8"
        if p.exists():
            return p
    return None