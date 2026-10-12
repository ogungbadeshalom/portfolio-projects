"""Multipart (chunked) upload flow.

For large files::

    POST /upload/init              -> {"upload_id": "..."}
    POST /upload/{id}/part         (body: raw bytes; returns part_number)
    POST /upload/{id}/complete     -> {"hash": "...", "url": "/files/..."}

Each part is written to a temp directory keyed by ``upload_id``; completion
streams the concatenated parts through the content-addressable storage layer
(single BLAKE2b pass) and then cleans up the temp parts.
"""
from __future__ import annotations

import secrets
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, status

from upload.config import settings
from upload.limits import LimitExceededError, check_mime, check_size, sanitize_filename
from upload.mime import detect_mime
from upload.models import FileRecord, MultipartUpload, PartRecord, get_metadata
from upload.storage import save_stream

router = APIRouter(tags=["upload"])


def _parts_dir(upload_id: str) -> Path:
    d = settings.storage_dir / "parts" / upload_id
    d.mkdir(parents=True, exist_ok=True)
    return d


@router.post("/upload/init", status_code=status.HTTP_201_CREATED)
async def init_upload(filename: str = "upload") -> dict:
    """Start a multipart upload and return its ``upload_id``."""
    safe = sanitize_filename(filename)
    upload_id = secrets.token_urlsafe(24)
    get_metadata().upsert_upload(MultipartUpload(upload_id=upload_id, filename=safe))
    return {"upload_id": upload_id, "filename": safe}


@router.post("/upload/{upload_id}/part")
async def upload_part(upload_id: str, request: Request) -> dict:
    """Upload a single part (raw body) and record its size."""
    upload = get_metadata().get_upload(upload_id)
    if upload is None:
        raise HTTPException(status_code=404, detail="upload_id not found")

    body = await request.body()
    check_size(len(body))  # a single oversized part is rejected up front

    part_number = (
        max((p.part_number for p in upload.parts), default=0) + 1
    )
    ( _parts_dir(upload_id) / f"part-{part_number}" ).write_bytes(body)

    upload.parts.append(PartRecord(part_number=part_number, size=len(body)))
    get_metadata().upsert_upload(upload)
    return {"part_number": part_number, "size": len(body)}


@router.post("/upload/{upload_id}/complete", status_code=status.HTTP_201_CREATED)
async def complete_upload(upload_id: str) -> dict:
    """Concatenate all parts, store content-addressably, and clean up."""
    upload = get_metadata().get_upload(upload_id)
    if upload is None:
        raise HTTPException(status_code=404, detail="upload_id not found")
    if not upload.parts:
        raise HTTPException(status_code=400, detail="no parts uploaded")

    parts = sorted(upload.parts, key=lambda p: p.part_number)
    dir_path = _parts_dir(upload_id)

    async def concatenated():
        for part in parts:
            data = (dir_path / f"part-{part.part_number}").read_bytes()
            yield data

    hash_ = await save_stream(concatenated())
    size = sum(p.size for p in parts)

    try:
        check_size(size)
    except LimitExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)
        ) from exc

    head = (dir_path / f"part-{parts[0].part_number}").read_bytes()[:8192]
    mime = detect_mime(head, upload.filename)
    try:
        check_mime(mime)
    except LimitExceededError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc

    get_metadata().insert_file(
        FileRecord(hash=hash_, filename=upload.filename, size=size, mime=mime)
    )
    get_metadata().delete_upload(upload_id)

    # Best-effort cleanup of leftover part files.
    for part in parts:
        (dir_path / f"part-{part.part_number}").unlink(missing_ok=True)
    try:
        dir_path.rmdir()
    except OSError:
        pass

    return {
        "hash": hash_,
        "size": size,
        "mime": mime,
        "filename": upload.filename,
        "url": f"/files/{hash_}",
    }