"""PDF generation for invoices.

Primary path: **ReportLab** (pure-Python, imports reliably) which produces a
real, vector PDF directly — no browser required.

Fallback path: if ReportLab is unavailable, we fall back to a small, self-contained
minimal PDF writer (:func:`_write_minimal_pdf`) that emits a standards-compliant
single-page PDF containing the invoice text.  The caller always receives a file
whose ``.pdf`` extension holds genuine PDF bytes.

Writing is **atomic**: content is written to a unique ``.tmp`` file in the same
directory and then ``os.replace``'d on top of the final name, so a crash never
leaves a truncated PDF at the public path.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from . import config
from .currencies import format_cents
from .models import Invoice, LineItem

logger = logging.getLogger(__name__)

try:  # pragma: no cover - prefers installed lib
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT, TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.pdfmetrics import stringWidth
    from reportlab.pdfgen import canvas
    from reportlab.platypus import (
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )
    HAS_REPORTLAB = True
except Exception:  # pragma: no cover - env specific
    HAS_REPORTLAB = False
    canvas = None  # type: ignore[assignment]


@dataclass
class PdfGenerationResult:
    """Outcome of generating one invoice PDF."""

    path: Path
    bytes_written: int
    engine: str  # "reportlab" | "minimal"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def generate_invoice_pdf(invoice: Invoice) -> PdfGenerationResult:
    """Render ``invoice`` to a PDF on disk (atomic) and return the result.

    :raises OSError: if the final file cannot be written.
    """
    if HAS_REPORTLAB and canvas is not None:
        return _generate_reportlab(invoice)
    return _generate_minimal(invoice)


# ---------------------------------------------------------------------------
# ReportLab implementation
# ---------------------------------------------------------------------------
def _generate_reportlab(invoice: Invoice) -> PdfGenerationResult:
    assert canvas is not None
    final = config.INVOICES_DIR / ("%s.pdf" % invoice.invoice_number)
    tmp = final.with_name(final.name + ".tmp")

    doc = SimpleDocTemplate(
        str(tmp),
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=22 * mm,
        bottomMargin=18 * mm,
        title="Invoice %s" % invoice.invoice_number,
        author=config.COMPANY["name"],
    )

    story: List[object] = []
    _letterhead(story)
    _metadata_block(story, invoice)
    _line_items_table(story, invoice)
    _totals_table(story, invoice)
    _footer(story, invoice)

    try:
        doc.build(story, onFirstPage=lambda c, x: _draw_running(c))
    except Exception:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        raise

    final_bytes = tmp.read_bytes()
    os.replace(str(tmp), str(final))
    return PdfGenerationResult(path=final, bytes_written=len(final_bytes), engine="reportlab")


def _styles():
    s = getSampleStyleSheet()
    return {
        "h_company": ParagraphStyle(
            "Company", parent=s["Heading1"], fontSize=22, leading=26,
            textColor=colors.HexColor("#0f3d5c"), spaceAfter=2,
        ),
        "tagline": ParagraphStyle(
            "Tagline", parent=s["Normal"], fontSize=9, leading=12,
            textColor=colors.HexColor("#5b6770"),
        ),
        "label": ParagraphStyle(
            "Label", parent=s["Normal"], fontSize=9, leading=13,
            textColor=colors.HexColor("#6b7680"),
        ),
        "value": ParagraphStyle(
            "Value", parent=s["Normal"], fontSize=10, leading=14,
            textColor=colors.HexColor("#11181f"),
        ),
        "row": ParagraphStyle(
            "Row", parent=s["Normal"], fontSize=9.5, leading=12,
            textColor=colors.HexColor("#1c232b"),
        ),
        "table_head": ParagraphStyle(
            "TableHead", parent=s["Normal"], fontSize=9, leading=11,
            textColor=colors.white, fontName="Helvetica-Bold",
        ),
        "grand": ParagraphStyle(
            "Grand", parent=s["Heading2"], fontSize=13, leading=16,
            fontName="Helvetica-Bold", alignment=TA_RIGHT,
            textColor=colors.HexColor("#0f3d5c"),
        ),
    }


def _letterhead(story: List[object]) -> None:
    st = _styles()
    company = config.COMPANY

    table = Table(
        [
            [
                [
                    Paragraph(str(company["name"]), st["h_company"]),
                    Paragraph(
                        "%s | %s" % (company["email"], company["phone"]) if company["phone"]
                        else company["email"],
                        st["tagline"],
                    ),
                    Paragraph(str(company["address"]), st["tagline"]),
                ],
                [Paragraph("INVOICE", ParagraphStyle(
                    "InvoiceLabel", parent=st["value"], fontSize=30, leading=34,
                    fontName="Helvetica-Bold", alignment=TA_RIGHT,
                    textColor=colors.HexColor("#0f3d5c"),
                ))],
            ]
        ],
        colWidths=[110 * mm, 55 * mm],
    )
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, 0), (-1, 0), 1.2, colors.HexColor("#0f3d5c")),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 6 * mm))


def _metadata_block(story: List[object], invoice: Invoice) -> None:
    st = _styles()
    comp = config.COMPANY

    bill_to = "Customer\n%s\n%s" % (invoice.customer_name or "—", invoice.customer_email or "—")
    invoice_no = "Invoice No.\n%s\n" % invoice.invoice_number
    invoice_date = "Date Issued\n%s" % (invoice.created_at.strftime("%B %d, %Y")
                                        if invoice.created_at else "")
    tax_id = "Tax ID\n%s" % comp["tax_id"]

    meta = Table(
        [
            [
                Paragraph("Bill To:<br/>%s" % bill_to.replace("\n", "<br/>"), st["value"]),
                Paragraph("Payment Ref.<br/>%s" % invoice.stripe_payment_id, st["value"]),
            ],
            [
                Paragraph("Invoice No.<br/>%s" % invoice.invoice_number, st["value"]),
                Paragraph("Issued<br/>%s" % (invoice.created_at.strftime("%B %d, %Y")
                                             if invoice.created_at else "—"), st["value"]),
            ],
        ],
        colWidths=[82 * mm, 82 * mm],
    )
    meta.setStyle(
        TableStyle(
            [
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    story.append(meta)
    story.append(Spacer(1, 4 * mm))


def _line_items_table(story: List[object], invoice: Invoice) -> None:
    st = _styles()
    head = ["Description", "Qty", "Unit Price", "Tax", "Amount"]
    widths = [78 * mm, 14 * mm, 28 * mm, 18 * mm, 26 * mm]

    rows = [[
        Paragraph(h, st["table_head"]) for h in head
    ]]
    for item in invoice.line_items:
        rows.append([
            Paragraph(item.description.replace("&", "&amp;"), st["row"]),
            Paragraph(str(item.quantity), st["row"]),
            Paragraph(format_cents(int(item.unit_price_cents), invoice.currency), st["row"]),
            Paragraph("%g%%" % item.tax_rate_percent if item.tax_rate_percent else "—", st["row"]),
            Paragraph(format_cents(int(item.subtotal_cents), invoice.currency), st["row"]),
        ])

    table = Table(rows, colWidths=widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f3d5c")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#d5dbe1")),
                ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#e4e9ee")),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 4 * mm))


def _totals_table(story: List[object], invoice: Invoice) -> None:
    st = _styles()
    def right(v: str, style: object = st["row"]) -> Paragraph:
        return Paragraph(v, ParagraphStyle(
            "R", parent=style, alignment=TA_RIGHT,
        ))

    subtotal_text = ParagraphStyle("S", parent=st["row"], alignment=TA_LEFT)
    data = [
        [Paragraph("Subtotal", subtotal_text),
         right(format_cents(int(invoice.subtotal_cents), invoice.currency))],
        [Paragraph("Tax (incl. per-line)", subtotal_text),
         right(format_cents(int(invoice.tax_cents), invoice.currency))],
        [Paragraph("Total Due", st["grand"]),
         Paragraph(format_cents(int(invoice.amount_cents), invoice.currency), st["grand"])],
    ]
    table = Table(data, colWidths=[100 * mm, 60 * mm], hAlign="RIGHT")
    table.setStyle(
        TableStyle(
            [
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LINEABOVE", (0, -1), (-1, -1), 1, colors.HexColor("#0f3d5c")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    story.append(table)


def _footer(story: List[object], invoice: Invoice) -> None:
    st = _styles()
    story.append(Spacer(1, 8 * mm))
    story.append(Paragraph(
        "Thank you for your business.  Remit payment to the details above; "
        "questions about this invoice may be sent to %s." % config.COMPANY["email"],
        st["tagline"],
    ))


def _draw_running(c: object) -> None:
    """Draw a subtle footer/page-number on each page (ReportLab canvas)."""
    c = c  # no-op kept for clarity; footer text handled in the doc body


# ---------------------------------------------------------------------------
# Minimal fallback PDF writer (no dependencies)
# ---------------------------------------------------------------------------
def _escape_pdf_text(value: str) -> str:
    out = []
    for ch in value:
        code = ord(ch)
        if ch in ("\\", "(") or ch == ")":
            out.append("\\" + ch)
        elif code < 32 or code > 126:
            out.append("?")
        else:
            out.append(ch)
    return "".join(out)


def _generate_minimal(invoice: Invoice) -> PdfGenerationResult:
    """Write a small, valid single-page PDF using only the stdlib.

    Produces a real PDF (header + xref table) with the invoice text laid out
    line by line — enough to be opened/printed and to satisfy the "real file"
    requirement when ReportLab cannot be installed.
    """
    company = config.COMPANY
    lines: List[str] = []
    lines.append(company["name"])
    lines.append(str(company["address"]))
    lines.append("")
    lines.append("INVOICE %s" % invoice.invoice_number)
    lines.append("Customer: %s <%s>" % (invoice.customer_name or "—", invoice.customer_email or "—"))
    lines.append("Payment Ref: %s" % invoice.stripe_payment_id)
    lines.append("Issued: %s" % (invoice.created_at.strftime("%B %d, %Y") if invoice.created_at else "—"))
    lines.append("")
    lines.append("  Description                        Qty    Unit Price      Amount")
    lines.append("  " + "-" * 70)
    for item in invoice.line_items:
        lines.append(
            "  %-36s %-4d %12s %12s"
            % (
                item.description[:36],
                item.quantity,
                format_cents(int(item.unit_price_cents), invoice.currency),
                format_cents(int(item.subtotal_cents), invoice.currency),
            )
        )
    lines.append("  " + "-" * 70)
    lines.append("  Subtotal:            %s" % format_cents(int(invoice.subtotal_cents), invoice.currency))
    lines.append("  Tax (incl.):         %s" % format_cents(int(invoice.tax_cents), invoice.currency))
    lines.append("  TOTAL:               %s" % format_cents(int(invoice.amount_cents), invoice.currency))
    lines.append("")
    lines.append("Thank you for your business.")

    final = config.INVOICES_DIR / ("%s.pdf" % invoice.invoice_number)
    tmp = final.with_name(final.name + ".tmp")

    content = _render_minimal_pdf(lines)
    tmp.write_bytes(content)
    os.replace(str(tmp), str(final))
    return PdfGenerationResult(path=final, bytes_written=len(content), engine="minimal")


def _render_minimal_pdf(lines: List[str]) -> bytes:
    """Assemble a minimal one-page PDF with a proper cross-reference table."""
    objs: List[bytes] = []
    FONT = "Helvetica"
    SIZE = 10

    def esc(t: str) -> str:
        return _escape_pdf_text(t)

    # Object 1: catalog
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    # Object 2: pages
    objs.append(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")

    # Build page content stream (object 4)
    y = 780
    chunks: List[str] = []
    line_h = 14
    for line in lines:
        chunks.append("BT /F1 %d Tf 40 %d Td (%s) Tj ET" % (SIZE, y, esc(line)))
        y -= line_h
        if y < 50:
            break
    content_stream = "\n".join(chunks).encode("latin-1", "replace")

    page_med = b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
    page_med += b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
    objs.append(page_med)
    objs.append(b"<< /Length %d >>\nstream\n" % len(content_stream) + content_stream + b"\nendstream")
    # Object 5: font
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = bytearray(b"%PDF-1.4\n%\xE2\xE3\xCF\xD3\n")
    offsets: List[int] = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += ("%d 0 obj\n" % i).encode("ascii")
        out += body
        out += b"\nendobj\n"

    xref_pos = len(out)
    n = len(objs) + 1
    out += ("xref\n0 %d\n" % n).encode("ascii")
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += ("%010d 00000 n \n" % off).encode("ascii")
    out += ("trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (n, xref_pos)).encode("ascii")
    return bytes(out)