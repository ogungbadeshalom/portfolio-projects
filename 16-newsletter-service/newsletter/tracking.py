"""Open pixel and click-redirect tracking.

Both endpoints update the matching :class:`Send` row (so analytics work) and are
deliberately cheap / non-blocking: the pixel answers with a bare 1x1 transparent
GIF and ``no-store`` cache headers (so each recipient's open is counted), and
the click endpoint returns a 302 only after validating the destination URL to
prevent an open-redirect.

An unknown/queried ``sid`` (subscriber id) is tolerated — at worst we fail to
find a Send and simply do not record anything.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import and_, select

from newsletter.models import Campaign, Send
from newsletter.security import is_safe_redirect_url

# A minimal, well-formed 1x1 transparent GIF (65 bytes).
TRANSPARENT_1PX_GIF = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9"
    b"\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02"
    b"\x02D\x01\x00;"
)


async def record_open(session, campaign_id: int, subscriber_id: Optional[int]) -> bool:
    """Mark the campaign's Send as opened (no-op if already/never opened)."""
    if subscriber_id is None:
        return False
    send = (
        await session.execute(
            select(Send).where(
                and_(
                    Send.campaign_id == campaign_id,
                    Send.subscriber_id == subscriber_id,
                )
            )
        )
    ).scalar_one_or_none()
    if send is None:
        return False
    if send.opened_at is None:
        from datetime import datetime, timezone
        send.opened_at = datetime.now(timezone.utc)
        await session.commit()
    return True


async def resolve_click_target(
    session, campaign_id: int, subscriber_id: Optional[int], target: str
) -> Optional[str]:
    """Validate the click destination and record the click on the Send row.

    Returns the target URL only if it passes :func:`is_safe_redirect_url`;
    otherwise returns ``None`` (the caller then serves a neutral page instead of
    redirecting, so an open redirect is impossible).
    """
    if not is_safe_redirect_url(target):
        return None
    if subscriber_id is not None:
        send = (
            await session.execute(
                select(Send).where(
                    and_(
                        Send.campaign_id == campaign_id,
                        Send.subscriber_id == subscriber_id,
                    )
                )
            )
        ).scalar_one_or_none()
        if send is not None and send.clicked_at is None:
            from datetime import datetime, timezone
            send.clicked_at = datetime.now(timezone.utc)
            await session.commit()

    # Campaign existence not required for the redirect itself, but keep an easy
    # query in case callers want it (e.g. building fallback copy).
    return target


async def campaign_exists(session, campaign_id: int) -> bool:
    return (
        await session.execute(select(Campaign.id).where(Campaign.id == campaign_id))
    ).scalar_one_or_none() is not None