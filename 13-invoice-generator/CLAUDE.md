# Invoice Generator (Stripe Webhook → PDF)

## Project Title
Invoice Generator (Stripe Webhook → PDF Email)

## Goal
Receive Stripe payment webhooks, generate PDF invoices, and email them to customers automatically. Full payment workflow.

## Why this project
Payment flows are everywhere. Teaches: webhook processing, PDF generation, email sending, idempotency, currency handling, professional invoice formatting.

## What You Build
A Flask app that:

1. Receives Stripe `payment_intent.succeeded` webhook
2. Verifies webhook signature
3. Generates branded PDF invoice (company info, line items, totals, tax)
4. Emails PDF to customer
5. Stores invoice record in DB
6. Exposes `GET /invoices/{id}` (download PDF) and `GET /invoices` (list)

## Tech
- **Python 3.11+**
- **Flask** (web framework)
- **Stripe Python SDK** (webhook handling, customer fetching)
- **ReportLab** (PDF generation) or **WeasyPrint** (HTML→PDF)
- **Jinja2** (invoice HTML template)
- **SendGrid** or **SMTP** (email delivery)
- **SQLAlchemy** + **SQLite** (invoice storage)

## Architecture

```
invoice/
├── invoice/
│   ├── __init__.py
│   ├── app.py              # Flask app factory
│   ├── webhook.py          # /stripe/webhook endpoint
│   ├── stripe_verify.py    # Stripe signature verification
│   ├── pdf_generator.py    # PDF generation (ReportLab or WeasyPrint)
│   ├── email_sender.py     # SMTP / SendGrid
│   ├── models.py           # Invoice, LineItem, Customer
│   ├── templates/
│   │   └── invoice.html    # Jinja2 template for PDF
│   └── config.py
├── static/
│   └── logo.png             # your logo
├── tests/
├── pyproject.toml
└── CLAUDE.md
```

## Build Order

1. **`models.py`** — Invoice (id, stripe_payment_id UNIQUE, customer_email, amount_cents, currency, line_items_json, pdf_path, status, sent_at), LineItem (description, qty, unit_price_cents, total_cents)
2. **`stripe_verify.py`** — `verify_stripe_signature(payload, sig_header, secret)` using Stripe SDK
3. **`webhook.py`** — Flask route, verify signature, parse event, create Invoice record
4. **`pdf_generator.py`** — render Jinja2 template to HTML, convert to PDF with WeasyPrint
5. **`email_sender.py`** — attach PDF, send to customer email with invoice details in body
6. **`webhook.py`** — full flow: webhook → create invoice → generate PDF → email
7. **`routes/invoices.py`** — `GET /invoices/{id}` (download PDF), `GET /invoices` (list with filters)
8. **Templates** — professional invoice HTML (header, line items, totals, tax, payment info)
9. **Stripe test mode** — use Stripe CLI to forward test webhooks

## Requirements

- Stripe webhook signature verification (HMAC-SHA256, timestamp check)
- Idempotency: same `payment_intent.id` processed only once
- PDF generation: company letterhead, line items, subtotal, tax (per line item), total
- PDF stored locally AND emailed to customer
- Email with PDF attachment, plain text body with payment details
- Currency formatting: USD, EUR, GBP, NGN (symbol + correct decimal places)
- Tax calculation: per-line-item rate, summed to subtotal
- Invoice numbering: `INV-2026-001`, `INV-2026-002`, etc. (sequential, no gaps)
- Web UI to view past invoices
- Support partial payments (multiple `payment_intent.succeeded` events for one invoice)

## Code Standards

- All money in cents (integers, never floats)
- Currency formatting via `babel` library (proper symbols + decimal places)
- Webhook signature verification uses Stripe SDK (don't reinvent)
- PDF generation atomic: generate to .tmp, rename to final
- Email sending uses async (don't block webhook response)
- All errors logged with stripe_payment_id context
- Invoice numbers monotonic per year

## Verification

```bash
# Start server
flask run --port 5000

# Install Stripe CLI
stripe login
stripe listen --forward-to localhost:5000/stripe/webhook

# Create test payment
stripe trigger payment_intent.succeeded

# Verify
# - PDF generated in invoices/
# - Email sent to customer (check Mailtrap or test inbox)
# - GET /invoices shows the new invoice

# Run tests
pytest tests/ -v
```

## Stretch Goals

- Multi-currency support (automatic conversion to base currency)
- Recurring invoice generation (monthly subscriptions)
- Customer portal (customer logs in, sees their invoices)
- Tax exempt handling
- Partial refunds → credit notes
- Multi-page PDF (long invoice with many line items)
- Email tracking (open + click tracking via SendGrid)
- Custom branding per company (multi-tenant)

## What You'll Learn

- Stripe webhook processing (real payment integration)
- HMAC signature verification
- PDF generation from HTML/CSS
- Email sending with attachments
- Currency formatting (proper money handling)
- Idempotency in payment systems
- Invoice numbering and tax math

## Time Estimate
6-10 hours for MVP. 12-16 hours with multi-currency + tax + email tracking + tests.