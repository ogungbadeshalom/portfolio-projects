"""API-key authentication, rate limiting, and quota gate for /v1/*.

An ASGI ``BaseHTTPMiddleware`` sits in front of every request. For paths under
``/v1/`` it:

1. extracts and verifies the ``X-API-Key`` (HMAC lookup -> tenant)  [401]
2. checks the per-tenant, per-endpoint sliding-window rate limit       [429]
3. checks the tenant's monthly quota                                   [402]
4. runs the proxied route, then stamps ``X-RateLimit-*`` headers.

Errors follow the structured envelope: ``{"error": {"code", "message",
"request_id"}}``.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, Optional

import httpx
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from gateway import keys
from gateway.config import settings
from gateway.database import get_session_factory
from gateway.models import ApiKey, Tenant
from gateway.quota import check_quota
from gateway.ratelimit import check_limit

logger = logging.getLogger(__name__)

_V1_PREFIX = "/v1/"


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Gate /v1/* requests with API key + rate limit + quota."""

    def __init__(self, app, *, rate_limit: Optional[int] = None, window: Optional[int] = None):
        super().__init__(app)
        self._rate_limit = rate_limit if rate_limit is not None else settings.rate_limit_default
        self._window = window if window is not None else settings.rate_limit_window_seconds

    async def dispatch(self, request: Request, call_next) -> Response:
        if not request.url.path.startswith(_V1_PREFIX):
            return await call_next(request)

        request_id = str(uuid.uuid4())[:12]

        plaintext = request.headers.get("X-API-Key")
        db = get_session_factory()()
        try:
            api_key = keys.verify_key(db, plaintext or "") if plaintext else None
            if api_key is None:
                return _error(401, "invalid_api_key", "Missing or invalid API key", request_id, auth=True)

            tenant: Optional[Tenant] = db.query(Tenant).filter(Tenant.id == api_key.tenant_id).first()
            if tenant is None:  # pragma: no cover - FK invariant
                return _error(401, "invalid_tenant", "Tenant not found", request_id, auth=True)

            endpoint = request.url.path

            # 2. Rate limit (per tenant, per endpoint) -> 429.
            decision = check_limit(
                tenant.id, endpoint, limit=self._rate_limit, window_seconds=self._window
            )
            if not decision.allowed:
                resp = _error(
                    429,
                    "rate_limited",
                    "Too many requests",
                    request_id,
                    headers={"Retry-After": str(max(1, int(decision.retry_after)))},
                )
                return _with_rate_headers(resp, decision, self._rate_limit)

            # 3. Quota (per tenant, per month) -> 402.
            quota = check_quota(db, tenant)
            if not quota.allowed:
                return _error(
                    402,
                    "quota_exceeded",
                    f"Monthly quota exceeded ({quota.used}/{quota.limit}); upgrade to raise it",
                    request_id,
                    headers={"Link": '</upgrade>; rel="upgrade"'},
                )

            # The proxied route reads these off request.state.
            request.state.gateway = {
                "tenant_id": tenant.id,
                "api_key_id": api_key.id,
                "request_id": request_id,
                "rate_decision": decision,
            }

            response = await call_next(request)
            return _with_rate_headers(response, decision, self._rate_limit)
        finally:
            db.close()


def _with_rate_headers(response: Response, decision, limit: int) -> Response:
    response.headers["X-RateLimit-Limit"] = str(limit)
    response.headers["X-RateLimit-Remaining"] = str(decision.remaining)
    response.headers["X-RateLimit-Reset"] = str(int(decision.retry_after))
    return response


def _error(
    status: int,
    code: str,
    message: str,
    request_id: str,
    *,
    auth: bool = False,
    headers: Optional[Dict[str, str]] = None,
) -> JSONResponse:
    body = {"error": {"code": code, "message": message, "request_id": request_id}}
    hdrs = dict(headers or {})
    if auth:
        hdrs.setdefault("WWW-Authenticate", "API-Key")
    return JSONResponse(body, status_code=status, headers=hdrs)