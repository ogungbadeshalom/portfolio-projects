"""Replay captured requests.

``replay_request`` reconstructs a stored request from SQLite (method, exact
headers, raw body bytes, query params) and fires it at a target URL with an
optional delay. Replay preserves the original request as faithfully as
possible: original method, original query string, original body, and (almost)
all original headers.

Host-bound headers are excluded by default so a replay to a *different* target
behaves like a fresh delivery from a utility — ``Host`` and hop-by-hop headers
like ``Content-Length`` are dropped and re-derived by httpx.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from .database import get_request
from .models import CapturedRequest, ReplayRequest, ReplayResponse

logger = logging.getLogger(__name__)

#: Injectable httpx transport for the outbound replay hop (tests set this to an
#: ASGI echo transport so no request leaves the process).
_replay_transport: Optional[httpx.AsyncBaseTransport] = None


def set_replay_transport(transport: Optional[httpx.AsyncBaseTransport]) -> None:
    """Install a custom httpx transport for replay sends (used by tests)."""
    global _replay_transport
    _replay_transport = transport


def _effective_transport(
    override: Optional[httpx.AsyncBaseTransport],
) -> Optional[httpx.AsyncBaseTransport]:
    return override if override is not None else _replay_transport

#: Headers that must not be copied verbatim onto a different target.
_HOP_BY_HOP = {
    "host",
    "content-length",
    "connection",
    "keep-alive",
    "transfer-encoding",
    "upgrade",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
}


def reconstruct_headers(record: CapturedRequest) -> Dict[str, str]:
    """Flatten a stored ``{name: [values]}`` header map, minus hop-by-hop."""
    stored = json.loads(record.headers_json) if record.headers_json else {}
    out: Dict[str, str] = {}
    for name, values in stored.items():
        lower = name.lower()
        if lower in _HOP_BY_HOP:
            continue
        out[name] = ", ".join(values) if values else ""
    return out


def build_target_url(base: str, original_path: str, query_json: str) -> str:
    """Join ``base`` with a (possibly differing) path + original query string.

    ``base`` may include a trailing slash; the stored request's path and query
    params are preserved so a replay reproduces the original request exactly.
    """
    base = base.rstrip("/")
    path = original_path or ""
    if not path.startswith("/"):
        path = "/" + path
    query = _query_string(query_json)
    return f"{base}{path}" + (f"?{query}" if query else "")


def _query_string(query_json: str) -> str:
    import urllib.parse

    try:
        params = json.loads(query_json)
    except (TypeError, ValueError):
        return ""
    if not isinstance(params, dict):
        return ""
    parts: List[str] = []
    for name in sorted(params):
        for value in params.get(name) or [""]:
            parts.append(f"{urllib.parse.quote(str(name))}={urllib.parse.quote(str(value))}")
    return "&".join(parts)


async def replay_request(
    session: AsyncSession,
    request_id: int,
    *,
    target: str,
    delay_ms: int = 0,
    path: Optional[str] = None,
    transport: Optional[httpx.AsyncBaseTransport] = None,
) -> Optional[ReplayResponse]:
    """Replay the stored request ``request_id`` against ``target``.

    Returns ``None`` if the stored request does not exist. Body bytes are sent
    exactly as captured; headers are reconstructed minus hop-by-hop.
    """
    record = await get_request(session, request_id)
    if record is None:
        return None

    if delay_ms:
        await asyncio.sleep(delay_ms / 1000.0)

    headers = reconstruct_headers(record)
    final_path = path if path is not None else record.path
    url = build_target_url(target, final_path, record.query_json)

    method = record.method
    content: Any = record.body if record.body is not None else None

    client_kwargs: Dict[str, Any] = {"timeout": httpx.Timeout(30.0)}
    effective = _effective_transport(transport)
    if effective is not None:
        client_kwargs["transport"] = effective

    async with httpx.AsyncClient(**client_kwargs) as client:
        request = httpx.Request(method, url, headers=headers, content=content)
        response = await client.send(request)

    body = response.content if not _is_text_like(response.headers) else response.content
    return ReplayResponse(
        status_code=response.status_code,
        headers=response_headers_as_dict(response.headers),
        body=body,
    )


def _is_text_like(headers: httpx.Headers) -> bool:
    ctype = headers.get("content-type", "")
    return "json" in ctype or "text/" in ctype or "html" in ctype


def response_headers_as_dict(headers: httpx.Headers) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for name, value in headers.multi_items():
        out.setdefault(name.lower(), []).append(value)
    return out