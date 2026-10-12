"""Command-line interface for the Todo App.

Builds a small Typer app exposing ``add``, ``list``, ``done``, ``delete`` and
``clear``. Every command loads the persisted todos, performs its change (if
any), saves back through the atomic storage layer, and renders output via
Rich.

Errors are surfaced as friendly, colored messages — never raw tracebacks.
"""

from __future__ import annotations

from typing import List, Optional

import typer
from rich.console import Console
from rich.prompt import Confirm

from . import storage
from .models import Priority, Todo
from .display import render_todos

app = typer.Typer(
    name="todo",
    help="A tiny command-line todo manager that persists to ~/.todo.json.",
    add_completion=False,
)
console = Console()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _load() -> List[Todo]:
    """Load the todo collection from disk.

    Returns:
        List[Todo]: The persisted todos.
    """
    return storage.load_todos()


def _find(todos: List[Todo], todo_id: int) -> Todo:
    """Locate a todo by id or quit with a friendly message.

    Args:
        todos: The collection to search.
        todo_id: The id to look up.

    Returns:
        Todo: The matching todo.

    Raises:
        SystemExit: Via ``raise typer.Exit`` if the id is unknown, after
            printing an error.
    """
    try:
        return storage.find_by_id(todos, todo_id)
    except storage.TodoNotFoundError as exc:
        console.print(f"[bold red]{exc}[/bold red]")
        raise typer.Exit(code=1) from exc


def _parse_priority(value: str) -> Priority:
    """Map a CLI string to a Priority, validating the choice.

    Args:
        value: One of ``high``, ``med``, ``low``.

    Returns:
        Priority: The parsed priority.

    Raises:
        SystemExit: If the value is not a valid priority.
    """
    try:
        return Priority(value)
    except ValueError:
        choices = ", ".join(p.value for p in Priority)
        console.print(f"[bold red]Invalid priority '{value}' (choose from: {choices})[/bold red]")
        raise typer.Exit(code=1) from None


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
@app.command()
def add(
    title: str = typer.Argument(..., help="The task to remember."),
    due: Optional[str] = typer.Option(
        None, "--due", "-d", help="Optional due date, YYYY-MM-DD."
    ),
    priority: str = typer.Option(
        Priority.MED.value,
        "--priority",
        "-p",
        help="Priority: high, med, or low.",
        show_default=True,
    ),
) -> None:
    """Add a new todo item."""
    from datetime import date, datetime

    todos = _load()
    due_date = _parse_due(due)

    try:
        todo = storage.add_todo(
            todos, title, due=due_date, priority=_parse_priority(priority)
        )
    except Exception as exc:  # Pydantic validation errors
        console.print(f"[bold red]{exc}[/bold red]")
        raise typer.Exit(code=1) from exc

    storage.save_todos(todos)
    console.print(
        f"[green]✓ Added[/green] {priority_display(todo)} "
        f"'{todo.title}' as #[bold]{todo.id}[/bold]."
    )


@app.command("list")
def list_todos(
    all: bool = typer.Option(
        False, "--all", "-a", help="Show every todo (default)."
    ),
    pending: bool = typer.Option(
        False, "--pending", "-P", help="Show only open todos."
    ),
    done: bool = typer.Option(
        False, "--done", "-D", help="Show only completed todos."
    ),
) -> None:
    """List todos, optionally filtered by status.

    With no filter flag, shows all todos. Flags are mutually exclusive; if
    more than one is given the most specific one wins (done > pending > all).
    """
    todos = _load()
    render_todos(_filter_todos(todos, pending=pending, done=done), console)


def _filter_todos(todos: List[Todo], pending: bool, done: bool) -> List[Todo]:
    """Apply the ``--pending`` / ``--done`` filters to a collection.

    Args:
        todos: The full collection.
        pending: Whether to restrict to open items.
        done: Whether to restrict to completed items.

    Returns:
        List[Todo]: The filtered collection.
    """
    if done:
        return [t for t in todos if t.done]
    if pending:
        return [t for t in todos if not t.done]
    return todos


@app.command()
def done(
    todo_id: int = typer.Argument(..., help="The id of the todo to mark done."),
) -> None:
    """Mark a todo as completed."""
    todos = _load()
    todo = _find(todos, todo_id)
    todo.done = True
    storage.save_todos(todos)
    console.print(f"[green]✓[/green] Marked #{todo.id} '{todo.title}' as done.")


@app.command("delete")
def delete(
    todo_id: int = typer.Argument(..., help="The id of the todo to delete."),
) -> None:
    """Delete a todo."""
    todos = _load()
    _find(todos, todo_id)
    todo = storage.remove_todo(todos, todo_id)
    storage.save_todos(todos)
    console.print(f"[red]✗[/red] Deleted #{todo.id} '{todo.title}'.")


@app.command()
def clear(
    done: bool = typer.Option(
        False,
        "--done",
        help="Remove all completed todos. (This command only ever removes done items.)",
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip the confirmation prompt."
    ),
) -> None:
    """Clear completed todos."""
    todos = _load()
    if not done:
        console.print("[yellow]Use: todo clear --done[/yellow]")
        raise typer.Exit(code=1)

    completed = [t for t in todos if t.done]
    if not completed:
        console.print("[dim]Nothing to clear — no completed todos.[/dim]")
        return

    if not yes and not Confirm.ask(f"Delete {len(completed)} completed todo(s)?"):
        console.print("[dim]Aborted.[/dim]")
        return

    removed = storage.clear_done(todos)
    storage.save_todos(todos)
    console.print(f"[green]✓[/green] Removed {removed} completed todo(s).")


# ---------------------------------------------------------------------------
# Small parsing helpers (kept below to keep command bodies readable)
# ---------------------------------------------------------------------------
def _parse_due(raw: Optional[str]) -> Optional["date"]:
    """Parse a ``YYYY-MM-DD`` string into a date.

    Args:
        raw: The raw due date string, or None.

    Returns:
        Optional[date]: The parsed date, or None when ``raw`` is None.

    Raises:
        SystemExit: If the string is not a valid date.
    """
    if raw is None:
        return None
    from datetime import date

    try:
        return date.fromisoformat(raw)
    except ValueError:
        console.print(
            f"[bold red]Invalid due date '{raw}' — use YYYY-MM-DD.[/bold red]"
        )
        raise typer.Exit(code=1) from None


def priority_display(todo: Todo) -> str:
    """Produce a short priority token for success messages.

    Args:
        todo: The todo whose priority should be shown.

    Returns:
        str: A lower-cased priority label.
    """
    return todo.priority.value.upper()


if __name__ == "__main__":
    app()