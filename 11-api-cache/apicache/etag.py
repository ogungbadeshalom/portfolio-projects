"""ETag / If-None-Match helpers for conditional HTTP caching.

When an origin response carries an ``ETag`` we store it with the entry so a
subsequent ``get_or_fetch`` call can send ``If-None-Match``; a 304 lets us
refresh the TTL without downloading the body again.
"""
from __future__ import annotations

from typing import Any, Optional


def extract_etag(headers: Any) -> Optional[str]:
    """Return the ``ETag`` header value from a response-like object.

    Accepts anything exposing ``.headers`` mapping that can be queried with
    ``.get("etag")`` (an ``httpx.Response``, a ``dict``, etc.).
    """
    if headers is None:
        return None
    if isinstance(headers, dict):
        etag = headers.get("etag") or headers.get("ETag")
    else:
        etag = headers.get("etag")
    if not etag:
        return None
    return etag


def build_if_none_match(etag: str | None) -> dict[str, str]:
    """Build the ``If-None-Match`` request header from a stored ETag.

    Returns an empty dict when there is no ETag to send.
    """
    if not etag:
        return {}
    return {"If-None-Match": etag}


def is_not_modified(status_code: int) -> bool:
    """Whether a status code indicates ``304 Not Modified``."""
    return status_code == 304


def derive_etag(key: str, value: Any) -> str:
    """Derive a stable ETag from a key+value (fallback when origin sends none)."""
    from apicache.storage import content_hash

    return f'"{content_hash(key, value)}"'