# CLI Todo App — Python

## Project Title
CLI Todo App (Python)

## Goal
Build a clean, fast command-line todo app. Add tasks, list them, mark done, delete. Persist to a JSON file in your home directory.

## Why this project
Forces you to nail: argparse (or typer), JSON serialization, atomic file writes, basic CLI UX. Every serious tool starts here.

## What You Build
A `todo` command you can run from anywhere.

```
todo add "Buy groceries"
todo list
todo done 3
todo delete 5
todo clear --done
```

Should support:
- Add with optional `--due YYYY-MM-DD` and `--priority high|med|low`
- List with `--all`, `--pending`, `--done` filters
- Done by ID (1-indexed)
- Delete by ID
- Clear completed items
- Pretty-printed table output (use `rich` if Python, `text/tabwriter` if Go)

## Tech
- **Python 3.11+** with **Typer** (modern CLI library, cleaner than argparse)
- **Rich** for pretty tables and colors
- **JSON file** at `~/.todo.json` for persistence (atomic writes via temp file + rename)
- No external dependencies beyond typer and rich

## Architecture

```
todo/
├── todo/
│   ├── __init__.py
│   ├── __main__.py        # entry point: python -m todo
│   ├── cli.py              # Typer commands
│   ├── storage.py          # JSON read/write with atomic save
│   ├── models.py           # Todo dataclass
│   └── display.py          # Rich tables
├── tests/
│   ├── test_storage.py
│   ├── test_models.py
│   └── test_cli.py
├── pyproject.toml
├── README.md
└── CLAUDE.md
```

## Build Order

1. **`models.py`** — Todo dataclass with id, title, due, priority, done, created_at
2. **`storage.py`** — `load_todos()`, `save_todos()` with atomic file writes (write to .tmp, then rename)
3. **`cli.py`** — Typer app with `add`, `list`, `done`, `delete`, `clear` commands
4. **`display.py`** — Rich table rendering with color coding by priority
5. **`__main__.py`** — Entry point
6. **Tests** — pytest for storage + models + CLI (use `typer.testing.CliRunner`)
7. **README** — Installation, usage examples, screenshots

## Requirements

- Python 3.11+
- All dependencies in `pyproject.toml`
- Tests pass: `pytest tests/ -v`
- Type hints on all functions
- Use Pydantic or dataclasses for Todo model (with validation)
- Atomic file writes (write to temp + os.replace, never partial writes)
- Pretty error messages ("Todo #5 not found", not stack traces)
- Help text via `--help` on every command

## Code Standards

- Type hints everywhere (use `from __future__ import annotations`)
- Docstrings on all public functions (Google style)
- 4-space indentation
- Use `pathlib.Path` not `os.path`
- Error handling: catch specific exceptions, log clearly

## Verification

```bash
# Install
pip install -e .

# Run tests
pytest tests/ -v --tb=short

# Try it
todo add "Write CLAUDE.md for project 02"
todo list
todo done 1
todo list --pending
```

All commands should work, JSON file at `~/.todo.json` should persist between sessions.

## Stretch Goals (Optional)

- Add `--tag` flag for categorization
- Add `search` command with fuzzy matching
- Add `export` to CSV/markdown
- Add shell completion script generation (`todo completion bash > /etc/bash_completion.d/todo`)
- Add config file at `~/.config/todo/config.toml`
- Add SQLite backend option alongside JSON

## What You'll Learn

- Typer for modern Python CLIs
- Rich for pretty terminal output
- Atomic file persistence
- Click-style argument handling
- Testing CLI apps with `typer.testing.CliRunner`

## Time Estimate
2-4 hours for a clean version. 6-8 hours with tests + polish.