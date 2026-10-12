"""Campaign CRUD (admin-facing) plus query helpers for the dashboard/CLI.

Functions take an async SQLAlchemy session and are shared by the HTTP routes and
the Click CLI so behavior stays consistent across entry points.
"""

from __future__ import annotations

import csv
import io
from typing import Optional

from sqlalchemy import func, select

from newsletter.models import (
    Campaign,
    CampaignStatus,
    Send,
    Subscriber,
    SubscriberStatus,
    new_unsubscribe_secret,
)


async def create_campaign(session, subject: str, html_body: str = "", text_body: str = "") -> Campaign:
    """Create a campaign in DRAFT state."""
    subject = (subject or "").strip()
    if not subject:
        raise ValueError("A subject is required.")
    campaign = Campaign(
        subject=subject,
        html_body=html_body or "",
        text_body=text_body or "",
        status=CampaignStatus.DRAFT.value,
    )
    session.add(campaign)
    await session.commit()
    await session.refresh(campaign)
    return campaign


async def get_campaign(session, campaign_id: int) -> Optional[Campaign]:
    return (
        await session.execute(select(Campaign).where(Campaign.id == campaign_id))
    ).scalar_one_or_none()


async def list_campaigns(session) -> list[Campaign]:
    rows = (
        await session.execute(select(Campaign).order_by(Campaign.id.desc()))
    ).scalars().all()
    return list(rows)


async def update_campaign(
    session,
    campaign: Campaign,
    *,
    subject: Optional[str] = None,
    html_body: Optional[str] = None,
    text_body: Optional[str] = None,
) -> Campaign:
    if subject is not None:
        campaign.subject = subject.strip()
    if html_body is not None:
        campaign.html_body = html_body
    if text_body is not None:
        campaign.text_body = text_body
    await session.commit()
    await session.refresh(campaign)
    return campaign


async def delete_campaign(session, campaign: Campaign) -> None:
    await session.delete(campaign)
    await session.commit()


# --- stats --------------------------------------------------------------------

async def get_campaign_stats(session, campaign_id: int) -> dict:
    """Per-campaign analytics: sent, opened, clicked, bounced."""
    sent = (
        await session.execute(
            select(func.count(Send.id)).where(
                Send.campaign_id == campaign_id,
                Send.sent_at.is_not(None),
            )
        )
    ).scalar_one()

    opened = (
        await session.execute(
            select(func.count(Send.id)).where(
                Send.campaign_id == campaign_id,
                Send.opened_at.is_not(None),
            )
        )
    ).scalar_one()

    clicked = (
        await session.execute(
            select(func.count(Send.id)).where(
                Send.campaign_id == campaign_id,
                Send.clicked_at.is_not(None),
            )
        )
    ).scalar_one()

    bounced = (
        await session.execute(
            select(func.count(Send.id)).where(
                Send.campaign_id == campaign_id,
                Send.bounced.is_(True),
            )
        )
    ).scalar_one()

    opens_rate = round((opened / sent * 100), 1) if sent else 0.0
    clicks_rate = round((clicked / opened * 100), 1) if opened else 0.0

    return {
        "campaign_id": campaign_id,
        "sent": sent,
        "opened": opened,
        "clicked": clicked,
        "bounced": bounced,
        "opens_rate": opens_rate,
        "clicks_rate": clicks_rate,
    }


async def get_global_stats(session) -> dict:
    """Dashboard headline numbers across all campaigns + the subscriber list."""
    subscribers_total = (
        await session.execute(select(func.count(Subscriber.id)))
    ).scalar_one()
    active = (
        await session.execute(
            select(func.count(Subscriber.id)).where(
                Subscriber.status == SubscriberStatus.ACTIVE.value
            )
        )
    ).scalar_one()
    unsubscribed = (
        await session.execute(
            select(func.count(Subscriber.id)).where(
                Subscriber.status == SubscriberStatus.UNSUBSCRIBED.value
            )
        )
    ).scalar_one()
    pending = (
        await session.execute(
            select(func.count(Subscriber.id)).where(
                Subscriber.status == SubscriberStatus.PENDING.value
            )
        )
    ).scalar_one()
    campaigned_sent = (
        await session.execute(
            select(func.count(Send.id)).where(Send.sent_at.is_not(None))
        )
    ).scalar_one()
    opened = (
        await session.execute(
            select(func.count(Send.id)).where(Send.opened_at.is_not(None))
        )
    ).scalar_one()
    clicked = (
        await session.execute(
            select(func.count(Send.id)).where(Send.clicked_at.is_not(None))
        )
    ).scalar_one()

    return {
        "subscribers": subscribers_total,
        "active": active,
        "pending": pending,
        "unsubscribed": unsubscribed,
        "sent": campaigned_sent,
        "opened": opened,
        "clicked": clicked,
    }


async def list_subscribers(session, *, status: Optional[str] = None) -> list[Subscriber]:
    stmt = select(Subscriber).order_by(Subscriber.id.desc())
    if status:
        stmt = stmt.where(Subscriber.status == status)
    rows = (await session.execute(stmt)).scalars().all()
    return list(rows)


# --- CSV import / export (stdlib csv) -----------------------------------------

def _csv_columns() -> list[str]:
    return ["email", "name", "status", "unsubscribe_token", "subscribed_at"]


def subscribers_to_csv(subscribers: list[Subscriber]) -> str:
    """Serialise subscribers to a CSV string (import-compatible round trip)."""
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(_csv_columns())
    for s in subscribers:
        writer.writerow(
            [
                s.email,
                s.name or "",
                s.status,
                s.unsubscribe_token,
                s.subscribed_at.isoformat() if s.subscribed_at else "",
            ]
        )
    return out.getvalue()


def parse_subscribers_csv(text: str) -> list[dict]:
    """Parse a CSV blob into normalized subscriber dicts (email, name).

    Ignores rows without a usable email. Emails are lowercased. Only the first
    two columns are treated as meaningful (email, name); extra columns (status,
    token, timestamp) from a re-import are intentionally dropped so tokens are
    always re-created server-side.
    """
    reader = csv.reader(io.StringIO(text))
    header = None
    results: list[dict] = []
    for row in reader:
        if not row or not any(cell.strip() for cell in row):
            continue
        if header is None:
            header = [c.lower().strip() for c in row]
            continue
        try:
            if len(row) >= 1 and row[0].strip():
                results.append({"email": row[0].strip().lower(), "name": (row[1].strip() if len(row) > 1 else "")})
        except IndexError:
            continue
    return results


async def import_subscribers(session, text: str) -> dict:
    """Bulk-add pending subscribers from CSV text (double opt-in applies)."""
    from newsletter.subscribe import normalize_email, SubscribeError

    parsed = parse_subscribers_csv(text)
    added = 0
    already = 0
    invalid = 0
    for item in parsed:
        try:
            email = normalize_email(item["email"])
        except SubscribeError:
            invalid += 1
            continue
        existing = (
            await session.execute(select(Subscriber).where(Subscriber.email == email))
        ).scalar_one_or_none()
        if existing is not None and existing.status != SubscriberStatus.UNSUBSCRIBED.value:
            already += 1
            continue
        # PENDING import: they still must confirm before receiving campaigns.
        session.add(
            Subscriber(
                email=email,
                name=item.get("name") or None,
                status=SubscriberStatus.PENDING.value,
                unsubscribe_token=new_unsubscribe_secret(),
            )
        )
        added += 1
    await session.commit()
    return {"added": added, "already_present": already, "invalid_rows": invalid}