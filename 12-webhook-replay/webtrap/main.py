"""Webhook Replay & Debug Tool — FastAPI application.

Serves:
* ``/incoming/{token}``  -- the capture endpoint (any method, any body).
* ``/``                  -- web UI listing captured requests.
* ``/request/{id}``      -- web UI inspecting one request + replay button.
* ``/api/...``           -- JSON API for the UI and external tooling.

Jinja2 templates live in ``webtrap/templates``; the router is registered from
:mod:`webtrap.capture`.
"""

from __future__ import annotations

import json
import logging
import secrets
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from . import capture
from .database import (
    count_requests,
    create_tables,
    delete_request,
    get_db,
    get_request,
    init_db,
    list_requests,
)
from .forwarder import clear_target_sync, forwards_snapshot, get_forwarder, set_target_sync
from .models import CapturedRequest, CaptureOut, ReplayRequest, ReplayResponse
from .replay import replay_request

logger = logging.getLogger(__name__)

BASE_DIR = __import__("pathlib").Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise the async engine + tables once on startup."""
    init_db()
    await create_tables()
    yield


app = FastAPI(title="Webhook Replay & Debug Tool", lifespan=lifespan)
app.include_router(capture.router)

_static_dir = BASE_DIR / "static"
if _static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


# --------------------------------------------------------------------------- #
# Pydantic request bodies for the API
# --------------------------------------------------------------------------- #
class TrapCreate(BaseModel):
    """Body for ``POST /api/traps``: optionally attach a forward URL."""

    forward_url: Optional[str] = None
    description: Optional[str] = None


class ForwardConfig(BaseModel):
    """Body for ``POST /api/forward``: set/clear a token's mirror target."""

    token: str
    url: Optional[str] = None  # None clears the target


class ReplayBody(BaseModel):
    """Body for ``POST /api/requests/{id}/replay``."""

    target: str
    delay_ms: int = 0


# --------------------------------------------------------------------------- #
# Web UI
# --------------------------------------------------------------------------- #
@app.get("/", response_class=HTMLResponse)
async def index(request: Request, session: AsyncSession = Depends(get_db)):
    rows = await list_requests(session, limit=200)
    total = await count_requests(session)
    return templates.TemplateResponse(
        request, "list.html", {"rows": rows, "total": total}
    )


@app.get("/request/{request_id}", response_class=HTMLResponse)
async def inspect(request: Request, request_id: int, session: AsyncSession = Depends(get_db)):
    record = await get_request(session, request_id)
    if record is None:
        return HTMLResponse("Not found", status_code=404)
    return templates.TemplateResponse(
        request, "inspect.html", {"record": record, "curl": curl_command(record)}
    )


# --------------------------------------------------------------------------- #
# JSON API
# --------------------------------------------------------------------------- #
@app.get("/api/requests")
async def api_list_requests(session: AsyncSession = Depends(get_db)):
    return [r.to_dict() for r in await list_requests(session, limit=100)]


@app.get("/api/requests/{request_id}")
async def api_get_request(request_id: int, session: AsyncSession = Depends(get_db)):
    record = await get_request(session, request_id)
    if record is None:
        raise HTTPException(status_code=404, detail="request not found")
    return record.to_dict()


@app.delete("/api/requests/{request_id}")
async def api_delete_request(request_id: int, session: AsyncSession = Depends(get_db)):
    ok = await delete_request(session, request_id)
    if not ok:
        raise HTTPException(status_code=404, detail="request not found")
    return {"deleted": request_id}


@app.post("/api/requests/{request_id}/replay", response_model=ReplayResponse)
async def api_replay(request_id: int, body: ReplayBody, session: AsyncSession = Depends(get_db)):
    result = await replay_request(session, request_id, target=body.target, delay_ms=body.delay_ms)
    if result is None:
        raise HTTPException(status_code=404, detail="request not found")
    return result


@app.get("/api/tokens")
async def api_list_tokens(session: AsyncSession = Depends(get_db)):
    """Return the set of distinct trap tokens plus any forward targets."""
    rows = await list_requests(session, limit=10000)
    tokens = sorted({r.token for r in rows})
    fwd = forwards_snapshot()
    return {"tokens": [{"token": t, "forward_url": fwd.get(t)} for t in tokens]}


@app.post("/api/traps", response_model=CaptureOut)
async def api_create_trap(body: TrapCreate):
    """Generate a fresh trap URL; optionally attach a forward target."""
    token = secrets.token_urlsafe(8)
    if body.forward_url:
        set_target_sync(token, body.forward_url)
    return CaptureOut(id=-1, token=token, received_at="")


@app.post("/api/forward")
async def api_set_forward(body: ForwardConfig):
    if body.url:
        set_target_sync(body.token, body.url)
    else:
        get_forwarder().clear_target(body.token)
    return {"token": body.token, "forward_url": body.url}


@app.get("/health")
async def health():
    return {"status": "ok"}


def curl_command(record: CapturedRequest) -> str:
    """Render an inspectable ``curl`` command reproducing the stored request."""
    headers = json.loads(record.headers_json) if record.headers_json else {}
    host = (headers.get("host") or ["example.com"])[0]
    method = record.method
    url = f"http://{host}{record.path}"
    head_args = ""
    for name, values in headers.items():
        for value in values:
            head_args += f" -H '{name}: {value}'"
    data = ""
    if record.body:
        data = f" --data-binary '{record.body.decode('utf-8', errors='replace')}'"
    return f"curl -X {method} '{url}'{head_args}{data}"