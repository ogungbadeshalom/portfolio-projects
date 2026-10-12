"""Invoice listing & PDF download routes.

* ``GET /invoices``                -- list invoices (filters: status, currency)
* ``GET /invoices/<id>``           -- one invoice as JSON
* ``GET /invoices/<id>/download``  -- download the generated PDF
* ``GET /                              -- Web UI landing (index page)
* ``GET /ui/invoices``             -- Web UI listing
"""

from __future__ import annotations

import logging
from pathlib import Path

from flask import (
    Blueprint,
    abort,
    current_app,
    jsonify,
    render_template,
    request,
    send_file,
    url_for,
)

from .. import models

logger = logging.getLogger(__name__)

invoices_bp = Blueprint("invoices", __name__)


def _session():
    """Read the app's SQLAlchemy session from the registered extension."""
    return current_app.extensions["sqlalchemy"]["session"]


def _fmt(cents: int, currency: str) -> str:
    from ..currencies import format_cents

    return format_cents(int(cents), currency)


def _query_arg(name: str, default=None):
    return request.args.get(name, default) if request.args is not None else default


def _query_arg_int(name: str, default: int) -> int:
    raw = request.args.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------------------- #
# JSON API
# --------------------------------------------------------------------------- #


@invoices_bp.get("/invoices")
def list_invoices():
    """Return a JSON list of invoices, optionally filtered by status/currency."""
    status = request.args.get("status")
    currency = request.args.get("currency")
    limit = _query_arg_int("limit", 100)
    offset = _query_arg_int("offset", 0)

    rows = models.list_invoices(_session(), status=status, currency=currency, limit=limit, offset=offset)
    result = []
    for inv in rows:
        d = inv.to_dict()
        d["download_url"] = url_for(
            "invoices.download_invoice", invoice_id=inv.id, _external=False
        )
        result.append(d)
    return jsonify({"invoices": result, "count": len(result)})


@invoices_bp.get("/invoices/<int:invoice_id>")
def get_invoice(invoice_id: int):
    """Return a single invoice as JSON (400 if not found)."""
    inv = _session().get(models.Invoice, invoice_id)
    if inv is None:
        abort(404, description="invoice not found")
    data = inv.to_dict()
    data["pdf_path"] = str(inv.pdf_path)
    data["download_url"] = url_for(
        "invoices.download_invoice", invoice_id=inv.id, _external=False
    )
    return jsonify(data)


@invoices_bp.get("/invoices/<int:invoice_id>/download")
def download_invoice(invoice_id: int):
    """Download the PDF for an invoice (404 if missing/not generated)."""
    inv = _session().get(models.Invoice, invoice_id)
    if inv is None:
        abort(404, description="invoice not found")
    pdf = Path(inv.pdf_path or "")
    if not pdf.is_file():
        abort(404, description="PDF not yet generated for this invoice")
    return send_file(
        str(pdf),
        as_attachment=True,
        download_name=f"{inv.invoice_number}.pdf",
        mimetype="application/pdf",
    )


# --------------------------------------------------------------------------- #
# Web UI (HTML) routes
# --------------------------------------------------------------------------- #


@invoices_bp.get("/")
def ui_index():
    """Render the web UI landing page showing recent invoices."""
    rows = models.list_invoices(_session(), limit=50)
    return render_template("invoice.html", page_title="Invoices", invoices=rows, money=_fmt)


@invoices_bp.get("/ui/invoices")
def ui_invoices():
    """Render an HTML page listing invoices."""
    rows = models.list_invoices(_session(), limit=200)
    return render_template("invoice.html", page_title="All Invoices", invoices=rows, money=_fmt)


@invoices_bp.get("/ui/invoices/<int:invoice_id>")
def ui_invoice_detail(invoice_id: int):
    """Render a single invoice's details as HTML."""
    inv = _session().get(models.Invoice, invoice_id)
    if inv is None:
        abort(404, description="invoice not found")
    return render_template(
        "invoice.html",
        page_title=f"Invoice {inv.invoice_number}",
        invoices=[inv],
        money=_fmt,
    )