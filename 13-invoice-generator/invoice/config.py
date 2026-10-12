"""Application configuration.

Everything is driven by environment variables so the app runs equally well
locally (dev), against Mailtrap, or in production.  All secrets default to
dev-friendly placeholder values and must never be committed.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Dict, Optional

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent   # project root
DATA_DIR = Path(os.environ.get("INVOICE_DATA_DIR", str(BASE_DIR / "data")))
INVOICES_DIR = Path(
    os.environ.get("INVOICE_OUTPUT_DIR", str(BASE_DIR / "data" / "invoices"))
)

DATABASE_URI = os.environ.get(
    "INVOICE_DATABASE_URL", "sqlite:///" + str(DATA_DIR / "invoice.db").replace("\\", "/")
)

# ---------------------------------------------------------------------------
# Stripe
# ---------------------------------------------------------------------------
STRIPE_WEBHOOK_SECRET = os.environ.get(
    "STRIPE_WEBHOOK_SECRET", "whsec_test_secret_replace_me"
)
# Tolerated skew (seconds) between the webhook timestamp and "now".
STRIPE_WEBHOOK_TOLERANCE_S = int(os.environ.get("STRIPE_WEBHOOK_TOLERANCE_S", "300"))

# Amount threshold above which a payment_intent is treated as a *partial*
# payment toward an existing invoice (per the spec's partial-payment stretch).
# 0 disables partial-payment grouping.
PARTIAL_PAYMENT_GROUP_MODE = os.environ.get("PARTIAL_PAYMENT_GROUP_MODE", "0")  # "0"|"1"

# ---------------------------------------------------------------------------
# Company branding (used on the invoice letterhead)
# ---------------------------------------------------------------------------
COMPANY = {
    "name": os.environ.get("INVOICE_COMPANY_NAME", "Northwind Studio LLC"),
    "address": os.environ.get(
        "INVOICE_COMPANY_ADDRESS", "400 Harrison St, Boston, MA 02118, USA"
    ),
    "tax_id": os.environ.get("INVOICE_COMPANY_TAX_ID", "US-00-1234567"),
    "email": os.environ.get("INVOICE_COMPANY_EMAIL", "billing@northwind.example"),
    "phone": os.environ.get("INVOICE_COMPANY_PHONE", "+1 (555) 010-0100"),
}

# Default VAT / tax percent applied to each line item when the payment payload
# or Stripe metadata does not specify its own rate.
DEFAULT_TAX_RATE_PERCENT = float(os.environ.get("INVOICE_DEFAULT_TAX_PERCENT", "20.0"))

# ---------------------------------------------------------------------------
# Email (SMTP).  Mailtrap-friendly defaults.
# ---------------------------------------------------------------------------
SMTP = {
    "host": os.environ.get("SMTP_HOST", "smtp.mailtrap.io"),
    "port": int(os.environ.get("SMTP_PORT", "2525")),
    "username": os.environ.get("SMTP_USERNAME", ""),
    "password": os.environ.get("SMTP_PASSWORD", ""),
    "use_tls": os.environ.get("SMTP_USE_TLS", "1") == "1",
    "from_email": os.environ.get(
        "SMTP_FROM_EMAIL", os.environ.get("INVOICE_COMPANY_EMAIL", "billing@example.com")
    ),
    "from_name": os.environ.get("SMTP_FROM_NAME", COMPANY["name"]),
}

# When True, the email sender logs the composed message instead of contacting the
# SMTP server.  This keeps demo runs offline-friendly.
EMAIL_DRY_RUN = os.environ.get("EMAIL_DRY_RUN", "0") == "1"

# ---------------------------------------------------------------------------
# Sample / demo payment intent metadata keys (used by tests + simulate route).
# ---------------------------------------------------------------------------
META_EMAIL = "customer_email"
META_LINE_ITEMS = "line_items"          # JSON list of {description, qty, unit_price_cents, tax_rate_percent}
META_REF = "reference"                  # optional buyer purchase-order / reference no.

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_LEVEL = os.environ.get("INVOICE_LOG_LEVEL", "INFO").upper()


def configured_logging() -> None:
    """Bootstrap stdlib logging once (idempotent)."""
    numeric = getattr(logging, LOG_LEVEL, logging.INFO)
    root = logging.getLogger()
    if not any(
        isinstance(h, logging.StreamHandler) for h in root.handlers
    ):
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        root.addHandler(handler)
        root.setLevel(numeric)


# Optional mapping of ISO currency -> effective tax rate override (percent).
CURRENCY_TAX_OVERRIDES: Dict[str, float] = {}


def ensure_dirs() -> None:
    """Create every directory the app writes to at startup."""
    for path in (DATA_DIR, INVOICES_DIR):
        path.mkdir(parents=True, exist_ok=True)


def webhook_secret_from_env_or_default() -> str:
    return STRIPE_WEBHOOK_SECRET


def optional_json_env(name: str) -> Optional[str]:
    """Return the raw env var (str) — caller validates/parses the JSON."""
    return os.environ.get(name)