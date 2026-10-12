"""End-to-end webhook tests via the offline ``/dev/simulate-webhook`` route.

No real Stripe network calls: the route signs a fake event with the configured
secret and invokes the handler in-process.  We override the Stripe signing
secret to a test value so signature verification is exercised for real.
"""

from __future__ import annotations

import json

import pytest

from invoice import models, config


@pytest.fixture()
def app_with_secret(monkeypatch):
    """App using a fixed, injected Stripe webhook secret."""
    from invoice.app import create_app

    secret = "whsec_test_secret_xyz"
    a = create_app(
        {
            "TESTING": True,
            "INVOICE_DATABASE_URL": "sqlite:///:memory:",
            "INVOICE_EMAIL_MODE": "sync",
            "STRIPE_WEBHOOK_SECRET": secret,
        }
    )
    monkeypatch.setattr(config, "STRIPE_WEBHOOK_SECRET", secret)
    yield a
    ext = a.extensions.get("sqlalchemy")
    if ext:
        ext["session"].close()
        ext["engine"].dispose()


def test_pipeline_creates_invoice_and_pdf(client, simulate_payload):
    resp = client.post("/dev/simulate-webhook", json=simulate_payload)
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["received"] is True
    assert "INV-" in payload["invoice"]

    rows = client.get("/invoices").get_json()["invoices"]
    assert len(rows) == 1
    inv = rows[0]
    assert inv["customer_email"] == "buyer@example.com"
    assert inv["currency"] == "USD"
    assert inv["status"] == "completed"
    # grand total for the two line items (incl. default 20% tax)
    subtotal = 15000 + 2 * 5000
    tax = round(15000 * 0.2) + round(10000 * 0.2)
    assert inv["subtotal_cents"] == subtotal
    assert inv["amount_cents"] == subtotal + tax
    assert inv["pdf_path"]

    # The PDF must be a real file on disk with real PDF bytes.
    from pathlib import Path

    pdf = Path(inv["pdf_path"])
    assert pdf.exists()
    head = pdf.read_bytes()[:5]
    assert head.startswith(b"%PDF")


def test_invoice_downloadable(client, simulate_payload):
    client.post("/dev/simulate-webhook", json=simulate_payload)
    inv = client.get("/invoices").get_json()["invoices"][0]

    dl = client.get(f"/invoices/{inv['id']}/download")
    assert dl.status_code == 200
    assert dl.mimetype == "application/pdf"
    assert dl.data[:5] == b"%PDF-"
    assert len(dl.data) > 1000


def test_idempotency_same_payment_processed_once(client, simulate_payload):
    client.post("/dev/simulate-webhook", json=simulate_payload)
    # Replay the identical payment_intent id -> must not create a second row.
    client.post("/dev/simulate-webhook", json=simulate_payload)
    rows = client.get("/invoices").get_json()["invoices"]
    assert len(rows) == 1


def test_sequential_invoice_numbers(client, simulate_payload):
    from datetime import datetime

    year = datetime.utcnow().year
    client.post("/dev/simulate-webhook", json=simulate_payload)
    client.post("/dev/simulate-webhook", json={**simulate_payload, "stripe_payment_id": "pi_test_fixed_2"})
    rows = client.get("/invoices").get_json()["invoices"]
    numbers = sorted(r["invoice_number"] for r in rows)
    assert numbers == [f"INV-{year}-001", f"INV-{year}-002"]


def test_stripe_signature_verified(app_with_secret, simulate_payload):
    """The demo route signs with the injected secret; a wrong secret must fail."""
    from invoice.app import config as app_cfg

    client = app_with_secret.test_client()
    resp = client.post("/dev/simulate-webhook", json=simulate_payload)
    assert resp.status_code == 200  # valid signature accepted

    # Reconstruct a hand-crafted event signed with a DIFFERENT secret and POST
    # it directly to /stripe/webhook: signature verification must reject it.
    from invoice.stripe_verify import sign_payload

    evt = {
        "id": "evt_x",
        "object": "event",
        "type": "payment_intent.succeeded",
        "data": {"object": {"id": "pi_wrong_secret", "amount": 100, "currency": "usd"}},
    }
    raw = json.dumps(evt).encode("utf-8")
    bad_sig = sign_payload(raw, "whsec_attacker_key")
    bad = client.post(
        "/stripe/webhook",
        data=raw,
        headers={"Stripe-Signature": bad_sig, "Content-Type": "application/json"},
    )
    assert bad.status_code == 400
    assert "invalid signature" in bad.get_json()["error"]


def test_valid_signed_webhook_accepted(app_with_secret):
    """A properly signed payment_intent event is accepted by /stripe/webhook."""
    from invoice.stripe_verify import sign_payload

    client = app_with_secret.test_client()
    evt = {
        "id": "evt_good",
        "object": "event",
        "type": "payment_intent.succeeded",
        "data": {
            "object": {
                "id": "pi_signed_ok",
                "amount": 9900,
                "currency": "usd",
                "receipt_email": "ok@example.com",
                "metadata": {},
            }
        },
    }
    raw = json.dumps(evt).encode("utf-8")
    sig = sign_payload(raw, config.STRIPE_WEBHOOK_SECRET)
    resp = client.post(
        "/stripe/webhook",
        data=raw,
        headers={"Stripe-Signature": sig, "Content-Type": "application/json"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["received"] is True