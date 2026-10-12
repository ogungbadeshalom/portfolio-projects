"""Shared test fixtures: a fresh in-memory app per test.

Importing this module as a conftest gives tests an isolated, offline Flask app.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# Force offline-friendly env and an isolated PDF output location BEFORE the
# invoice.config module is imported (it reads these at import time).
_BUILD_DIR = Path(__file__).parent / "_build"
os.environ.setdefault("EMAIL_DRY_RUN", "1")
os.environ.setdefault("INVOICE_OUTPUT_DIR", str(_BUILD_DIR / "invoices"))
os.environ.setdefault("INVOICE_DATA_DIR", str(_BUILD_DIR / "data"))


@pytest.fixture()
def app():
    """Build an in-memory, email-dry-run Flask app."""
    from invoice.app import create_app

    a = create_app(
        {
            "TESTING": True,
            "INVOICE_DATABASE_URL": "sqlite:///:memory:",
            "INVOICE_EMAIL_MODE": "sync",  # deterministic, no background threads
        }
    )
    Path(a.config["INVOICE_OUTPUT_DIR"]).mkdir(parents=True, exist_ok=True)
    yield a
    # Close the session/engine so in-memory DBs are freed between tests.
    ext = a.extensions.get("sqlalchemy")
    if ext:
        ext["session"].close()
        ext["engine"].dispose()


@pytest.fixture()
def client(app):
    """A Flask test client bound to the isolated app."""
    return app.test_client()


@pytest.fixture()
def simulate_payload():
    """Default demo-webhook body used by the simulate route."""
    return {
        "amount_cents": 25000,
        "currency": "usd",
        "customer_email": "buyer@example.com",
        "stripe_payment_id": "pi_test_fixed_1",
        "line_items": [
            {"description": "Productivity Suite license", "qty": 1, "unit_price_cents": 15000},
            {"description": "Priority support (annual)", "qty": 2, "unit_price_cents": 5000},
        ],
    }