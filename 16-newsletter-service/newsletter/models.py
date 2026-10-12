"""Declarative ORM models: Subscriber, Campaign, Send.

A single :class:`Send` row records the delivery of one campaign to one
subscriber and carries the tracking state that drives the analytics dashboard:

- ``sent_at``   -- set when the email is handed to the sender backend
- ``opened_at`` -- set when the 1x1 tracking pixel is requested
- ``clicked_at``-- set when a wrapped (redirected) link is followed
- ``bounced``   -- flag raised by the bounce webhook / an SMTP error

This keeps open/click/unsubscribe statistics a simple query over :class:`Send`
rather than a sprawling event log.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    """Timezone-aware UTC 'now' used as the default for all timestamps."""
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Declarative base shared by every model."""


class SubscriberStatus(str, Enum):
    """Lifecycle states for a subscriber."""

    PENDING = "pending"  # signed up, confirmation email not yet confirmed
    ACTIVE = "active"  # double opt-in confirmed
    UNSUBSCRIBED = "unsubscribed"
    BOUNCED = "bounced"


class CampaignStatus(str, Enum):
    """Lifecycle states for a campaign."""

    DRAFT = "draft"
    SENDING = "sending"
    SENT = "sent"


class Subscriber(Base):
    """A person on the list. Emails are stored lowercase and unique.

    ``unsubscribe_token`` is HMAC-signed server-side; the token in the
    unsubscribe link is what makes one-click unsubscribe abuse-resistant.
    """

    __tablename__ = "subscribers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True, default=None)
    status: Mapped[str] = mapped_column(String(20), default=SubscriberStatus.PENDING.value, nullable=False)
    unsubscribe_token: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    subscribed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )

    sends: Mapped[list["Send"]] = relationship(
        back_populates="subscriber", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<Subscriber {self.email} [{self.status}]>"


def new_unsubscribe_secret() -> str:
    """Random secret stored on the Subscriber and embedded (HMAC-wrapped) in the
    unsubscribe link so only the owner of that subscriber row can unsubscribe."""
    return secrets.token_urlsafe(32)


class Campaign(Base):
    """A broadcast message with subject plus HTML and plaintext bodies.

    ``status`` moves DRAFT -> SENDING -> SENT as ``newsletter campaign send``
    runs. ``sent_at`` is stamped when the send loop completes (not started),
    which makes "in progress" distinguishable from "done".
    """

    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    html_body: Mapped[str] = mapped_column(Text, default="", nullable=False)
    text_body: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default=CampaignStatus.DRAFT.value, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )

    sends: Mapped[list["Send"]] = relationship(
        back_populates="campaign",
        cascade="all, delete-orphan",
        primaryjoin="Send.campaign_id == Campaign.id",
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<Campaign {self.id} {self.subject!r} [{self.status}]>"


class Send(Base):
    """One campaign -> one subscriber delivery + its tracking timeline."""

    __tablename__ = "sends"
    __table_args__ = (UniqueConstraint("campaign_id", "subscriber_id", name="uq_send_campaign_subscriber"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"), index=True, nullable=False
    )
    subscriber_id: Mapped[int] = mapped_column(
        ForeignKey("subscribers.id", ondelete="CASCADE"), index=True, nullable=False
    )
    sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    opened_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    clicked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    bounced: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    campaign: Mapped["Campaign"] = relationship(
        back_populates="sends", foreign_keys=[campaign_id]
    )
    subscriber: Mapped["Subscriber"] = relationship(
        back_populates="sends", foreign_keys=[subscriber_id]
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<Send campaign={self.campaign_id} sub={self.subscriber_id} opened={self.opened_at}>"