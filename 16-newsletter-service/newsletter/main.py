"""FastAPI application: public subscribe/unsubscribe/tracking endpoints plus an
admin API (basic auth) for campaigns, subscribers and statistics.

Routing summary
===============

Public (no auth):
    POST /api/subscribe                     double opt-in signup (form or JSON)
    GET  /api/subscribe/confirm?email&token confirm the confirmation link
    GET  /api/unsubscribe?token             one-click CAN-SPAM unsubscribe
    GET  /api/track/open/{campaign_id}?sid  1x1 open pixel
    GET  /api/track/click/{campaign_id}?target&sid   tracking redirect

Admin (HTTP basic auth):
    GET    /api/admin/stats
    GET    /api/admin/subscribers
    POST   /api/admin/subscribers/import     upload CSV text
    GET    /api/admin/subscribers/export     CSV download
    GET    /api/admin/campaigns              list
    POST   /api/admin/campaigns              create
    GET    /api/admin/campaigns/{id}         fetch one
    POST   /api/admin/campaigns/{id}/send    bulk-send to ACTIVE subscribers

Plus minimal ``GET /`` (landing) and ``GET /admin`` stubs so the app responds
sensibly in a browser without investing in the stretch-goal JS dashboard.
"""

from __future__ import annotations

import secrets
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from newsletter import __version__
from newsletter.campaigns import (
    create_campaign,
    get_campaign,
    get_global_stats,
    import_subscribers,
    list_campaigns,
    list_subscribers,
    subscribers_to_csv,
)
from newsletter.config import settings
from newsletter.db import ainit_db, get_session
from newsletter.models import CampaignStatus
from newsletter.security import is_safe_redirect_url
from newsletter.sender import build_sender, send_campaign
from newsletter.subscribe import SubscribeError, confirm, subscribe, unsubscribe_by_token
from newsletter.tracking import TRANSPARENT_1PX_GIF, record_open, resolve_click_target

__all__ = ["app"]


# --- Pydantic response models -------------------------------------------------

class SubscribeOut(BaseModel):
    """Confirmation that a subscription was requested and a confirm email set."""

    email: str
    status: str
    message: str
    confirmation_sent: bool = True


class SubscriberOut(BaseModel):
    """Serialised subscriber for the admin API / stats."""

    id: int
    email: str
    name: Optional[str] = None
    status: str
    subscribed_at: Optional[str] = None
    confirmed_at: Optional[str] = None


class CampaignOut(BaseModel):
    """Serialised campaign."""

    id: int
    subject: str
    html_body: str = ""
    text_body: str = ""
    status: str
    created_at: Optional[str] = None
    sent_at: Optional[str] = None


class StatsOut(BaseModel):
    """Global dashboard numbers."""

    subscribers: int
    active: int
    pending: int
    unsubscribed: int
    sent: int
    opened: int
    clicked: int


class SendOut(BaseModel):
    """Result of an admin send-campaign run."""

    campaign_id: int
    status: str
    sent: int
    failed: int
    recipients: int


def _iso(dt) -> Optional[str]:
    return dt.isoformat() if dt else None


def _subscriber_out(s) -> SubscriberOut:
    return SubscriberOut(
        id=s.id,
        email=s.email,
        name=s.name,
        status=s.status,
        subscribed_at=_iso(s.subscribed_at),
        confirmed_at=_iso(s.confirmed_at),
    )


def _campaign_out(c) -> CampaignOut:
    return CampaignOut(
        id=c.id,
        subject=c.subject,
        html_body=c.html_body,
        text_body=c.text_body,
        status=c.status,
        created_at=_iso(c.created_at),
        sent_at=_iso(c.sent_at),
    )


# --- Admin basic auth ---------------------------------------------------------

_security = HTTPBasic(auto_error=False)


async def require_admin(
    credentials: Optional[HTTPBasicCredentials] = Depends(_security),
) -> HTTPBasicCredentials:
    """Reject the request unless basic-auth credentials match the configured
    admin user/password. Constant-time comparison avoids a timing oracle.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin credentials required.",
            headers={"WWW-Authenticate": "Basic"},
        )
    user_ok = secrets.compare_digest(
        credentials.username.encode("utf-8"), settings.admin_user.encode("utf-8")
    )
    pass_ok = secrets.compare_digest(
        credentials.password.encode("utf-8"), settings.admin_password.encode("utf-8")
    )
    if not (user_ok and pass_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect admin credentials.",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials


# --- App + lifespan -----------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create tables before the server accepts traffic (idempotent)."""
    await ainit_db()
    yield


app = FastAPI(title="Newsletter Service", version=__version__, lifespan=lifespan)


def _render_unsubscribe_page(sub) -> str:
    """Minimal standalone HTML page for a successful one-click unsubscribe."""
    company = settings.company_name
    name = sub.name or sub.email
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>Unsubscribed</title></head>
<body style="font-family:Arial,sans-serif;max-width:560px;margin:32px auto;color:#222;">
  <h1 style="color:#333;">You've been unsubscribed</h1>
  <p>Hi {name}, we've removed your email address from the {company} list. You won't receive future campaigns.</p>
  <p>If you change your mind later, you can re-subscribe at any time.</p>
</body>
</html>"""


# --- Public: subscribe --------------------------------------------------------

@app.post("/api/subscribe", response_model=SubscribeOut, status_code=201)
async def api_subscribe(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> SubscribeOut:
    """Double opt-in signup. Accepts either JSON (``{"email": .., "name": ..}``)
    or form-urlencoded (``email=..&name=..``) bodies. Returns 201 on success,
    400 for an invalid email.

    The body is parsed manually (rather than via a Pydantic body parameter) so
    that both JSON and form payloads are supported from a single endpoint without
    FastAPI's automatic content-type validation rejecting either.
    """
    content_type = request.headers.get("content-type", "").lower()
    email: Optional[str] = None
    name: Optional[str] = None

    if "application/json" in content_type:
        body = await request.json()
        email = (body.get("email") or "").strip()
        name = (body.get("name") or "").strip() or None
    elif "x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type:
        form = await request.form()
        email = (form.get("email") or "").strip()
        name = (form.get("name") or "").strip() or None
    else:
        # Unknown content type: fall back to treating the raw UTF-8 body as JSON.
        raw = (await request.body()).decode("utf-8", errors="replace")
        if raw.strip().startswith("{"):
            body = await request.json()
            email = (body.get("email") or "").strip()
            name = (body.get("name") or "").strip() or None

    if not email:
        raise HTTPException(status_code=400, detail="An email address is required.")

    try:
        sub = await subscribe(session, email, name=name)
    except SubscribeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return SubscribeOut(
        email=sub.email,
        status=sub.status,
        message="Subscription requested; check your inbox to confirm.",
    )


@app.get("/api/subscribe/confirm", response_model=SubscribeOut)
async def api_subscribe_confirm(
    email: str = Query(...),
    token: str = Query(...),
    session: AsyncSession = Depends(get_session),
) -> SubscribeOut:
    """Confirm a pending double opt-in subscription (link click)."""
    try:
        sub = await confirm(session, email, token)
    except SubscribeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return SubscribeOut(
        email=sub.email,
        status=sub.status,
        message="Your subscription is confirmed. Welcome aboard!",
        confirmation_sent=False,
    )


# --- Public: unsubscribe ------------------------------------------------------

@app.get("/api/unsubscribe", response_class=HTMLResponse)
async def api_unsubscribe(
    token: str = Query(...),
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    """One-click CAN-SPAM unsubscribe. Verifies the HMAC token, marks the
    subscriber UNSUBSCRIBED, and renders a confirmation HTML page. Invalid or
    forged tokens get a 400 so they cannot be silently ignored.
    """
    sub = await unsubscribe_by_token(session, token)
    if sub is None:
        raise HTTPException(
            status_code=400, detail="Invalid or expired unsubscribe token."
        )

    # Send a CAN-SPAM notice (goes to the outbox with the FileSender backend).
    from newsletter.mailer import Mailer

    try:
        await build_sender().send(Mailer().unsubscribed_notice(sub))
    except Exception:  # pragma: no cover - a notice must not break the page
        pass

    return HTMLResponse(content=_render_unsubscribe_page(sub), status_code=200)


# --- Public: tracking ---------------------------------------------------------

@app.get("/api/track/open/{campaign_id}")
async def api_track_open(
    campaign_id: int,
    sid: Optional[int] = Query(None),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Open-tracking pixel: records the open and returns a 1x1 transparent GIF
    with ``Cache-Control: no-store`` so every view is counted."""
    await record_open(session, campaign_id, sid)
    return Response(
        content=TRANSPARENT_1PX_GIF,
        media_type="image/gif",
        headers={
            "Cache-Control": "no-store",
            "Content-Length": str(len(TRANSPARENT_1PX_GIF)),
        },
    )


@app.get("/api/track/click/{campaign_id}")
async def api_track_click(
    campaign_id: int,
    target: str = Query(...),
    sid: Optional[int] = Query(None),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Click-redirect endpoint: records the click, then 307-redirects to the
    target only if it is safe. Unsafe destinations receive a neutral 200 page,
    so an open-redirect is impossible."""
    resolved = await resolve_click_target(session, campaign_id, sid, target)
    if resolved is not None and is_safe_redirect_url(resolved):
        return RedirectResponse(resolved, status_code=307)
    return PlainTextResponse(
        content="This link could not be followed because it is untrusted.",
        status_code=200,
    )


# --- Admin: stats / subscribers -----------------------------------------------

@app.get("/api/admin/stats", response_model=StatsOut)
async def admin_stats(
    _: HTTPBasicCredentials = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> StatsOut:
    return StatsOut(**await get_global_stats(session))


@app.get("/api/admin/subscribers", response_model=list[SubscriberOut])
async def admin_subscribers(
    status_filter: Optional[str] = Query(None, alias="status"),
    _: HTTPBasicCredentials = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> list[SubscriberOut]:
    rows = await list_subscribers(session, status=status_filter)
    return [_subscriber_out(s) for s in rows]


@app.post("/api/admin/subscribers/import")
async def admin_subscribers_import(
    request: Request,
    _: HTTPBasicCredentials = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Import subscribers from a raw CSV body (email,name per line). JSON body
    ``{"text": "..."}`` is also accepted for convenience."""
    content_type = request.headers.get("content-type", "")
    if "json" in content_type:
        body = await request.json()
        text = body.get("text", "")
    else:
        text = (await request.body()).decode("utf-8", errors="replace")
    if not text.strip():
        raise HTTPException(status_code=400, detail="Empty CSV body.")
    return await import_subscribers(session, text)


@app.get("/api/admin/subscribers/export")
async def admin_subscribers_export(
    _: HTTPBasicCredentials = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Download the full subscriber list as CSV."""
    rows = await list_subscribers(session)
    return Response(
        content=subscribers_to_csv(rows),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="subscribers.csv"'},
    )


# --- Admin: campaigns ---------------------------------------------------------

class CampaignIn(BaseModel):
    subject: str = Field(..., min_length=1)
    html_body: Optional[str] = ""
    text_body: Optional[str] = ""


class CampaignCreateOut(CampaignOut):
    """Same shape as CampaignOut; kept distinct so the create endpoint can set a
    specific status code without confusion."""


@app.get("/api/admin/campaigns", response_model=list[CampaignOut])
async def admin_campaigns(
    _: HTTPBasicCredentials = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> list[CampaignOut]:
    return [_campaign_out(c) for c in await list_campaigns(session)]


@app.post("/api/admin/campaigns", response_model=CampaignOut, status_code=201)
async def admin_campaigns_create(
    payload: CampaignIn,
    _: HTTPBasicCredentials = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> CampaignOut:
    try:
        c = await create_campaign(
            session, payload.subject, payload.html_body or "", payload.text_body or ""
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _campaign_out(c)


@app.get("/api/admin/campaigns/{campaign_id}", response_model=CampaignOut)
async def admin_campaign_get(
    campaign_id: int,
    _: HTTPBasicCredentials = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> CampaignOut:
    c = await get_campaign(session, campaign_id)
    if c is None:
        raise HTTPException(status_code=404, detail="Campaign not found.")
    return _campaign_out(c)


@app.post("/api/admin/campaigns/{campaign_id}/send", response_model=SendOut)
async def admin_campaign_send(
    campaign_id: int,
    _: HTTPBasicCredentials = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> SendOut:
    """Send a campaign to every ACTIVE subscriber (rate-limited). Uses the
    configured sender (FileSender in tests/offline) so nothing leaves the box."""
    c = await get_campaign(session, campaign_id)
    if c is None:
        raise HTTPException(status_code=404, detail="Campaign not found.")
    if c.status == CampaignStatus.SENT.value and c.sent_at is not None:
        raise HTTPException(status_code=409, detail="Campaign has already been sent.")
    result = await send_campaign(session, c, rate_limit=settings.rate_per_min)
    return SendOut(campaign_id=campaign_id, status=c.status, **result)


# --- Minimal web stubs (full JS dashboard is a stretch goal) ------------------

@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    return HTMLResponse(
        content=(
            "<!DOCTYPE html><html><head><meta charset='utf-8'><title>Newsletter</title></head>"
            "<body style='font-family:Arial,sans-serif;max-width:600px;margin:48px auto;color:#222;'>"
            "<h1>Newsletter Service</h1>"
            "<p>Subscribe with <code>POST /api/subscribe</code> (JSON or form of "
            "<code>{\"email\": ..., \"name\": ...}</code>).</p>"
            "<p>API reference: <code>/docs</code>. Admin API requires basic auth.</p>"
            "</body></html>"
        ),
        status_code=200,
    )


@app.get("/admin", response_class=HTMLResponse)
async def admin_stub() -> HTMLResponse:
    return HTMLResponse(
        content=(
            "<!DOCTYPE html><html><head><meta charset='utf-8'><title>Admin</title></head>"
            "<body style='font-family:Arial,sans-serif;max-width:600px;margin:48px auto;'>"
            "<h1>Admin</h1><p>Use the JSON API (see <code>/docs</code>) with basic auth.</p>"
            "</body></html>"
        ),
        status_code=200,
    )