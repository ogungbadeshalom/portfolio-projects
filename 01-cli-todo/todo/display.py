"""Rendering utilities for the CLI Todo App.

Provides pretty table output built on Rich, and maps todo priorities to
human-friendly colored labels. This module knows nothing about how todos are
stored — it only knows how to draw them.
"""

from __future__ import annotations

from typing import Iterable, List

from rich.console import Console
from rich.table import Table

from .models import Priority, Todo

# Priority -> (label, style). Styles are Rich markup, used both as the cell
# text style and as the colour of the priority chip.
_PRIORITY_STYLE = {
    Priority.HIGH: ("HIGH", "bold red"),
    Priority.MED: ("MED", "bold yellow"),
    Priority.LOW: ("LOW", "bold cyan"),
}

STATUS_DONE = "[green]✔ done[/green]"
STATUS_OPEN = "[grey50]open[/grey50]"


def priority_label(priority: Priority) -> str:
    """Return the styled label for a priority.

    Args:
        priority: The priority to render.

    Returns:
        str: A Rich-formatted label, e.g. ``[bold red]HIGH[/bold red]``.
    """
    label, style = _PRIORITY_STYLE[priority]
    return f"[{style}]{label}[/{style}]"


def due_label(todo: Todo) -> str:
    """Return a formatted string for a todo's due date.

    Args:
        todo: The todo to render a due date for.

    Returns:
        str: The ``YYYY-MM-DD`` date or an em-dash when no date is set.
    """
    if todo.due is None:
        return "[dim]—[/dim]"
    return todo.due.isoformat()


def render_todos(todos: Iterable[Todo], console: Console) -> None:
    """Print a collection of todos as a Rich table.

    Args:
        todos: The todos to render.
        console: The Rich console to print to.
    """
    rows = sorted(todos, key=lambda t: (t.priority.weight, t.done))
    table = Table(title="Todos", show_lines=False, pad_edge=False)

    table.add_column("#", justify="right", style="dim", no_wrap=True)
    table.add_column("Title", style="bold")
    table.add_column("Status", no_wrap=True)
    table.add_column("Priority", justify="center", no_wrap=True)
    table.add_column("Due", justify="right", no_wrap=True)

    for todo in rows:
        status = STATUS_DONE if todo.done else STATUS_OPEN
        table.add_row(
            str(todo.id),
            todo.title,
            status,
            priority_label(todo.priority),
            due_label(todo),
        )

    console.print(table)


def render_summary(todos: List[Todo], console: Console) -> None:
    """Print a one-line summary of an empty list, if applicable.

    Args:
        todos: The collection to summarize.
        console: The Rich console to print to.
    """
    if not todos:
        console.print("[dim]No todos yet. Add one with:[/dim] todo add \"<task>\"")