"""Tests for the atomic storage layer."""

from __future__ import annotations

from pathlib import Path

import pytest

from todo import storage
from todo.models import Priority, Todo
from todo.storage import TodoNotFoundError


def _seed(path: str, *todos: Todo) -> None:
    """Write some todos to the given path via the storage layer."""
    storage.save_todos(list(todos), Path(path))


def test_load_missing_file_returns_empty(todo_path: str) -> None:
    """A missing file should yield an empty list, not an error."""
    assert storage.load_todos(Path(todo_path)) == []


def test_save_then_load_roundtrip(todo_path: str) -> None:
    """Todos written via save_todos survive load_todos intact."""
    todos = [
        Todo(id=1, title="First"),
        Todo(id=2, title="Second", priority=Priority.HIGH),
    ]
    _seed(todo_path, *todos)

    loaded = storage.load_todos(Path(todo_path))
    assert [t.title for t in loaded] == ["First", "Second"]
    assert loaded[1].priority is Priority.HIGH


def test_add_assigns_incrementing_ids(todo_path: str) -> None:
    """add_todo picks max existing id + 1."""
    todos = [Todo(id=3, title="Existing")]
    new = storage.add_todo(todos, "A new one")
    assert new.id == 4
    assert len(todos) == 2


def test_add_to_empty_starts_at_one(todo_path: str) -> None:
    """The very first todo gets id 1."""
    todos: list[Todo] = []
    new = storage.add_todo(todos, "First ever")
    assert new.id == 1


def test_find_by_id_missing_raises_friendly(todo_path: str) -> None:
    """Lookup for an unknown id raises a friendly error."""
    with pytest.raises(TodoNotFoundError, match="Todo #5 not found"):
        storage.find_by_id([Todo(id=1, title="Only")], 5)


def test_remove_by_id(todo_path: str) -> None:
    """remove_todo deletes the matching todo and returns it."""
    removed = storage.remove_todo([Todo(id=2, title="Gone")], 2)
    assert removed.title == "Gone"


def test_clear_done_only_removes_completed(todo_path: str) -> None:
    """clear_done prunes done items but keeps open ones."""
    todos = [
        Todo(id=1, title="Open"),
        Todo(id=2, title="Closed", done=True),
        Todo(id=3, title="Also open"),
    ]
    removed = storage.clear_done(todos)
    assert removed == 1
    assert [t.title for t in todos] == ["Open", "Also open"]


def test_corrupt_file_degrades_to_empty(todo_path: str) -> None:
    """Malformed JSON should yield [] rather than blowing up the CLI."""
    path = Path(todo_path)
    path.write_text("this is { not json", encoding="utf-8")
    assert storage.load_todos(path) == []


def test_default_path_respects_todo_home(monkeypatch, tmp_path) -> None:
    """TODO_HOME overrides the home dir for the todo file."""
    monkeypatch.delenv("TODO_FILE", raising=False)
    monkeypatch.setenv("TODO_HOME", str(tmp_path))
    assert storage.default_todo_path() == (tmp_path / ".todo.json").resolve()
    assert storage.default_todo_path().exists() is False