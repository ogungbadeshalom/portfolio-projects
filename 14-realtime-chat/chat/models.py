"""SQLAlchemy ORM models for the chat application.

User, Room, Message, RoomMembership -- persisted in SQLite and designed to
survive a server restart (message history is durable).

The declarative Base is defined in :mod:`chat.database` and imported here so
that every model inherits from the same metadata.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship

from chat.database import Base


class User(Base):
    """A registered chat user."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    # Never stores plaintext -- always a bcrypt/scrypt hash.
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    # Mark deleted users such that reconnect handling can be explicit.
    is_active = Column(Boolean, default=True, nullable=False)

    messages = relationship(
        "Message", back_populates="user", cascade="all, delete-orphan"
    )
    memberships = relationship(
        "RoomMembership", back_populates="user", cascade="all, delete-orphan"
    )


class Room(Base):
    """A chat room that multiple users can join."""

    __tablename__ = "rooms"

    id = Column(Integer, primary_key=True)
    name = Column(String(128), unique=True, nullable=False, index=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=func.now(), nullable=False)

    creator = relationship("User", foreign_keys=[created_by])
    messages = relationship(
        "Message", back_populates="room", cascade="all, delete-orphan"
    )
    memberships = relationship(
        "RoomMembership", back_populates="room", cascade="all, delete-orphan"
    )


class Message(Base):
    """A single chat message persisted to the database."""

    __tablename__ = "messages"

    id = Column(Integer, primary_key=True)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    text = Column(Text, nullable=False)
    created_at = Column(
        DateTime, default=func.now(), nullable=False, index=True
    )

    room = relationship("Room", back_populates="messages")
    user = relationship("User", back_populates="messages")


class RoomMembership(Base):
    """Tracks which users have joined which rooms."""

    __tablename__ = "room_memberships"
    __table_args__ = (UniqueConstraint("user_id", "room_id", name="uq_member_room"),)

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=False, index=True)
    joined_at = Column(DateTime, default=func.now(), nullable=False)

    user = relationship("User", back_populates="memberships")
    room = relationship("Room", back_populates="memberships")


def to_iso(dt: Optional[datetime]) -> Optional[str]:
    """Convert a datetime to an ISO-8601 string for JSON payloads."""
    if dt is None:
        return None
    return dt.isoformat()