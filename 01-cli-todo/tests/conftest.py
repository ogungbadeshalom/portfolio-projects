"""Shared pytest fixtures.

The key fixture, ``todo_path``, points persistence at a temporary file so
tests never touch the real ``~/.todo.json``. The CLI reads the override from
the ``TODO_FILE`` environment variable, which is set scoped to each test.
"""

from __future__ import annotations

from typing import Iterator

import pytest
import typer
from typer.testing import CliRunner


@pytest.fixture()
def todo_path(tmp_path) -> str:
    """Return a temp file path the tests should use for storage.

    Returns:
        str: Absolute path to a non-existent file inside a tmp dir.
    """
    return str(tmp_path / "todos.json")


@pytest.fixture()
def monkeypatch_todo_env(monkeypatch, todo_path: str) -> Iterator[str]:
    """Point ``TODO_FILE`` at the temp path for the duration of a test.

    Yields:
        str: The temp path, for convenience in assertions.
    """
    monkeypatch.setenv("TODO_FILE", todo_path)
    yield todo_path


@pytest.fixture()
def runner() -> CliRunner:
    """Return a fresh isolated Typer test runner.

    Returns:
        CliRunner: A runner that captures clean result objects.
    """
    return CliRunner()


@pytest.fixture()
def app() -> typer.Typer:
    """Return the Typer application under test.

    Returns:
        typer.Typer: The ``cli.app`` application instance.
    """
    from todo import cli

    return cli.app