"""Public subscriber lifecycle: subscribe (double opt-in), confirm, unsubscribe.

All three entry points are small, dependency-light functions so both the HTTP
routes (FastAPI) and the CLI can reuse them against an async session.
"""

from __future__ import annotations

import re
from typing import Optional

from sqlalchemy import select

from newsletter.models import Subscriber, SubscriberStatus, new_unsubscribe_secret
from newsletter.security import verify_unsubscribe_token
from newsletter.sender import build_sender
from newsletter.mailer import Mailer


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class SubscribeError(Exception):
    """Raised for recoverable, user-facing errors (invalid email, etc.)."""


def normalize_email(email: str) -> str:
    """Lowercase + trim + basic validation. Raises SubscribeError if invalid."""
    email = (email or "").strip().lower()
    if not email or not _EMAIL_RE.match(email):
        raise SubscribeError("A valid email address is required.")
    return email


async def subscribe(
    session,
    email: str,
    name: Optional[str] = None,
    *,
    sender=None,
    mailer: Optional[Mailer] = None,
) -> Subscriber:
    """Register a NEW subscriber in PENDING state and send the confirmation email.

    Double opt-in: the person is not yet ACTIVE until they click the HMAC-signed
    confirmation link. Re-subscribing an already-active address is a no-op
    (returns the existing row); an unsubscribed address is re-registered as
    active-ready and refreshed.

    Returns the Subscriber row. Uses our async session but performs the send
    itself, so callers may pass a real sender or a stubbed one for tests.
    """
    email = normalize_email(email)
    existing = (
        await session.execute(select(Subscriber).where(Subscriber.email == email))
    ).scalar_one_or_none()

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)

    if existing is not None:
        if existing.status == SubscriberStatus.UNSUBSCRIBED.value:
            # Someone re-subscribing after unsubscribing: confirm again (opt-in).
            existing.status = SubscriberStatus.PENDING.value
            existing.confirmed_at = None
            existing.subscribed_at = now
            mailer = mailer or Mailer()
            sender = sender or build_sender()
            await sender.send(mailer.confirmation(existing))
            await session.commit()
            return existing
        # active or pending: do not spam repeated confirmations.
        return existing

    sub = Subscriber(
        email=email,
        name=(name or "").strip() or None,
        status=SubscriberStatus.PENDING.value,
        unsubscribe_token=new_unsubscribe_secret(),
    )
    session.add(sub)
    await session.commit()

    mailer = mailer or Mailer()
    sender = sender or build_sender()
    await sender.send(mailer.confirmation(sub))
    await session.commit()
    return sub


async def confirm(session, email: str, token: str) -> Subscriber:
    """Confirm a pending subscription (double opt-in link click)."""
    email = normalize_email(email)
    verified = verify_unsubscribe_token(token)
    if verified is None or verified != email:
        raise SubscribeError("Invalid or expired confirmation link.")
    sub = (
        await session.execute(select(Subscriber).where(Subscriber.email == email))
    ).scalar_one_or_none()
    if sub is None:
        raise SubscribeError("No such subscriber.")
    from datetime import datetime, timezone
    sub.status = SubscriberStatus.ACTIVE.value
    sub.confirmed_at = datetime.now(timezone.utc)
    await session.commit()
    return sub


async def unsubscribe_by_token(session, token: str) -> Optional[Subscriber]:
    """One-click unsubscribe from ``GET /api/unsubscribe?token=...``.

    Verifies the HMAC signature first (rejects forged tokens), then marks the
    matching subscriber as UNSUBSCRIBED. Returns the subscriber or None if the
    token is invalid/unknown.
    """
    email = verify_unsubscribe_token(token)
    if email is None:
        return None
    sub = (
        await session.execute(select(Subscriber).where(Subscriber.email == email))
    ).scalar_one_or_none()
    if sub is None:
        return None
    if sub.status != SubscriberStatus.UNSUBSCRIBED.value:
        sub.status = SubscriberStatus.UNSUBSCRIBED.value
        await session.commit()
    return sub