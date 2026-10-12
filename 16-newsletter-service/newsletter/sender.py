"""Email transport + bulk campaign sending with rate limiting.

Three interchangeable backends (all implement ``async send(mail)``):

- :class:`AioSmtpSender`  -- async SMTP via **aiosmtplib** (preferred, non-blocking).
- :class:`SmtpSender`     -- stdlib :mod:`smtplib` run in a thread executor
                             (fallback when aiosmtplib is not importable).
- :class:`FileSender`     -- dev backend; writes each message as an ``.eml``
                             file under the configured ``outbox/`` directory so
                             the whole feature is demonstrable with zero SMTP.

Selection: ``NEWSLETTER_SENDER_BACKEND`` = ``auto`` | ``aiosmtplib`` | ``smtplib``
| ``file``. ``auto`` tries aiosmtplib, else smtplib, else FileSender. This keeps
the app offline-demoable and Mailtrap-configurable from env vars alone.

:func:`send_campaign` is the rate-limited bulk sender that the CLI and the admin
UI both call; it is a *queued loop* that never fires more than
``settings.rate_per_min`` emails per minute (spam-flag protection).
"""

from __future__ import annotations

import asyncio
import email.message
import email.utils
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Protocol

from newsletter.config import settings
from newsletter.mailer import Mail


class Sender(Protocol):
    """Structural type: any backend with an async ``send(mail)`` method."""

    async def send(self, mail: Mail) -> None:
        ...


# --- backends -----------------------------------------------------------------

class FileSender:
    """Dev backend: append each message to a plain-text ``.eml`` under an outbox
    directory (one file per recipient), so sending is inspectable and requires
    no network or SMTP account."""

    def __init__(self, outbox_dir: Optional[Path] = None) -> None:
        self.outbox_dir = (outbox_dir or settings.outbox_dir).resolve()
        self.outbox_dir.mkdir(parents=True, exist_ok=True)

    def _render(self, mail: Mail) -> str:
        msg = email.message.EmailMessage()
        msg["From"] = mail.from_email or settings.from_email
        msg["To"] = mail.to_email
        msg["Subject"] = mail.subject
        msg["Date"] = email.utils.formatdate(localtime=True)
        msg.set_content(mail.text)
        if mail.html:
            msg.add_alternative(mail.html, subtype="html")
        for k, v in (mail.headers or {}).items():
            msg[k] = v
        return msg.as_string()

    async def send(self, mail: Mail) -> None:
        safe = "".join(c for c in mail.to_email if c.isalnum() or c in "@.-_") or "unknown"
        filename = f"{int(time.time() * 1000)}-{safe}.eml"
        (self.outbox_dir / filename).write_text(
            self._render(mail), encoding="utf-8"
        )


class AioSmtpSender:
    """Async SMTP via aiosmtplib (non-blocking, preferred)."""

    def __init__(self) -> None:
        import aiosmtplib  # local import: backend is optional at runtime

        self._client = aiosmtplib.SMTP(
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_username or None,
            password=settings.smtp_password or None,
            use_tls=settings.smtp_use_tls,
            timeout=20,
        )

    async def send(self, mail: Mail) -> None:
        import aiosmtplib

        message: email.message.EmailMessage = email.message.EmailMessage()
        message["From"] = mail.from_email or settings.from_email
        message["To"] = mail.to_email
        message["Subject"] = mail.subject
        message["Date"] = email.utils.formatdate(localtime=True)
        message.set_content(mail.text)
        if mail.html:
            message.add_alternative(mail.html, subtype="html")
        message["List-Unsubscribe"] = "<mailto:unsubscribe@example.com>"  # deliverability nicety
        await self._client.send_message(
            message,
            sender=message["From"],
            recipients=[mail.to_email],
        )


class SmtpSender:
    """Blocking stdlib smtplib run inside a thread so the async surface stays
    non-blocking. Used as the fallback when aiosmtplib is unavailable."""

    def _send_sync(self, mail: Mail) -> None:
        import smtplib
        from email.mime.multipart import MIMEMultipart

        msg = email.message.EmailMessage()
        msg["From"] = mail.from_email or settings.from_email
        msg["To"] = mail.to_email
        msg["Subject"] = mail.subject
        msg.set_content(mail.text)
        if mail.html:
            msg.add_alternative(mail.html, subtype="html")
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as s:
            if settings.smtp_use_tls:
                s.starttls(context=None)
            if settings.smtp_username:
                s.login(settings.smtp_username, settings.smtp_password)
            s.send_message(msg, to_addrs=[mail.to_email])

    async def send(self, mail: Mail) -> None:
        await asyncio.get_event_loop().run_in_executor(None, self._send_sync, mail)


def build_sender(backend: Optional[str] = None) -> Sender:
    """Instantiate the configured (or ``auto``) transfer backend."""
    choice = (backend or settings.sender_backend).lower()
    if choice == "iosmtplib" or choice == "aiosmtplib":
        return AioSmtpSender()
    if choice == "smtplib":
        return SmtpSender()
    if choice == "file":
        return FileSender()
    # auto: prefer aiosmtplib, fall back to smtplib, then file.
    try:  # pragma: no cover - depends on environment
        import aiosmtplib  # noqa: F401
        return AioSmtpSender()
    except ImportError:
        try:  # pragma: no cover
            import smtplib  # noqa: F401
            return SmtpSender()
        except ImportError:  # pragma: no cover - extremely unusual
            return FileSender()


# --- bulk sending -------------------------------------------------------------

class RateLimiter:
    """Token-bucket rate limiter ensuring at most ``per_minute`` sends per 60s
    window. Tolerates slow sends by letting their elapsed time count against the
    quota."""

    def __init__(self, per_minute: float) -> None:
        self.rate = max(per_minute, 1)
        self._interval = 60.0 / self.rate
        self._next = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            if now < self._next:
                await asyncio.sleep(self._next - now)
            self._next = time.monotonic() + self._interval


async def send_campaign(
    db_session,
    campaign,
    sender: Sender | None = None,
    *,
    rate_limit: float | None = None,
    progress=None,
) -> dict:
    """Send ``campaign`` to every ACTIVE subscriber, recording a Send row each.

    Respects ``settings.rate_per_min`` (or ``rate_limit`` override) between
    sends. Idempotent per (campaign, subscriber): uses an upsert so re-running
    after a partial failure does not double-send to already-processed rows when
    using SQLite. Returns a dict of aggregate counts for the CLI output.
    """
    from sqlalchemy import select
    from newsletter.models import CampaignStatus, Send, Subscriber, SubscriberStatus

    limiter = RateLimiter(rate_limit if rate_limit is not None else settings.rate_per_min)
    sender = sender or build_sender()

    campaign.status = CampaignStatus.SENDING.value

    rows = (
        await db_session.execute(
            select(Subscriber).where(Subscriber.status == SubscriberStatus.ACTIVE.value)
        )
    ).scalars().all()

    sent = 0
    failed = 0
    now = datetime.now(timezone.utc)

    for sub in rows:
        # Skip subscribers that already received this campaign (idempotent).
        existing = (
            await db_session.execute(
                select(Send).where(
                    Send.campaign_id == campaign.id,
                    Send.subscriber_id == sub.id,
                )
            )
        ).scalar_one_or_none()
        if existing is not None and existing.sent_at is not None:
            sent += 1
            continue

        mail = await _build_campaign_mail(campaign, sub)
        try:
            await sender.send(mail)
        except Exception:  # noqa: BLE001 - one bad recipient must not kill the run
            failed += 1
            _upsert_send(db_session, campaign.id, sub.id, now=now, bounced=True)
            continue

        if existing is not None:
            existing.sent_at = existing.sent_at or now
            existing.bounced = False
            existing_sub = existing
        else:
            db_session.add(
                Send(
                    campaign_id=campaign.id,
                    subscriber_id=sub.id,
                    sent_at=now,
                )
            )
        sent += 1
        await db_session.commit()
        await limiter.wait()
        if progress is not None:
            progress(sent + failed)

    campaign.status = CampaignStatus.SENT.value
    campaign.sent_at = datetime.now(timezone.utc)
    await db_session.commit()
    return {"sent": sent, "failed": failed, "recipients": len(rows)}


async def _build_campaign_mail(campaign, subscriber) -> Mail:
    from newsletter.mailer import Mailer

    mailer = Mailer()
    return mailer.campaign(campaign, subscriber, subscriber_id=subscriber.id)


def _upsert_send(session, campaign_id: int, subscriber_id: int, *, now, bounced: bool = False) -> None:
    from sqlalchemy import select
    from newsletter.models import Send

    row = (
        session.execute(
            select(Send).where(
                Send.campaign_id == campaign_id,
                Send.subscriber_id == subscriber_id,
            )
        )
        .scalars()
        .first()
    )
    if row is None:
        session.add(
            Send(
                campaign_id=campaign_id,
                subscriber_id=subscriber_id,
                sent_at=now,
                bounced=bounced,
            )
        )
    else:
        row.bounced = bounced
    session.commit()