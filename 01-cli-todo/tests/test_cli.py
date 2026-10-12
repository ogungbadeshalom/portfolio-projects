"""End-to-end tests of the CLI using Typer's CliRunner.

The ``TODO_FILE`` env var (via the ``monkeypatch_todo_env`` fixture) points
storage at a temp file, so these tests never touch the user's real data.
"""

from __future__ import annotations

from todo import storage


def test_help_works(app, runner) -> None:
    """--help should parse and list the commands."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("add", "list", "done", "delete", "clear"):
        assert command in result.output


def test_add_and_list_roundtrip(app, runner, monkeypatch_todo_env: str) -> None:
    """Adding a task then listing it shows up in the table."""
    add_result = runner.invoke(app, ["add", "Buy groceries"])
    assert add_result.exit_code == 0
    assert "#1" in add_result.output

    list_result = runner.invoke(app, ["list"])
    assert list_result.exit_code == 0
    assert "Buy groceries" in list_result.output


def test_add_with_due_and_priority(app, runner, monkeypatch_todo_env: str) -> None:
    """--due and --priority flags are honored."""
    result = runner.invoke(
        app,
        ["add", "Ship", "--due", "2026-12-31", "--priority", "high"],
    )
    assert result.exit_code == 0
    stored = storage.load_todos()
    assert stored[0].priority.value == "high"
    assert stored[0].due.isoformat() == "2026-12-31"


def test_add_invalid_priority_errors(app, runner, monkeypatch_todo_env: str) -> None:
    """An unsupported priority produces a friendly error, not a crash."""
    result = runner.invoke(app, ["add", "X", "--priority", "urgent"])
    assert result.exit_code == 1
    assert "Invalid priority" in result.output


def test_add_invalid_due_errors(app, runner, monkeypatch_todo_env: str) -> None:
    """A malformed due date produces a friendly error."""
    result = runner.invoke(app, ["add", "X", "--due", "not-a-date"])
    assert result.exit_code == 1
    assert "Invalid due date" in result.output


def test_done_marks_completed(app, runner, monkeypatch_todo_env: str) -> None:
    """Running `done 1` marks the first todo complete."""
    runner.invoke(app, ["add", "Task one"])
    result = runner.invoke(app, ["done", "1"])
    assert result.exit_code == 0

    stored = storage.load_todos()
    assert stored[0].done is True


def test_done_missing_todo_errors(app, runner, monkeypatch_todo_env: str) -> None:
    """Marking an unknown id as done prints a friendly message."""
    result = runner.invoke(app, ["done", "99"])
    assert result.exit_code == 1
    assert "Todo #99 not found" in result.output


def test_delete_removes_todo(app, runner, monkeypatch_todo_env: str) -> None:
    """Deleting by id removes the todo and it no longer lists."""
    runner.invoke(app, ["add", "Temp"])
    result = runner.invoke(app, ["delete", "1"])
    assert result.exit_code == 0
    assert storage.load_todos() == []


def test_list_pending_filters_out_done(app, runner, monkeypatch_todo_env: str) -> None:
    """--pending should hide completed items."""
    runner.invoke(app, ["add", "buy-milk"])
    runner.invoke(app, ["add", "pay-bills"])
    runner.invoke(app, ["done", "1"])

    result = runner.invoke(app, ["list", "--pending"])
    assert "buy-milk" not in result.output
    assert "pay-bills" in result.output


def test_list_done_only_shows_done(app, runner, monkeypatch_todo_env: str) -> None:
    """--done should show only completed items."""
    runner.invoke(app, ["add", "a"])
    runner.invoke(app, ["done", "1"])
    result = runner.invoke(app, ["list", "--done"])
    assert "a" in result.output


def test_clear_done_requires_flag(app, runner, monkeypatch_todo_env: str) -> None:
    """`clear` without --done should refuse and hint at the flag."""
    runner.invoke(app, ["add", "a"])
    result = runner.invoke(app, ["clear"])
    assert result.exit_code == 1
    assert "--done" in result.output


def test_clear_done_removes_completed_only(app, runner, monkeypatch_todo_env: str) -> None:
    """`clear --done --yes` removes done items but keeps open ones."""
    runner.invoke(app, ["add", "keep me"])
    runner.invoke(app, ["add", "drop me"])
    runner.invoke(app, ["done", "2"])

    result = runner.invoke(app, ["clear", "--done", "--yes"])
    assert result.exit_code == 0

    titles = [t.title for t in storage.load_todos()]
    assert titles == ["keep me"]


def test_add_blank_title_errors(app, runner, monkeypatch_todo_env: str) -> None:
    """A whitespace-only title is rejected with a message."""
    result = runner.invoke(app, ["add", "   "])
    assert result.exit_code == 1