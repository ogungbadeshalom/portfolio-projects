"""Entry point for ``python -m md2html``."""

from __future__ import annotations

from .cli import main


def run() -> None:
    """Invoke the Click CLI (no return value; exits the process on error)."""
    main()


if __name__ == "__main__":
    run()