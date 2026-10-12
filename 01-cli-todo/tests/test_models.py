"""Tests for the Todo model: validation, serialization, defaults."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from todo.models import Priority, Todo


def test_empty_title_rejected() -> None:
    """Whitespace-only titles must fail validation."""
    with pytest.raises(ValidationError):
        Todo(id=1, title="   ")


def test_defaults_applied() -> None:
    """Omitting optional fields yields sensible defaults."""
    todo = Todo(id=1, title="Buy groceries")
    assert todo.done is False
    assert todo.due is None
    assert todo.priority is Priority.MED
    assert todo.created_at is not None


def test_due_date_and_priority_roundtrip() -> None:
    """Explicit due/priority survive a dict round-trip."""
    todo = Todo(id=2, title="Ship", due=date(2026, 12, 31), priority=Priority.HIGH)
    restored = Todo.from_dict(todo.to_dict())
    assert restored == todo
    assert restored.due == date(2026, 12, 31)
    assert restored.priority is Priority.HIGH


def test_serialization_is_json_friendly() -> None:
    """to_dict() should produce only primitives (strings/dates iso)."""
    data = Todo(id=1, title="Test", due=date(2026, 1, 1)).to_dict()
    assert data["due"] == "2026-01-01"
    assert data["priority"] == "med"
    assert data["done"] is False


def test_priority_weight_ordering() -> None:
    """Priorities sort from low to high by weight."""
    assert Priority.LOW.weight < Priority.MED.weight < Priority.HIGH.weight