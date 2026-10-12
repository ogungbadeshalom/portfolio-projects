"""Request capturing: the /incoming/{token} trap endpoint.

Any HTTP method, any content type. The full request (headers with multi-value
support, raw body bytes, query params, source IP) is persisted to SQLite and a
200 is returned. In forward mode the body is also streamed to a live endpoint.
"""

from __future__ import annotations

import json
from typing import Dict, List

from fastapi import APIRouter, Depends, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from .database import get_db
from .forwarder import get_forward_url
from .models import CapturedRequest, CaptureOut

router = APIRouter()


def headers_as_dict(headers) -> Dict[str, List[str]]:
    """Flatten a Starlette ``Headers`` into a ``{name: [values]}`` dict,
    preserving duplicates and lower-casing names.

    Starlette's ``Headers`` object no longer exposes ``multi_items()``; we read
    the raw ``(bytes, bytes)`` list instead, which preserves multi-value headers
    (e.g. duplicate ``Accept`` or ``Set-Cookie``) exactly as received.
    """
    out: Dict[str, List[str]] = {}
    for raw_name, raw_value in headers.raw:
        name = raw_name.decode("latin-1").lower()
        value = raw_value.decode("latin-1")
        out.setdefault(name, []).append(value)
    return out


def query_as_dict(query) -> Dict[str, List[str]]:
    """Convert a parsed query string into ``{name: [values]}`` (multi-value
    aware). Preserves empty values as empty strings.
    """
    out: Dict[str, List[str]] = {}
    for name, value in query.multi_items():  # type: ignore[attr-defined]
        out.setdefault(name, []).append(value)
    return out


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client is not None:
        return request.client.host
    return ""


def _store(
    request: Request,
    token: str,
    path: str,
    body: bytes,
    session: AsyncSession,
) -> CapturedRequest:
    record = CapturedRequest(
        token=token,
        method=request.method,
        path=path,
        headers_json=json.dumps(headers_as_dict(request.headers)),
        body=body or None,
        query_json=json.dumps(query_as_dict(request.query_params)),
        source_ip=client_ip(request) or None,
    )
    session.add(record)
    return record


@router.api_route(
    "/incoming/{token}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "TRACE"],
)
async def incoming(
    token: str, request: Request, session: AsyncSession = Depends(get_db)
) -> Response:
    """Capture any webhook. Streams the body to forward mode live, then stores
    a persistent copy and returns 200.
    """
    forward_url = await get_forward_url(token)

    # Stream the raw body so forward mode never buffers huge payloads.
    body_parts: List[bytes] = []
    async for chunk in request.stream():
        body_parts.append(chunk)
        if forward_url:
            # non-blocking fan-out handled by forwarder; here we just collect.
            await _push_forward_chunk(token, chunk)
    body = b"".join(body_parts)

    if forward_url and body_parts:
        await _finish_forward(token)

    record = _store(request, token, str(request.url.path), body, session)
    await session.commit()
    await session.refresh(record)

    if request.method == "HEAD":
        return Response(status_code=200)

    payload = CaptureOut(id=record.id, token=token, received_at=record.received_at.isoformat())
    return JSONResponse(content=jsonable_encoder(payload), status_code=202)


# --------------------------------------------------------------------------- #
# Forward-mode helpers (imported lazily to avoid a circular import at startup).
# --------------------------------------------------------------------------- #

from .forwarder import _push_forward_chunk, _finish_forward  # noqa: E402


def make_handler_docs() -> str:
    return "Capture endpoint for /incoming/{token}"


# A second, body-bearing route for clients that stream via raw body rather
# than form parsing. Kept as an explicit alias so both POST and GET code
# paths map cleanly to the same store logic.
@router.post("/raw/{token}")
async def incoming_raw_body(token: str, request: Request, session: AsyncSession = Depends(get_db)):
    body = await request.body()
    return await _store_response(request, token, body, session)


async def _store_response(
    request: Request, token: str, body: bytes, session: AsyncSession
) -> Response:
    record = _store(request, token, str(request.url.path), body, session)
    await session.commit()
    await session.refresh(record)
    return PlainTextResponse(f"ok {record.id}", status_code=200)