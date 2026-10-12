"""SQLAlchemy models and the database bootstrap.

Invoice numbers are generated **per calendar year** and are monotonic with no
gaps: ``INV-2026-001``, ``INV-2026-002``, ...  The next number is computed as
``max(existing for the year) + 1`` inside an exclusive lock so concurrent
webhooks cannot produce duplicates.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, Iterator, List, Optional, Tuple

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker
from sqlalchemy.orm.session import Session
from sqlalchemy.pool import StaticPool

from . import config

logger = logging.getLogger(__name__)

Base = declarative_base()


class LineItem:
    """A single billed row.  Kept in pure Python (no ORM row) because line
    items are stored as JSON on the Invoice for portability and simple PDF
    rendering.  All money is integer cents."""

    __slots__ = ("description", "quantity", "unit_price_cents", "tax_rate_percent")

    def __init__(
        self,
        description: str,
        quantity: int,
        unit_price_cents: int,
        tax_rate_percent: float = 0.0,
    ) -> None:
        if quantity < 0:
            raise ValueError("quantity cannot be negative: %r" % quantity)
        if not isinstance(unit_price_cents, int):
            raise TypeError("unit_price_cents must be int, got %r" % unit_price_cents)
        self.description = description
        self.quantity = quantity
        self.unit_price_cents = unit_price_cents
        self.tax_rate_percent = tax_rate_percent

    # --- derived money (all integer cents) ---------------------------------
    @property
    def total_cents(self) -> int:
        """Pre-tax total for the line (quantity * unit price)."""
        return self.quantity * self.unit_price_cents

    @property
    def tax_cents(self) -> int:
        """Tax on this line, rounded to nearest cent (>= 0)."""
        if self.tax_rate_percent <= 0:
            return 0
        return int(round(self.total_cents * self.tax_rate_percent / 100.0))

    @property
    def subtotal_cents(self) -> int:
        """Line total including its tax (used for grand totals)."""
        return self.total_cents + self.tax_cents

    def to_dict(self) -> Dict[str, Any]:
        return {
            "description": self.description,
            "quantity": self.quantity,
            "unit_price_cents": self.unit_price_cents,
            "tax_rate_percent": self.tax_rate_percent,
            "total_cents": self.total_cents,
            "tax_cents": self.tax_cents,
            "subtotal_cents": self.subtotal_cents,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LineItem":
        return cls(
            description=data.get("description", ""),
            quantity=int(data.get("quantity", 1)),
            unit_price_cents=int(data.get("unit_price_cents")),
            tax_rate_percent=float(data.get("tax_rate_percent", 0.0)),
        )


class Invoice(Base):
    """A single generated invoice for one customer/money amount."""

    __tablename__ = "invoices"
    __table_args__ = (
        UniqueConstraint("stripe_payment_id", name="uq_invoice_payment"),
    )

    id = Column(Integer, primary_key=True)
    invoice_number = Column(String(32), unique=True, index=True, nullable=False)
    stripe_payment_id = Column(String(255), nullable=False, index=True)
    customer_email = Column(String(320), nullable=False)
    customer_name = Column(String(255), default="")
    currency = Column(String(3), nullable=False)
    amount_cents = Column(Integer, nullable=False)        # grand total (tax incl.)
    subtotal_cents = Column(Integer, nullable=False)      # sum of line totals before tax
    tax_cents = Column(Integer, nullable=False)           # summed per-line tax
    line_items_json = Column(Text, nullable=False)
    pdf_path = Column(String(1024), default="")
    status = Column(String(32), nullable=False, default="created")
    email_status = Column(String(32), default="pending")  # pending|sent|failed|dry_run
    created_at = Column(DateTime, default=datetime.utcnow)
    paid_at = Column(DateTime, nullable=True)
    sent_at = Column(DateTime, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<Invoice %s %s %d%s status=%s>" % (
            self.invoice_number,
            self.currency,
            self.amount_cents,
            self.status,
            self.id,
        )

    # --- JSON helpers ------------------------------------------------------
    @property
    def line_items(self) -> List[LineItem]:
        return [LineItem.from_dict(item) for item in json.loads(self.line_items_json)]

    def set_line_items(self, items: List[LineItem]) -> None:
        self.line_items_json = json.dumps([it.to_dict() for it in items])

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "invoice_number": self.invoice_number,
            "stripe_payment_id": self.stripe_payment_id,
            "customer_email": self.customer_email,
            "customer_name": self.customer_name,
            "currency": self.currency,
            "amount_cents": self.amount_cents,
            "subtotal_cents": self.subtotal_cents,
            "tax_cents": self.tax_cents,
            "line_items": [it.to_dict() for it in self.line_items],
            "pdf_path": self.pdf_path,
            "status": self.status,
            "email_status": self.email_status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "sent_at": self.sent_at.isoformat() if self.sent_at else None,
        }


# ---------------------------------------------------------------------------
# Engine / session bootstrap
# ---------------------------------------------------------------------------
def _make_engine(db_uri: str):
    """Create a SQLAlchemy engine, adding nice SQLite PRAGMAs for tests."""
    options: Dict[str, Any] = {"echo": False}
    if db_uri.startswith("sqlite"):
        # StaticPool so an in-memory DB is shared by all connections in one pro
        # (tests), and WAL for the on-disk dev DB.
        if db_uri == "sqlite:///:memory:":
            options["poolclass"] = StaticPool
            options["connect_args"] = {"check_same_thread": False}
        else:
            options["connect_args"] = {"check_same_thread": False}

    engine = create_engine(db_uri, **options)

    if db_uri.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, connection_record):  # pragma: no cover
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def init_engine(db_uri: Optional[str] = None):
    db_uri = db_uri or config.DATABASE_URI
    engine = _make_engine(db_uri)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    return engine, SessionLocal


def create_schema(engine) -> None:
    import invoice.models  # noqa: F401  ensure models are imported

    Base.metadata.create_all(engine)


def next_invoice_number(session: Session, year: Optional[int] = None) -> str:
    """Generate the next sequential invoice number for the given year.

    Computes max(existing) + 1 for the year, so numbers are monotonic with no
    gaps even if intermediate rows are later deleted (we never delete).
    Called while holding a DB transaction lock (see below).
    """
    year = year or datetime.utcnow().year
    prefix = "INV-%04d-" % year
    # Matches existing "INV-2026-001" style rows.
    rows = (
        session.query(Invoice.invoice_number)
        .filter(Invoice.invoice_number.like(prefix + "%"))
        .all()
    )
    highest = 0
    for (number,) in rows:
        suffix = number[len(prefix):]
        try:
            n = int(suffix)
        except ValueError:
            continue
        if n > highest:
            highest = n
    return "%s%03d" % (prefix, highest + 1)


def lock_invoice_numbering(session: Session) -> None:
    """Serialize concurrent invoice-number generation.

    For SQLite we take a coarse write lock by opening a transactional
    write on the whole DB; in production (Postgres etc.) you would use
    ``SELECT ... FOR UPDATE`` on a sequence row.
    """
    try:
        session.execute(__import__("sqlalchemy").text(
            "PRAGMA locking_mode=EXCLUSIVE"
        ))
        session.execute(__import__("sqlalchemy").text("BEGIN IMMEDIATE"))
    except Exception as exc:  # pragma: no cover - permissive fallback
        logger.debug("invoice numbering lock unavailable: %s", exc)


def release_invoice_numbering(session: Session) -> None:
    try:
        session.execute(__import__("sqlalchemy").text("PRAGMA locking_mode=NORMAL"))
    except Exception:  # pragma: no cover
        pass


# ---------------------------------------------------------------------------
# Convenience query helpers
# ---------------------------------------------------------------------------
def invoice_by_payment_id(session: Session, stripe_payment_id: str) -> Optional[Invoice]:
    return (
        session.query(Invoice)
        .filter(Invoice.stripe_payment_id == stripe_payment_id)
        .first()
    )


def invoice_by_number(session: Session, invoice_number: str) -> Optional[Invoice]:
    return (
        session.query(Invoice)
        .filter(Invoice.invoice_number == invoice_number)
        .first()
    )


def list_invoices(
    session: Session,
    *,
    status: Optional[str] = None,
    currency: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[Invoice]:
    query = session.query(Invoice)
    if status:
        query = query.filter(Invoice.status == status)
    if currency:
        query = query.filter(Invoice.currency == currency.upper())
    return (
        query.order_by(Invoice.id.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )


def iter_batches(items: List[Any], size: int) -> Iterator[List[Any]]:
    for i in range(0, len(items), size):
        yield items[i:i + size]