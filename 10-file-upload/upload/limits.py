"""File size and type enforcement.

These helpers centralise the policy rules the routes check before accepting a
file, so upload/prewarm paths can't drift from each other.
"""
from __future__ import annotations

from upload.config import settings


class LimitExceededError(Exception):
    """Raised when a file violates a size/type policy limit."""


def check_size(size: int) -> None:
    """Raise :class:`LimitExceededError` if ``size`` exceeds the max."""
    if size > settings.max_size:
        raise LimitExceededError(
            f"file too large: {size} bytes > max {settings.max_size}"
        )


def check_mime(mime: str) -> None:
    """Raise :class:`LimitExceededError` if ``mime`` is not whitelisted.

    ``application/octet-stream`` is always allowed as a catch-all so unknown
    binary content can still be uploaded when the operator opts in.
    """
    if mime == "application/octet-stream":
        return
    if mime not in settings.allowed_types:
        raise LimitExceededError(f"content type not allowed: {mime}")


def sanitize_filename(filename: str) -> str:
    """Strip path separators and dangerous control bytes from a filename.

    Prevents path traversal (``../``) and OS null-byte tricks.

    Returns:
        A safe basename, or ``"upload"`` when nothing usable remains.
    """
    clean = filename.replace("\\", "/").split("/")[-1]
    clean = "".join(ch for ch in clean if ch not in "\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\x0c\x0d\x0e\x0f\x1f")
    clean = clean.strip()
    if not clean or clean in (".", ".."):
        return "upload"
    return clean[:255]