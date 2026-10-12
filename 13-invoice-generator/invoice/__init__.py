"""Invoice generator: Stripe webhook -> branded PDF -> email.

A Flask app that verifies a Stripe ``payment_intent.succeeded`` signature,
creates an idempotent invoice record, renders a ReportLab PDF (with a
dependency-free fallback), and emails it to the customer.  All money is
integer cents.
"""

from __future__ import annotations

__version__ = "1.0.0"

__all__ = ["__version__"]