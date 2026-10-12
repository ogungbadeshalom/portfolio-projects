"""GitHub webhook receipt: HMAC verification + the /webhook/github route.

Responsibilities
----------------
* Verify ``X-Hub-Signature-256`` with the shared secret using a timing-safe
  comparison (``hmac.compare_digest``). Invalid signatures are rejected with
  401 — spec requirement.
* De-duplicate by ``X-GitHub-Delivery`` (idempotency): a replayed delivery is
  answered 200 OK but never re-stored or re-sent.
* Route supported event types (push / pull_request / release / star) through a
  formatter into Block Kit and dispatch to Slack. Unsupported types are
  answered 200 OK silently, with a small JSON note.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import threading
import uuid
from typing import Any, Callable, Dict, List, Optional

from flask import Blueprint, Response, current_app, jsonify, request

from githook import formatters
from githook.events import DuplicateDeliveryError, EventStore
from githook.retry import delivery_retrier

logger = logging.getLogger(__name__)

webhook_bp = Blueprint("webhook", __name__)

# Header names sent by GitHub (exact casing not guaranteed; Flask lower-cases).
_HEADER_SIGNATURE = "X-Hub-Signature-256"
_HEADER_DELIVERY = "X-GitHub-Delivery"
_HEADER_EVENT = "X-GitHub-Event"

#: Prefix GitHub prepends to the hex-encoded MAC.
_SIGNATURE_PREFIX = "sha256="


def compute_signature(secret: str, payload: bytes) -> str:
    """Return ``sha256=<hex>`` for ``payload`` using ``secret`` (HMAC-SHA256)."""
    digest = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return f"{_SIGNATURE_PREFIX}{digest}"


def verify_signature(secret: str, payload: bytes, signature: Optional[str]) -> bool:
    """Timing-safe check that ``signature`` matches ``payload`` under ``secret``.

    Accepts both the canonical ``sha256=<hex>`` form and a bare hex digest.
    Returns ``False`` for any malformed/missing signature.
    """
    if not signature:
        return False
    text = str(signature).strip()
    if text.lower().startswith(_SIGNATURE_PREFIX):
        provided = text[len(_SIGNATURE_PREFIX):]
    else:
        provided = text
    expected = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, provided)


@webhook_bp.route("/webhook/github", methods=["POST"])
def handle_webhook() -> Response:
    """Receive + verify + store + format + (background) forward a webhook."""
    secret = current_app.config["GITHUB_WEBHOOK_SECRET"]
    store: EventStore = current_app.config["EVENT_STORE"]
    request_id = str(uuid.uuid4())[:12]

    payload = request.get_data()

    signature = request.headers.get(_HEADER_SIGNATURE)
    if not verify_signature(secret, payload, signature):
        logger.warning("WEBHOOK %s rejected: bad HMAC signature.", request_id)
        return _reject("Invalid signature", status=401)

    delivery_id = request.headers.get(_HEADER_DELIVERY)
    event_type = request.headers.get(_HEADER_EVENT, "")

    try:
        data: Dict[str, Any] = json.loads(payload) if payload else {}
    except json.JSONDecodeError:
        data = {}
    if not isinstance(data, dict):
        data = {}

    # Idempotency: a delivery we have already seen is answered 200 but handled
    # exactly once end-to-end.
    if delivery_id:
        try:
            store.record(delivery_id, event_type, data)
        except DuplicateDeliveryError:
            logger.info("WEBHOOK %s duplicate delivery %r -> 200 (no re-send).", request_id, delivery_id)
            return _ok({"status": "duplicate", "request_id": request_id})
    else:
        # No delivery header: allow receipt but we cannot de-duplicate.
        delivery_id = f"unidentified-{request_id}"

    blocks = formatters.format_event(event_type, data)
    if blocks is None:
        # Supported-but-empty formatters return None too; treat as handled.
        logger.info("WEBHOOK %s event='%s' ignored (no formatter).", request_id, event_type)
        return _ok({"status": "ignored", "event": event_type, "request_id": request_id})

    webhook_url = current_app.config.get("SLACK_WEBHOOK_URL")
    if not webhook_url:
        logger.warning("WEBHOOK %s has no SLACK_WEBHOOK_URL; event stored, not sent.", request_id)
        return _ok({"status": "stored", "event": event_type, "request_id": request_id})

    _dispatch_delivery(store, delivery_id, blocks, webhook_url)

    return _ok({"status": "queued", "event": event_type, "request_id": request_id})


def _dispatch_delivery(
    store: EventStore, delivery_id: str, blocks: List[Dict[str, Any]], webhook_url: str
) -> None:
    """Send to Slack, honoring the app's sync/async delivery mode.

    In ``SYNC_DELIVERY`` mode (tests, simple local runs) the send completes
    before the webhook returns, so assertions are deterministic. Otherwise the
    send runs on a short-lived background thread so the webhook response is
    never blocked on Slack's latency.
    """
    from githook import slack

    transport: Any = current_app.config.get("SLACK_TRANSPORT")
    sync = bool(current_app.config.get("SYNC_SLACK_DELIVERY", False))

    kwargs: Dict[str, Any] = dict(
        store=store,
        send_to_slack=slack.send_to_slack,
        webhook_url=webhook_url,
        blocks=blocks,
        delivery_id=delivery_id,
        max_retries=current_app.config["MAX_SLACK_RETRIES"],
        backoff_base=current_app.config["SLACK_BACKOFF_BASE"],
        retry_queue=current_app.config.get("SLACK_RETRY_QUEUE"),
        transport=transport,
    )
    if sync:
        delivery_retrier(**kwargs)
        return

    thread = threading.Thread(
        target=delivery_retrier, kwargs=kwargs, name=f"slack-{delivery_id[:8]}", daemon=True
    )
    thread.start()


def _reject(message: str, *, status: int) -> Response:
    return jsonify({"error": message, "status": status}), status


def _ok(body: Dict[str, Any]) -> Response:
    return jsonify(body), 200