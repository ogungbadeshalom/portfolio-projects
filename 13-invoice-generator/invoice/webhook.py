"""Stripe webhook endpoint and the invoice-processing pipeline.

Pipeline (per spec build order, step 6):

    POST /stripe/webhook
        -> verify signature (SDK or stdlib HMAC)
        -> parse event (payment_intent.succeeded)
        -> idempotency check on stripe_payment_id (process once)
        -> compute line items (from payload metadata / Stripe amount)
        -> create Invoice record with next sequential per-year number
        -> generate branded PDF (atomic)
        -> email the PDF to the customer (async, non-blocking)
        -> persist record + pdf_path; mark email_status

All errors are logged with their ``stripe_payment_id`` context.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from flask import Blueprint, current_app, jsonify, request
from sqlalchemy.exc import IntegrityError

from . import config, models
from .email_sender import EmailSendError, send_invoice_email_async, send_invoice_email_sync
from .models import Invoice, LineItem
from .pdf_generator import generate_invoice_pdf
from .stripe_verify import (
    SignatureVerificationError,
    verify_stripe_signature,
)

logger = logging.getLogger(__name__)

webhook_bp = Blueprint("webhook", __name__)


# ---------------------------------------------------------------------------
# Request parsing helpers
# ---------------------------------------------------------------------------
def _json_body_or_raise(raw: Optional[bytes] = None) -> Dict[str, Any]:
    """Parse the request JSON body (or ``raw`` bytes when provided).

    ``raw`` is used by :func:`stripe_webhook` so the body is consumed exactly
    once (the raw bytes are also needed for HMAC verification) and we never
    trip over a second read of an already-consumed stream.
    """
    try:
        if raw is not None:
            import json as _json

            data = _json.loads(raw.decode("utf-8"))
        else:
            data = request.get_json(force=True, silent=False)
    except Exception as exc:
        raise ValueError("invalid JSON body: %s" % exc)
    if not isinstance(data, dict):
        raise ValueError("webhook JSON body must be an object")
    return data


# ---------------------------------------------------------------------------
# Event -> money/line-item mapping
# ---------------------------------------------------------------------------
def _extract_payment_payload(event: Dict[str, Any]) -> Dict[str, Any]:
    """Return the ``data.object`` (the payment_intent) or raise ValueError."""
    obj = (event.get("data") or {}).get("object")
    if not isinstance(obj, dict):
        raise ValueError("event has no data.object")
    if obj.get("id") != event.get("id"):
        # not a hard requirement; keep as informational
        pass
    return obj


def _line_items_from_payload(pi: Dict[str, Any]) -> List[LineItem]:
    """Build LineItem list from payment_intent metadata (or sensible defaults).

    Preferred: ``metadata[line_items]`` as a JSON array of
    ``{"description", "qty"/"quantity", "unit_price_cents", "tax_rate_percent"}``.

    Fallback: a single line for the captured amount with the default tax rate.
    """
    meta = pi.get("metadata") or {}
    raw = meta.get(config.META_LINE_ITEMS)
    if raw:
        try:
            items_data = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError("metadata.line_items is not valid JSON: %s" % exc)
        items: List[LineItem] = []
        for entry in items_data:
            items.append(
                LineItem(
                    description=entry.get("description", "Service"),
                    quantity=int(entry.get("qty", entry.get("quantity", 1))),
                    unit_price_cents=int(entry.get("unit_price_cents")),
                    tax_rate_percent=float(entry.get("tax_rate_percent", config.DEFAULT_TAX_RATE_PERCENT)),
                )
            )
        if not items:
            raise ValueError("metadata.line_items cannot be an empty array")
        return items

    # Fallback: single line from the charge amount.
    amount = int(pi.get("amount", 0))
    return [LineItem(
        description="Service / goods",
        quantity=1,
        unit_price_cents=amount,
        tax_rate_percent=config.DEFAULT_TAX_RATE_PERCENT,
    )]


def _customer_email(pi: Dict[str, Any]) -> str:
    meta = pi.get("metadata") or {}
    email = meta.get(config.META_EMAIL)
    if email:
        return email
    # Stripe receipt_email often holds the customer address.
    return pi.get("receipt_email") or "customer@example.com"


def _compute_totals(items: List[LineItem]) -> Tuple[int, int, int]:
    subtotal = sum(it.total_cents for it in items)          # pre-tax
    tax = sum(it.tax_cents for it in items)                 # per-line summed
    total = subtotal + tax                                  # grand total incl tax
    return subtotal, tax, total


# ---------------------------------------------------------------------------
# Core processing
# ---------------------------------------------------------------------------
def _process_payment_intent(session, pi: Dict[str, Any]) -> Invoice:
    """Create invoice + PDF + (optionally) email for one payment_intent.

    Must be called inside a committed transaction; raises on failure.
    """
    stripe_payment_id = pi.get("id")
    if not stripe_payment_id:
        raise ValueError("payment_intent object has no id")

    # 1) Idempotency — same payment_intent.id processed only once.
    existing = models.invoice_by_payment_id(session, stripe_payment_id)
    if existing is not None and existing.status == "completed":
        logger.info("idempotent: skipping already-processed payment %s", stripe_payment_id)
        return existing

    items = _line_items_from_payload(pi)
    subtotal, tax, total = _compute_totals(items)
    currency = (pi.get("currency") or "usd").upper()
    email = _customer_email(pi)
    customer_name = (pi.get("metadata") or {}).get("customer_name", "")

    # 2) Sequential per-year invoice number (serialized).
    models.lock_invoice_numbering(session)
    try:
        number = models.next_invoice_number(session)
        invoice = Invoice(
            invoice_number=number,
            stripe_payment_id=stripe_payment_id,
            customer_email=email,
            customer_name=customer_name,
            currency=currency,
            amount_cents=total,
            subtotal_cents=subtotal,
            tax_cents=tax,
            status="processing",
            paid_at=datetime.utcnow(),
        )
        invoice.set_line_items(items)
        session.add(invoice)
        session.flush()   # assigns invoice.id; surfaces UNIQUE collisions early
    finally:
        models.release_invoice_numbering(session)

    # 3) Generate the PDF (atomic tmp+rename).  Stores path on the record.
    try:
        result = generate_invoice_pdf(invoice)
        invoice.pdf_path = str(result.path)
    except Exception as exc:
        session.rollback()
        logger.exception(
            "pdf generation failed stripe_payment_id=%s invoice=%s",
            stripe_payment_id,
            invoice.invoice_number,
        )
        raise ValueError("pdf generation failed: %s" % exc) from exc

    # 4) Email the PDF to the customer (async sends; sync fallback used in tests).
    send_mode = current_app.config.get("INVOICE_EMAIL_MODE", "async")
    try:
        if send_mode == "sync":
            status = send_invoice_email_sync(invoice)
            invoice.email_status = status
            if status == "sent":
                invoice.sent_at = datetime.utcnow()
        else:
            # Kick off the background thread; report back was captured already.
            send_invoice_email_async(invoice)
            invoice.email_status = "queued"
    except EmailSendError as exc:
        invoice.email_status = "failed"
        logger.error(
            "email send failed stripe_payment_id=%s invoice=%s status=failed: %s",
            stripe_payment_id,
            invoice.invoice_number,
            exc,
        )

    invoice.status = "completed"
    session.commit()
    logger.info(
        "invoice created stripe_payment_id=%s invoice=%s total=%d%s email_status=%s",
        stripe_payment_id,
        invoice.invoice_number,
        invoice.amount_cents,
        invoice.currency,
        invoice.email_status,
    )
    return invoice


# ---------------------------------------------------------------------------
# Flask route
# ---------------------------------------------------------------------------
@webhook_bp.route("/stripe/webhook", methods=["POST"])
def stripe_webhook():
    raw = request.get_data(cache=True)   # read once; used for HMAC + JSON parse
    sig = request.headers.get("Stripe-Signature", "")
    secret = config.STRIPE_WEBHOOK_SECRET

    try:
        verify_stripe_signature(raw, sig, secret)
    except SignatureVerificationError as exc:
        logger.warning("signature verification failed: %s", exc)
        return jsonify({"error": "invalid signature"}), 400

    try:
        event = _json_body_or_raise(raw)
    except ValueError as exc:
        logger.warning("could not parse webhook body: %s", exc)
        return jsonify({"error": "invalid payload"}), 400

    event_type = event.get("type", "")
    if event_type != "payment_intent.succeeded":
        logger.info(
            "ignoring event type=%s stripe_payment_id=%s",
            event_type,
            (event.get("data") or {}).get("object", {}).get("id"),
        )
        # Acknowledge non-target events so Stripe stops retrying harmless ones.
        return jsonify({"received": event_type}), 200

    try:
        pi = _extract_payment_payload(event)
    except ValueError as exc:
        logger.error("malformed payment_intent payload: %s", exc)
        return jsonify({"error": "malformed event"}), 422

    swipe = current_app.extensions["sqlalchemy"]
    session = swipe["session"]
    try:
        invoice = _process_payment_intent(session, pi)
    except ValueError as exc:
        logger.error(
            "processing failed stripe_payment_id=%s error=%s",
            pi.get("id"), exc,
        )
        return jsonify({"error": str(exc)}), 422
    except IntegrityError as exc:
        session.rollback()

        # A classic duplicate raced us — re-check idempotency.
        existing = models.invoice_by_payment_id(session, pi.get("id"))
        if existing is not None:
            logger.warning(
                "duplicate webhook after integrity error; returning existing "
                "stripe_payment_id=%s invoice=%s",
                pi.get("id"), existing.invoice_number,
            )
            return jsonify({"invoice": existing.invoice_number}), 200
        raise

    return jsonify({"received": True, "invoice": invoice.invoice_number}), 200


# ---------------------------------------------------------------------------
# Local simulation route (demo without real Stripe)
# ---------------------------------------------------------------------------
@webhook_bp.route("/dev/simulate-webhook", methods=["POST"])
def simulate_webhook():
    """Build a signed payment_intent.succeeded event and POST it to ourselves.

    Lets the full flow be demonstrated entirely offline: authors a valid
    Stripe-Signature over the same payload, then calls the webhook handler
    directly (in-process) using the configured secret.
    """
    from inspect import getmembers
    from .stripe_verify import sign_payload

    body = request.get_json(force=True, silent=True) or {}
    amount = int(body.get("amount_cents", 25000))
    currency = (body.get("currency") or "usd").lower()
    email = body.get("customer_email") or body.get("email") or "customer@example.com"
    line_items = body.get("line_items") or [
        {"description": "Productivity Suite license", "qty": 1, "unit_price_cents": 15000},
        {"description": "Priority support (annual)", "qty": 2, "unit_price_cents": 5000},
    ]
    payment_id = body.get("stripe_payment_id")
    if not payment_id:
        digest = hashlib.sha1(json.dumps(body, sort_keys=True).encode("utf-8")).hexdigest()[:32]
        payment_id = "pi_demo_%032d" % int(digest[:20], 16)

    event = {
        "id": "evt_demo_%s" % payment_id,
        "object": "event",
        "type": "payment_intent.succeeded",
        "data": {
            "object": {
                "id": payment_id,
                "object": "payment_intent",
                "amount": amount,
                "currency": currency,
                "receipt_email": email,
                "status": "succeeded",
                "metadata": {
                    config.META_EMAIL: email,
                    config.META_LINE_ITEMS: json.dumps(
                        [
                            {"description": li.get("description"), "qty": li.get("qty", li.get("quantity", 1)),
                             "unit_price_cents": li.get("unit_price_cents"),
                             "tax_rate_percent": li.get("tax_rate_percent", config.DEFAULT_TAX_RATE_PERCENT)}
                            for li in line_items
                        ]
                    ),
                },
            }
        },
    }

    raw = json.dumps(event).encode("utf-8")
    sig = sign_payload(raw, config.STRIPE_WEBHOOK_SECRET)
    # Push a single request context carrying the signed body and the
    # signature header, then invoke the webhook handler in-process.
    ctx = current_app.test_request_context(
        "/stripe/webhook",
        method="POST",
        data=raw,
        headers={"Stripe-Signature": sig, "Content-Type": "application/json"},
    )
    with ctx:
        return stripe_webhook()