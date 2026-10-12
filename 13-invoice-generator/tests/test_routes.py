"""GET /invoices and GET /invoices/<id>/download route tests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest


def _create_one(client, simulate_payload):
    resp = client.post("/dev/simulate-webhook", json=simulate_payload)
    assert resp.status_code == 200
    return client.get("/invoices").get_json()["invoices"][0]


def test_list_invoices_empty(client):
    resp = client.get("/invoices")
    assert resp.status_code == 200
    assert resp.get_json() == {"invoices": [], "count": 0}


def test_list_invoices_shows_row(client, simulate_payload):
    _create_one(client, simulate_payload)
    data = client.get("/invoices").get_json()
    assert data["count"] == 1
    inv = data["invoices"][0]
    assert "invoice_number" in inv
    assert "download_url" in inv
    assert "/download" in inv["download_url"]


def test_get_single_invoice(client, simulate_payload):
    inv = _create_one(client, simulate_payload)
    data = client.get(f"/invoices/{inv['id']}").get_json()
    assert data["invoice_number"] == inv["invoice_number"]
    assert data["currency"] == "USD"
    assert len(data["line_items"]) == 2


def test_get_missing_invoice_404(client):
    assert client.get("/invoices/9999").status_code == 404


def test_download_missing_pdf_404(client, simulate_payload):
    inv = _create_one(client, simulate_payload)
    # Remove the generated PDF then attempt download -> 404.
    pdf = Path(inv["pdf_path"])
    if pdf.exists():
        pdf.unlink()
    resp = client.get(f"/invoices/{inv['id']}/download")
    assert resp.status_code == 404


def test_download_pdf_content_disposition(client, simulate_payload):
    inv = _create_one(client, simulate_payload)
    resp = client.get(f"/invoices/{inv['id']}/download")
    assert "application/pdf" == resp.mimetype
    assert f"{inv['invoice_number']}.pdf" in resp.headers.get("Content-Disposition", "")


def test_currency_filter(client, simulate_payload):
    _create_one(client, simulate_payload)
    # One USD invoice; a GBP filter should return none.
    gbp = client.get("/invoices?currency=gbp").get_json()
    assert gbp["count"] == 0
    usd = client.get("/invoices?currency=usd").get_json()
    assert usd["count"] == 1


def test_ui_listing_page_renders(client, simulate_payload):
    _create_one(client, simulate_payload)
    resp = client.get("/ui/invoices")
    assert resp.status_code == 200
    assert "INV-" in resp.get_data(as_text=True)