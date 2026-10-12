"""Files: signed-URL issuing, authenticated downloads, and deletion.

Downloads require a valid HMAC signature (``?expires=...&sig=...``) obtained
from ``POST /files/{hash}/url`` — or, for brevity in a local dev deployment,
``GET /files/{hash}/url`` can return it. Range requests (``Range`` header) are
honoured so media streams with HTTP 206.
"""
from __future__ import annotations

import base64
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query, status
from fastapi.responses import FileResponse, Response

from upload.models import get_metadata
from upload.signed_url import generate_signed_url, verify_signature
from upload.storage import delete_file, get_path

router = APIRouter(tags=["files"])


def _required_record(hash_: str):
    record = get_metadata().get_file(hash_)
    if record is None:
        raise HTTPException(status_code=404, detail="file not found")
    return record


def _address_from_range(range_header: Optional[str], size: int):
    """Parse a ``Range: bytes=start-end`` header.

    Returns ``(start, end)`` inclusive byte positions, or ``None`` if the
    header is absent/malformed (caller falls back to 200 full download).
    """
    if not range_header or not range_header.startswith("bytes="):
        return None
    spec = range_header[len("bytes="):].split(",")[0].strip()
    if spec.startswith("-"):
        try:
            suffix = int(spec[1:])
        except ValueError:
            return None
        if suffix <= 0:
            return None
        start = max(0, size - suffix)
        return (start, size - 1)
    if "-" not in spec:
        return None
    start_s, end_s = spec.split("-", 1)
    try:
        start = int(start_s)
        end = int(end_s) if end_s else size - 1
    except ValueError:
        return None
    if start < 0 or start >= size:
        return None
    end = min(end, size - 1)
    return (start, end)


@router.get("/files/{hash}/url")
async def get_signed_url(
    hash: str,
    expires: int = Query(3600, ge=1, le=86400),
) -> dict:
    """Issue a time-limited, signed download URL for ``hash``."""
    _required_record(hash)
    return {
        "hash": hash,
        "expires_in": expires,
        "url": generate_signed_url(hash, expires_in=expires),
    }


@router.get("/files/{hash}")
async def download_file(
    hash: str,
    expires: Optional[str] = Query(None),
    sig: Optional[str] = Query(None),
    range: Optional[str] = Header(None),
) -> FileResponse:
    """Download ``hash`` after verifying the signed URL query params."""
    _required_record(hash)
    if not expires or not sig or not verify_signature(hash, expires, sig):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing, invalid, or expired signature",
        )
    path: Path = get_path(hash)
    record = get_metadata().get_file(hash)
    filename = (record.filename if record else "download") or "download"
    mime = (record.mime if record else "application/octet-stream") or "application/octet-stream"

    size = path.stat().st_size

    # Range support: return 206 partial content when a valid Range is given.
    pair = _address_from_range(range, size) if range else None
    if pair is not None:
        start, end = pair
        length = end - start + 1
        with open(path, "rb") as fh:
            fh.seek(start)
            body = fh.read(length)
        headers = {
            "Accept-Ranges": "bytes",
            "Content-Range": f"bytes {start}-{end}/{size}",
            "Content-Disposition": f'attachment; filename="{filename}"',
        }
        return Response(
            content=body,
            status_code=206,
            media_type=mime,
            headers=headers,
        )

    return FileResponse(
        path,
        status_code=200,
        media_type=mime,
        filename=filename,
    )


@router.delete("/files/{hash}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file_route(hash: str) -> None:
    """Delete ``hash`` (bytes on disk + metadata record)."""
    record = get_metadata().get_file(hash)
    deleted_blob = delete_file(hash)
    deleted_meta = get_metadata().delete_file(hash) if record else False
    if not deleted_blob and not deleted_meta:
        raise HTTPException(status_code=404, detail="file not found")
    return None