"""MIME detection from file *content*, not file extension.

Uses magic-byte signatures for the common binary formats (images, PDF, zip,
audio/video) and falls back to ``mimetypes`` for text/XML/JSON. Detecting from
bytes is what lets us ignore whatever Content-Type a client claims and reject
disguised payloads server-side.
"""
from __future__ import annotations

import mimetypes

#: Magic-byte signature table. Each entry maps a ``(offset, bytes)`` prefix to a
#: MIME type; we check the longest signatures first.
_MAGIC_SIGNATURES: tuple[tuple[int, bytes, str], ...] = (
    (0, b"\xff\xd8\xff", "image/jpeg"),
    (0, b"\x89PNG\r\n\x1a\n", "image/png"),
    (0, b"GIF87a", "image/gif"),
    (0, b"GIF89a", "image/gif"),
    (0, b"RIFF", "image/webp"),  # further disambiguated below
    (0, b"BM", "image/bmp"),
    (0, b"%PDF-", "application/pdf"),
    (0, b"PK\x03\x04", "application/zip"),  # zip / docx / xlsx based on name
    (0, b"PK\x05\x06", "application/zip"),
    (0, b"\x1f\x8b", "application/gzip"),
    (0, b"\x7fELF", "application/octet-stream"),
    (0, b"<?xml", "application/xml"),
)


def detect_mime(data: bytes, filename: str | None = None) -> str:
    """Detect the MIME type of ``data`` from its magic bytes.

    Args:
        data: At least the first few bytes of the file (ideally the head).
        filename: Optional original name used only to disambiguate
            zip-based Office documents and as a last-resort fallback.

    Returns:
        A MIME type string such as ``"image/png"``. Unknown binary data is
        reported as ``application/octet-stream``.
    """
    if not data:
        return "application/octet-stream"

    # WebP: "RIFF....WEBP" (bytes 8..11 == "WEBP").
    if data.startswith(b"RIFF") and len(data) >= 12 and data[8:12] == b"WEBP":
        return "image/webp"

    for offset, signature, mime in _MAGIC_SIGNATURES:
        if data.startswith(signature, offset):
            if mime == "application/zip" and filename:
                lowered = (filename or "").lower()
                if lowered.endswith(".docx"):
                    return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                if lowered.endswith(".xlsx"):
                    return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            return mime

    # Fall back to text sniffing: if it looks like text, let mimetypes decide.
    if _looks_like_text(data):
        if b"<html" in data[:4096].lower():
            return "text/html"
        if data.lstrip().startswith((b"{", b"[")):
            return "application/json"
        if filename:
            guessed, _ = mimetypes.guess_type(filename)
            if guessed and guessed.startswith(("text/", "application/json", "application/xml")):
                return guessed
        return "text/plain"

    return "application/octet-stream"


def _looks_like_text(data: bytes) -> bool:
    """True if ``data`` (a prefix) contains no obvious binary control bytes."""
    sample = data[:2048]
    if not sample:
        return True
    nuls = sample.count(b"\x00")
    if nuls > 0 and (len(sample) == 0 or nuls / len(sample) > 0.15):
        return False
    control = sum(1 for b in sample if b < 0x09 or (0x0E <= b < 0x20) or b == 0x7F)
    return control / len(sample) < 0.30