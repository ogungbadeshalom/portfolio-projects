"""Email sending (SMTP) for invoice PDFs.

Uses stdlib ``smtplib`` and ``email`` — no extra dependency.  The compose step
(building the MIME message with the PDF attached) is synchronous and pure; the
network send runs in a background thread via the async wrapper so it never
blocks the webhook response.

When ``EMAIL_DRY_RUN=1`` (or SMTP creds are unset) we log the composed message
instead of dialing the network, so the whole flow is demonstrable offline.
"""

from __future__ import annotations

import logging
import os
import smtplib
import ssl
import threading
import time
from email.message import EmailMessage
from email.utils import formataddr, formatdate
from pathlib import Path
from typing import Callable, Optional

from . import config
from .currencies import format_cents
from .models import Invoice

logger = logging.getLogger(__name__)


class EmailSendError(Exception):
    """Raised when an email could not be sent."""


def _format_amount(invoice: Invoice) -> str:
    return format_cents(int(invoice.amount_cents), invoice.currency)


def compose_invoice_email(invoice: Invoice, pdf_path: Path) -> EmailMessage:
    """Build the MIME message (PDF attachment + plain-text body).

    Pure/deterministic — no network — so it is unit-testable and safe to call
    from any thread.
    """
    msg = EmailMessage()
    company = config.COMPANY
    sender = (config.SMTP["from_name"], config.SMTP["from_email"])
    msg["From"] = formataddr(sender)
    msg["To"] = invoice.customer_email
    msg["Subject"] = "Your invoice %s from %s" % (invoice.invoice_number, company["name"])
    msg["Date"] = formatdate(localtime=True)

    body = (
        "Hello %s,\n\n"
        "Thank you for your payment.  Please find attached your invoice.\n\n"
        "  Invoice:      %s\n"
        "  Payment ref:  %s\n"
        "  Amount due:   %s\n\n"
        "If you have any questions, reply to this email or contact %s.\n\n"
        "Best regards,\n%s"
    ) % (
        invoice.customer_name or "there",
        invoice.invoice_number,
        invoice.stripe_payment_id,
        _format_amount(invoice),
        company["email"],
        company["name"],
    )
    msg.set_content(body)

    with open(str(pdf_path), "rb") as fh:
        pdf_bytes = fh.read()
    msg.add_attachment(
        pdf_bytes,
        maintype="application",
        subtype="pdf",
        filename="%s.pdf" % invoice.invoice_number,
    )
    return msg


def _smtp_connect():
    host = config.SMTP["host"]
    port = int(config.SMTP["port"])
    use_tls = config.SMTP["use_tls"]

    if use_tls:
        ctx = ssl.create_default_context()
        server = smtplib.SMTP(host, port, timeout=30)
        server.starttls(context=ctx)
    else:
        server = smtplib.SMTP(host, port, timeout=30)

    username = os.environ.get("SMTP_USERNAME", config.SMTP.get("username", ""))
    password = os.environ.get("SMTP_PASSWORD", config.SMTP.get("password", ""))
    if username:
        server.login(username, password)
    return server


def send_invoice_email_sync(invoice: Invoice) -> str:
    """Synchronously send the invoice email. Returns a status string.

    Returns ``"dry_run"`` when emailing is disabled/not configured, otherwise
    ``"sent"``.  Raises :class:`EmailSendError` on failure.
    """
    if not invoice.pdf_path or not Path(invoice.pdf_path).exists():
        raise EmailSendError(
            "no PDF on disk for invoice %s (%s)" % (invoice.invoice_number, invoice.stripe_payment_id)
        )

    pdf_path = Path(invoice.pdf_path)
    message = compose_invoice_email(invoice, pdf_path)

    if config.EMAIL_DRY_RUN or not (config.SMTP["host"] and config.SMTP["username"]):
        logger.info(
            "EMAIL_DRY_RUN invoice=%s to=%s subject=%r (not sending over network)",
            invoice.invoice_number,
            invoice.customer_email,
            message["Subject"],
        )
        return "dry_run"

    try:
        with _smtp_connect() as server:
            server.send_message(message)
    except Exception as exc:
        raise EmailSendError(
            "failed to send invoice %s to %s: %s"
            % (invoice.invoice_number, invoice.customer_email, exc)
        ) from exc

    logger.info(
        "emailed invoice=%s to=%s (pdf=%s)",
        invoice.invoice_number,
        invoice.customer_email,
        invoice.pdf_path,
    )
    return "sent"


def send_invoice_email_async(
    invoice: Invoice,
    *,
    on_done: Optional[Callable[[Invoice, str], None]] = None,
) -> threading.Thread:
    """Send the invoice email in a background thread so it never blocks the
    webhook.  Returns the started thread.

    Calling code may pass ``on_done(request, invoice, status)`` executed with
    the no-arg result status string.
    """
    def _worker(label: str = invoice.invoice_number) -> None:
        try:
            status = send_invoice_email_sync(invoice)
            if on_done:
                on_done(invoice, status)
        except EmailSendError as exc:
            logger.error(
                "email failed stripe_payment_id=%s invoice=%s: %s",
                invoice.stripe_payment_id,
                invoice.invoice_number,
                exc,
            )
            if on_done:
                on_done(invoice, "failed")

    thread = threading.Thread(
        target=_worker,
        name="invoice-email-%s" % time.time(),
        daemon=True,
    )
    thread.start()
    return thread