"""Persistence layer for the CLI Todo App.

Handles reading and writing the todo collection as JSON, with *atomic*
writes: content is first written to a temp file in the same directory, then
moved over the real file with :func:`os.replace`. This guarantees readers
never observe a half-written file, even if the process crashes mid-save.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import List, Optional

from .models import SCHEMA_VERSION, Todo

# Env vars used to redirect where data lives. Useful for tests and for
# anyone who wants their todo file somewhere other than the home dir.
TODO_FILE_ENV = "TODO_FILE"
TODO_HOME_ENV = "TODO_HOME"


class TodoNotFoundError(LookupError):
    """Raised when a requested todo id does not exist."""


def default_todo_path() -> Path:
    """Resolve the path to the todo data file.

    Resolution order:
      1. ``$TODO_FILE`` if set (explicit full path).
      2. ``$TODO_HOME/.todo.json`` if ``$TODO_HOME`` is set.
      3. ``~/.todo.json`` otherwise.

    Returns:
        Path: The absolute path to the todo JSON file.
    """
    explicit = os.environ.get(TODO_FILE_ENV)
    if explicit:
        return Path(explicit).expanduser().resolve()

    home = os.environ.get(TODO_HOME_ENV)
    base = Path(home).expanduser() if home else Path.home()
    return (base / ".todo.json").resolve()


def load_todos(path: Optional[Path] = None) -> List[Todo]:
    """Load the todo list from disk.

    A missing file means "no todos yet" and returns an empty list rather than
    erroring. A malformed file also degrades gracefully instead of crashing
    the whole CLI.

    Args:
        path: Where to read from. Defaults to :func:`default_todo_path`.

    Returns:
        List[Todo]: The persisted todos, or an empty list if none exist.
    """
    path = path or default_todo_path()
    if not path.exists():
        return []

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        # TODO(usability): surface a clear warning instead of silently
        # ignoring a corrupt file. For now, degrade to empty.
        return []

    if not isinstance(raw, dict):
        return []

    items = raw.get("todos", [])
    if not isinstance(items, list):
        return []

    todos: List[Todo] = []
    for item in items:
        if isinstance(item, dict):
            todos.append(Todo.from_dict(item))
    return todos


def save_todos(todos: List[Todo], path: Optional[Path] = None) -> None:
    """Persist todos to disk using an atomic write.

    Writes to a temporary file, flushes it to disk, then atomically renames
    it over the target. If anything goes wrong the original file is left
    untouched.

    Args:
        todos: The list of todos to persist.
        path: Where to write. Defaults to :func:`default_todo_path`.

    Raises:
        OSError: If the write could not be completed.
    """
    path = path or default_todo_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "schema_version": SCHEMA_VERSION,
        "todos": [todo.to_dict() for todo in todos],
    }
    encoded = json.dumps(payload, indent=2) + "\n"

    fd, tmp_name = tempfile.mkstemp(
        prefix=".todo-", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, str(path))
    except Exception:
        # Best-effort cleanup of the temp file, then re-raise.
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _next_id(todos: List[Todo]) -> int:
    """Compute the next id to assign (max existing + 1).

    Args:
        todos: The current collection.

    Returns:
        int: The next id. Returns 1 for an empty collection.
    """
    if not todos:
        return 1
    return max(todo.id for todo in todos) + 1


def find_by_id(todos: List[Todo], todo_id: int) -> Todo:
    """Return the todo with the given id or raise a friendly error.

    Args:
        todos: The collection to search.
        todo_id: The id to look up.

    Returns:
        Todo: The matching todo.

    Raises:
        TodoNotFoundError: If no todo has ``todo_id``.
    """
    for todo in todos:
        if todo.id == todo_id:
            return todo
    raise TodoNotFoundError(f"Todo #{todo_id} not found")


def add_todo(todos: List[Todo], title: str, **kwargs: object) -> Todo:
    """Create a new todo and append it to the collection.

    Args:
        todos: The collection to append to (mutated in place).
        title: The todo title.
        **kwargs: Extra fields passed to :class:`~todo.models.Todo`.

    Returns:
        Todo: The newly created todo.
    """
    todo = Todo(id=_next_id(todos), title=title, **kwargs)
    todos.append(todo)
    return todo


def remove_todo(todos: List[Todo], todo_id: int) -> Todo:
    """Remove and return the todo with the given id.

    Args:
        todos: The collection to remove from (mutated in place).
        todo_id: The id to remove.

    Returns:
        Todo: The removed todo.

    Raises:
        TodoNotFoundError: If no todo has ``todo_id``.
    """
    todo = find_by_id(todos, todo_id)
    todos.remove(todo)
    return todo


def clear_done(todos: List[Todo]) -> int:
    """Remove every completed todo.

    Args:
        todos: The collection to prune (mutated in place).

    Returns:
        int: How many todos were removed.
    """
    before = len(todos)
    todos[:] = [todo for todo in todos if not todo.done]
    return before - len(todos)