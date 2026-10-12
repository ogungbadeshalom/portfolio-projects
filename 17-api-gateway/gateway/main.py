"""FastAPI application for the multi-tenant API gateway.

Endpoints
---------
* ``POST   /api/auth/register``  -- create a tenant (email + password)
* ``POST   /api/auth/login``     -- verify credentials -> JWT
* ``POST   /api/keys``           -- create an API key (JWT-guarded)
* ``GET    /api/keys``           -- list my keys (JWT-guarded)
* ``DELETE /api/keys/{id}``      -- revoke a key (JWT-guarded)
* ``GET    /api/usage``          -- my usage stats (JWT-guarded)
* ``/v1/{path}``                 -- proxied protected backend (X-API-Key)

``create_app`` is the factory: it wires the gate middleware + proxy transport
so tests can build isolated apps (fresh SQLite, in-process ASGI backend).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from gateway import keys, proxy, usage
from gateway.auth import bearer_token, decode_jwt, encode_jwt, hash_password, verify_password
from gateway.config import settings
from gateway.database import dispose, get_db, init_db
from gateway.middleware import APIKeyMiddleware
from gateway.models import ApiKey, Tenant

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Schemas
# --------------------------------------------------------------------------- #
class RegisterBody(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=6, max_length=255)
    name: str = ""
    plan: Optional[str] = None


class LoginBody(BaseModel):
    email: str
    password: str


class KeyCreateBody(BaseModel):
    name: str = ""
    expires_in_days: Optional[int] = None


class KeyOut(BaseModel):
    id: int
    name: str
    prefix: str
    key: str  # full plaintext (shown once, at creation)
    expires_at: Optional[str] = None


class TenantOut(BaseModel):
    id: int
    email: str
    name: str
    plan: str


# --------------------------------------------------------------------------- #
# App factory
# --------------------------------------------------------------------------- #
def create_app(
    *,
    database_url: Optional[str] = None,
    backend_transport=None,
    rate_limit: Optional[int] = None,
    rate_window: Optional[int] = None,
) -> FastAPI:
    """Build a gateway. ``iinit_db`` (or a fresh URL) is set up here, and the
    backend transport can be swapped for an in-process ASGI echo in tests."""
    init_db(database_url)
    proxy.configure_backend_transport(backend_transport)

    app = FastAPI(title="Multi-Tenant API Gateway", version="1.0.0")
    app.add_middleware(
        APIKeyMiddleware, rate_limit=rate_limit, window=rate_window
    )
    _register_routes(app)
    return app


def _register_routes(app: FastAPI) -> None:
    @app.post("/api/auth/register", response_model=TenantOut)
    def register(body: RegisterBody, db: Session = Depends(get_db)):
        existing = db.query(Tenant).filter(Tenant.email == body.email).first()
        if existing:
            raise HTTPException(status_code=409, detail="email already registered")
        tenant = Tenant(
            email=body.email.lower(),
            name=body.name,
            password_hash=hash_password(body.password),
            plan=(body.plan or "free") if (body.plan or "free") in settings.plan_quotas else "free",
        )
        db.add(tenant)
        db.commit()
        db.refresh(tenant)
        return TenantOut(id=tenant.id, email=tenant.email, name=tenant.name, plan=tenant.plan)

    @app.post("/api/auth/login")
    def login(body: LoginBody, db: Session = Depends(get_db)):
        tenant = db.query(Tenant).filter(Tenant.email == body.email.lower()).first()
        if tenant is None or not verify_password(body.password, tenant.password_hash):
            raise HTTPException(status_code=401, detail="invalid credentials")
        token = encode_jwt({"sub": tenant.id, "email": tenant.email, "plan": tenant.plan})
        return {"token": token, "token_type": "bearer"}

    def current_user(authorization: str, db: Session) -> Tenant:
        """Dependency: authenticate the Bearer JWT for the admin routes."""
        token = bearer_token(authorization)
        if not token:
            raise HTTPException(status_code=401, detail="missing bearer token")
        try:
            claims = decode_jwt(token)
        except ValueError:
            raise HTTPException(status_code=401, detail="invalid or expired token")
        tenant = db.query(Tenant).filter(Tenant.id == claims["sub"]).first()
        if tenant is None:
            raise HTTPException(status_code=401, detail="unknown tenant")
        return tenant

    @app.post("/api/keys", response_model=KeyOut)
    def create_key(
        body: KeyCreateBody,
        authorization: str = Header(""),
        db: Session = Depends(get_db),
    ):
        tenant = current_user(authorization, db)
        plaintext = keys.generate_key()
        from datetime import datetime, timedelta, timezone

        expires_at = None
        if body.expires_in_days:
            expires_at = datetime.now(timezone.utc) + timedelta(days=body.expires_in_days)
        api_key = ApiKey(
            tenant_id=tenant.id,
            key_hash=keys.hash_key(plaintext),
            prefix=keys.KEY_PREFIX,
            name=body.name,
            expires_at=expires_at,
            revoked=False,
        )
        db.add(api_key)
        db.commit()
        db.refresh(api_key)
        return KeyOut(
            id=api_key.id,
            name=api_key.name,
            prefix=api_key.prefix,
            key=plaintext,
            expires_at=expires_at.isoformat() if expires_at else None,
        )

    @app.get("/api/keys")
    def list_keys(authorization: str = Header(""), db: Session = Depends(get_db)):
        tenant = current_user(authorization, db)
        rows = db.query(ApiKey).filter(ApiKey.tenant_id == tenant.id).all()
        return [
            {
                "id": k.id,
                "name": k.name,
                "prefix": k.prefix,
                "revoked": k.revoked,
                "last_used_at": k.last_used_at,
                "expires_at": k.expires_at,
            }
            for k in rows
        ]

    @app.delete("/api/keys/{key_id}")
    def revoke_key(key_id: int, authorization: str = Header(""), db: Session = Depends(get_db)):
        tenant = current_user(authorization, db)
        api_key = db.query(ApiKey).filter(ApiKey.id == key_id, ApiKey.tenant_id == tenant.id).first()
        if api_key is None:
            raise HTTPException(status_code=404, detail="key not found")
        api_key.revoked = True
        db.commit()
        return {"revoked": key_id}

    @app.get("/api/usage")
    def my_usage(authorization: str = Header(""), db: Session = Depends(get_db)):
        tenant = current_user(authorization, db)
        usage.flush_now()  # make pending batched rows visible to the query
        return usage.usage_stats(db, tenant.id)

    @app.api_route("/v1/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
    async def proxy_route(path: str, request: Request):
        """Proxied protected endpoint. The APIKeyMiddleware guards entry and
        attaches the tenant context to ``request.state.gateway``."""
        gw = getattr(request.state, "gateway", None)
        tenant_id = (gw or {}).get("tenant_id")

        body = await request.body()
        status, resp_body, resp_headers, latency = proxy.proxy_request(request, path, body)

        if tenant_id is not None:
            usage.log_usage(tenant_id, f"/v1/{path}", request.method, status, latency)

        return Response(
            content=resp_body,
            status_code=status,
            headers=resp_headers,
            media_type=resp_headers.get("content-type", None),
        )

    @app.get("/health")
    def health():
        return {"status": "ok", "service": "api-gateway"}


# Provide a module-level app for `uvicorn gateway.main:app`.
app = create_app()