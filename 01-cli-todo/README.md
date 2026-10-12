# CLI Todo App

A small, portfolio-ready command-line todo manager written in Python.

Built with **Typer** for the CLI, **Rich** for pretty terminal output, and
**Pydantic** for validated data models. Todos persist to `~/.todo.json`
using atomic writes — a temp file plus `os.replace` — so your data is never
left half-written.

## Features

- `add` tasks with an optional due date and priority (`high` / `med` / `low`)
- `list` with `--all`, `--pending`, or `--done` filters, rendered as a
  color-coded Rich table
- `done` / `delete` by 1-indexed id
- `clear --done` to remove completed items
- Friendly errors (`Todo #5 not found`) — never raw stack traces
- Persists to `~/.todo.json` (override via `TODO_FILE` or `TODO_HOME`)

## Install

Requires Python 3.10+. From the project root:

```bash
pip install -e .
```

This installs a `todo` command on your PATH. To install with the dev/test
dependencies as well:

```bash
pip install -e ".[dev]"
```

## Usage

```bash
# Add tasks
todo add "Buy groceries"
todo add "Ship v1.0" --due 2026-12-31 --priority high

# List
todo list              # all
todo list --pending    # open items only
todo list --done       # completed items only

# Manage
todo done 1            # mark #1 complete
todo delete 2          # remove #2
todo clear --done      # remove completed items (asks for confirmation)

# Help
todo --help
todo add --help
```

### Examples

```
$ todo add "Write blog post" --priority high
✓ Added HIGH 'Write blog post' as #1.

$ todo list
        Todos
┏━━━┳━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━┓
┃   #┃ Title          ┃ Status ┃ Priority ┃         Due ┃
┡━━━╇━━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━┩
│   1│ Write blog post│ open   │ HIGH    │          —   │
│   2│ Buy groceries  │ open   │ MED     │ 2026-12-31  │
└───┴────────────────┴────────┴─────────┴──────────────┘
```

## Data storage

Todos live in `~/.todo.json`. Each write is atomic. To keep your data
elsewhere (e.g. for tests or to sync a portable file):

```bash
export TODO_FILE=/path/to/my-todos.json
# or
export TODO_HOME=/some/dir        # → $TODO_HOME/.todo.json
```

## Development

Run the test suite:

```bash
pytest tests/ -v --tb=short
```

Tests use `typer.testing.CliRunner` and redirect storage to a temporary file
via the `TODO_FILE` environment variable, so they never touch your real data.

### Project layout

```
todo/
├── todo/
│   ├── __init__.py      # package metadata
│   ├── __main__.py      # python -m todo entry point
│   ├── cli.py           # Typer commands (add/list/done/delete/clear)
│   ├── models.py        # validated Todo model + Priority enum
│   ├── storage.py       # atomic JSON load/save, id helpers
│   └── display.py       # Rich table rendering, priority colors
├── tests/               # pytest + CliRunner suite
├── pyproject.toml       # packaging + console script
├── README.md
└── CLAUDE.md
```

## Roadmap / Stretch goals

- `--tag` flag for categorizing tasks
- `search` command with fuzzy matching
- `export` to CSV or Markdown
- Shell completion generation (`todo completion bash`)