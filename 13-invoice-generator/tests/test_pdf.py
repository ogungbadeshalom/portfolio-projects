"""Unit tests for PDF generation, currency math and email composition."""

from __future__ import annotations

from pathlib import Path

import pytest


# --------------------------------------------------------------------------- #
# PDF generation
# --------------------------------------------------------------------------- #


def test_generate_invoice_pdf_produces_real_bytes(app, simulate_payload):
    """Directly build a LineItem/Invoice and render a genuine PDF."""
    from datetime import datetime

    from invoice import config, models
    from invoice.models import Invoice, LineItem
    from invoice.pdf_generator import generate_invoice_pdf

    items = [LineItem("Design retainer", 3, 15000, 20.0)]
    invoice = Invoice(
        invoice_number="TEST-UNIT-001",
        stripe_payment_id="pi_unit_1",
        customer_email="unit@example.com",
        customer_name="Unit Tester",
        currency="EUR",
        amount_cents=54000,
        subtotal_cents=45000,
        tax_cents=9000,
        status="completed",
        created_at=datetime.utcnow(),
    )
    invoice.set_line_items(items)

    result = generate_invoice_pdf(invoice)
    path = Path(result.path)
    assert path.exists()
    assert path.read_bytes().startswith(b"%PDF")
    assert result.engine in ("reportlab", "minimal")
    assert result.bytes_written > 200


def test_pdf_generation_is_atomic(app, simulate_payload):
    """No leftover ``.tmp`` files remain after generation."""
    from datetime import datetime

    from invoice.models import Invoice, LineItem
    from invoice.pdf_generator import generate_invoice_pdf

    invoice = Invoice(
        invoice_number="TEST-ATOMIC-001",
        stripe_payment_id="pi_atomic_1",
        customer_email="a@example.com",
        currency="USD",
        amount_cents=1000,
        subtotal_cents=1000,
        tax_cents=0,
        status="completed",
        created_at=datetime.utcnow(),
    )
    invoice.set_line_items([LineItem("Item", 1, 1000, 0.0)])
    res = generate_invoice_pdf(invoice)
    assert not Path(str(res.path) + ".tmp").exists()


# --------------------------------------------------------------------------- #
# Currency formatting
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "cents,currency,expected",
    [
        (12345, "USD", "$123.45"),
        (12345, "EUR", "€123.45"),
        (12345, "GBP", "£123.45"),
        (500, "NGN", "₦5.00"),
        (12345, "JPY", "¥123"),  # 0 decimal places
        (0, "USD", "$0.00"),
    ],
)
def test_format_cents(cents, currency, expected):
    from invoice.currencies import format_cents

    assert format_cents(cents, currency) == expected


def test_money_is_always_int_cents():
    from invoice.currencies import format_cents

    with pytest.raises(TypeError):
        format_cents(12.5, "USD")  # float cents must be rejected


# --------------------------------------------------------------------------- #
# Email composition
# --------------------------------------------------------------------------- #


def test_compose_invoice_email_attaches_pdf(app, simulate_payload):
    from datetime import datetime

    from invoice.email_sender import compose_invoice_email
    from invoice.models import Invoice, LineItem
    from invoice.pdf_generator import generate_invoice_pdf

    invoice = Invoice(
        invoice_number="TEST-MAIL-001",
        stripe_payment_id="pi_mail_1",
        customer_email="mail@example.com",
        customer_name="Mail Recipient",
        currency="GBP",
        amount_cents=2500,
        subtotal_cents=2500,
        tax_cents=0,
        status="completed",
        created_at=datetime.utcnow(),
    )
    invoice.set_line_items([LineItem("Widget", 1, 2500, 0.0)])
    pdf = generate_invoice_pdf(invoice)
    invoice.pdf_path = str(pdf.path)

    msg = compose_invoice_email(invoice, pdf.path)
    assert msg["To"] == "mail@example.com"
    assert "invoice" in msg["Subject"].lower()
    # One PDF attachment present.
    attachments = [part for part in msg.iter_attachments() if part.get_content_type() == "application/pdf"]
    assert len(attachments) == 1
    assert attachments[0].get_payload(decode=True).startswith(b"%PDF")