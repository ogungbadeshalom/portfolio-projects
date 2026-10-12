"""POST /upload — simple multipart file upload.

Uploads one or more files under the ``file`` form field. Each file is streamed
to content-addressable storage, MIME-sniffed from bytes, validated against the
whitelist, and its metadata recorded.

The multipart body is read via ``await request.form()`` so both a single
``file`` field and repeated ``file`` fields are supported uniformly.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, UploadFile, status

from upload.limits import LimitExceededError, check_mime, check_size, sanitize_filename
from upload.mime import detect_mime
from upload.models import FileRecord, get_metadata
from upload.storage import save_stream

router = APIRouter(tags=["upload"])


async def _ingest(upload: UploadFile) -> dict:
    """Stream a single ``UploadFile`` into storage and record metadata."""
    filename = sanitize_filename(upload.filename or "upload")
    size = 0
    collected_head = b""

    async def chunked_reads():
        nonlocal size, collected_head
        while True:
            chunk = await upload.read(64 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if len(collected_head) < 8192:
                collected_head = (collected_head + chunk)[:8192]
            yield chunk

    try:
        hash_ = await save_stream(chunked_reads())
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"storage error: {exc}") from exc

    try:
        check_size(size)
    except LimitExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)
        ) from exc

    mime = detect_mime(collected_head, filename)
    try:
        check_mime(mime)
    except LimitExceededError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc

    record = FileRecord(hash=hash_, filename=filename, size=size, mime=mime)
    get_metadata().insert_file(record)

    return {
        "hash": hash_,
        "size": size,
        "mime": mime,
        "filename": filename,
        "url": f"/files/{hash_}",
    }


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_files(request: Request) -> dict:
    """Accept one or more multipart ``file`` fields and store them.

    Returns per-file metadata under ``results``, and mirroring the top-level
    fields (``hash``/``url``/``mime``) when a single file was uploaded for a
    quick client experience.
    """
    form = await request.form()
    files = form.getlist("file")
    if not files:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="multipart field 'file' is required",
        )
    results = [await _ingest(f) for f in files]
    if len(results) == 1:
        return {"results": results, **results[0]}
    return {"results": results}