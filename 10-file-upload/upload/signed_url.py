"""HMAC-SHA256 signed URLs with expiration.

A signed download URL looks like::

    /files/{hash}?expires={unix_ts}&sig={hex_hmac}

The signature covers ``file:expires`` so it cannot be replayed after expiry
and cannot be reused against a different file hash.
"""
from __future__ import annotations

import hashlib
import hmac
import time
from urllib.parse import urlencode, urlsplit, urlunsplit

from upload.config import settings


def _sig(secret: str, file_hash: str, expires: int) -> str:
    """Compute the HMAC-SHA256 signature for a file/expiry pair."""
    message = f"{file_hash}:{expires}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def generate_signed_url(
    file_hash: str,
    expires_in: int | None = None,
    base_url: str = "/files",
) -> str:
    """Build a signed download URL for ``file_hash``.

    Args:
        file_hash: Content-addressable hash of the stored file.
        expires_in: Lifetime (seconds) of the URL from now.
        base_url: Prefix to hang the query string on; defaults to ``/files``.

    Returns:
        A URL string with ``?expires=...&sig=...`` appended.
    """
    expires_in = settings.expires_in if expires_in is None else int(expires_in)
    expires = int(time.time()) + expires_in
    sig = _sig(settings.secret, file_hash, expires)
    path = f"{base_url.rstrip('/')}/{file_hash}"
    return urlunsplit(("", "", path, urlencode({"expires": expires, "sig": sig}), ""))


def verify_signature(file_hash: str, expires: str | int, sig: str) -> bool:
    """Check ``sig`` against the expected MAC and the expiry timestamp.

    Uses :func:`hmac.compare_digest` for constant-time comparison to resist
    timing attacks.

    Returns:
        ``True`` if the signature is valid and not expired, else ``False``.
    """
    try:
        expires_int = int(expires)
    except (TypeError, ValueError):
        return False
    if expires_int < int(time.time()):
        return False  # expired / replay
    expected = _sig(settings.secret, file_hash, expires_int)
    return hmac.compare_digest(expected, sig)