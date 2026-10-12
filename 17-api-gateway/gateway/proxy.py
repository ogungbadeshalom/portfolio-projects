"""Proxy: forward an approved gateway request to the backend service.

The proxy is intentionally thin — it streams the body through (never buffers
the whole payload) and returns the backend's status, body, and relevant
headers. ``backend_base_url`` comes from settings; a custom ``httpx``
transport can be injected so tests can serve an in-process ASGI echo backend
with zero network I/O.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional, Tuple

import httpx
from starlette.requests import Request

from gateway.config import settings

logger = logging.getLogger(__name__)

#: Injectable httpx transport/callable for tests (a real pool by default).
_backend_transport = None

#: Upstream response headers we never pass through (hop-by-hop).
_HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "transfer-encoding",
    "upgrade",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
}


def configure_backend_transport(transport=None) -> None:
    """Install a custom httpx transport for backend calls (tests use an ASGI
    or mock transport so no real network is hit)."""
    global _backend_transport
    _backend_transport = transport


def proxy_request(
    request: Request,
    path: str,
    body: bytes = b"",
    *,
    method: Optional[str] = None,
) -> Tuple[int, bytes, Dict[str, str], int]:
    """Forward ``request`` to ``{backend_base_url}/{path}`` and stream back.

    ``body`` is passed explicitly (the route awaits ``request.body()`` before
    calling, so the middleware never has to touch the stream).

    Returns ``(status_code, body_bytes, response_headers, latency_ms)``.
    """
    url = settings.backend_base_url.rstrip("/") + "/" + path.lstrip("/")
    method = (method or request.method).upper()

    headers = _forward_headers(request)

    client_kwargs: Dict[str, Any] = {"timeout": httpx.Timeout(settings.proxy_timeout)}
    if _backend_transport is not None:
        client_kwargs["transport"] = _backend_transport

    start = time.monotonic()
    try:
        with httpx.Client(**client_kwargs) as client:
            # stream() keeps us from buffering the upstream body ourselves.
            with client.stream(method, url, headers=headers, content=body) as resp:
                response_body = b"".join(resp.iter_bytes())
                status = resp.status_code
                passthrough = {
                    k: v for k, v in resp.headers.items() if k.lower() not in _HOP_BY_HOP_HEADERS
                }
    except httpx.HTTPError as exc:
        logger.warning("Backend proxy error for %s: %s", path, exc)
        return 502, b'{"error":"BadGateway"}', {"content-type": "application/json"}, 0
    finally:
        latency_ms = int((time.monotonic() - start) * 1000)

    return status, response_body, passthrough, latency_ms


def _forward_headers(request: Request) -> Dict[str, str]:
    """Select headers to forward to the backend (drop hop-by-hop + auth)."""
    skip = {"host", "authorization", "x-api-key", "content-length", "connection", "transfer-encoding"}
    out: Dict[str, str] = {}
    for name, value in request.headers.items():
        if name.lower() in skip:
            continue
        out[name] = value
    # The backend usually wants to know the real caller (the tenant).
    return out