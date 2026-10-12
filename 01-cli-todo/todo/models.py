"""Data model for the CLI Todo App.

This module defines the single source of truth for what a todo *looks* like:
its fields, how it validates, and how it serializes to and from JSON.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, field_validator

# The current schema version, so future migrations can be handled gracefully
# instead of failing on unexpected shapes in the data file.
SCHEMA_VERSION = 1


class Priority(str, Enum):
    """The three supported todo priorities, ordered low -> high."""

    LOW = "low"
    MED = "med"
    HIGH = "high"

    @property
    def weight(self) -> int:
        """Return a numeric ordering so priorities can be sorted.

        Returns:
            int: 0 for low, 1 for med, 2 for high.
        """
        return {Priority.LOW: 0, Priority.MED: 1, Priority.HIGH: 2}[self]


def _utcnow() -> datetime:
    """Return the current UTC timestamp, timezone-aware.

    Uses a small wrapper so tests can patch the clock cleanly.

    Returns:
        datetime: the current time in UTC.
    """
    return datetime.now(timezone.utc)


# Pydantic v1 needs `Optional[X]` (not `X | None`) in field annotations at
# runtime; the surrounding types remain introspection-friendly with
# ``from __future__ import annotations``.
class Todo(BaseModel):
    """A single todo item.

    Attributes:
        id: Unique, 1-indexed identifier for the todo.
        title: Short human-readable summary of the task.
        due: Optional ``YYYY-MM-DD`` due date.
        priority: One of ``low``, ``med``, ``high``.
        done: Whether the todo has been completed.
        created_at: UTC timestamp recording when the todo was added.
    """

    id: int
    title: str = Field(min_length=1, max_length=200)
    due: Optional[date] = None
    priority: Priority = Priority.MED
    done: bool = False
    created_at: datetime = Field(default_factory=_utcnow)

    @field_validator("title")
    @classmethod
    def _title_must_not_be_blank(cls, value: str) -> str:
        """Reject titles that are only whitespace.

        Args:
            value: The raw title provided by the caller.

        Returns:
            str: The stripped title.

        Raises:
            ValueError: If the title is empty after stripping.
        """
        stripped = value.strip()
        if not stripped:
            raise ValueError("Todo title cannot be blank.")
        return stripped

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the todo to a plain, JSON-friendly dict.

        Returns:
            dict: A mapping of field names to primitive values.
        """
        return self.model_dump(mode="json")

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Todo":
        """Build a Todo back from a previously serialized dict.

        Args:
            data: A dict produced by :meth:`to_dict`.

        Returns:
            Todo: The reconstructed todo instance.
        """
        return cls.model_validate(data)