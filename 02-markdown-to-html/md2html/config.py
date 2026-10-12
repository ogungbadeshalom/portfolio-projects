"""Pydantic settings model for convert/build options.

``Options`` validates the subset of CLI flags that feed straight into
``convert()`` and the document assembly step. It is intentionally small; the
CLI owns orchestration, and the model keeps the shared knobs typed and
validated regardless of which frontend (CLI or library) sets them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

try:
    from pydantic import BaseModel, Field, ValidationError, field_validator

    _PYDANTIC_LOADED = True
except ImportError:  # pragma: no cover - exercised only without pydantic
    _PYDANTIC_LOADED = False
    BaseModel = object  # type: ignore[misc, assignment]
    Field = None  # type: ignore[assignment]
    field_validator = None  # type: ignore[assignment]

    class ValidationError(Exception):  # type: ignore[no-redef]
        """Minimal stand-in so ``Options`` still validates theme names."""

from .themes import THEME_NAMES

__all__ = ["Options", "validate_theme", "PYDANTIC_LOADED"]

PYDANTIC_LOADED = _PYDANTIC_LOADED

_VALID_THEMES = sorted(THEME_NAMES)


def validate_theme(theme: str) -> str:
    """Return ``theme`` if valid, else raise ``ValueError`` with guidance."""
    clean = theme.strip().lower()
    if clean not in THEME_NAMES:
        raise ValueError(
            f"Unknown theme {theme!r}. Choose from {', '.join(_VALID_THEMES)}."
        )
    return clean


if _PYDANTIC_LOADED:

    class Options(BaseModel):  # type: ignore[misc, valid-type]
        """Validated options for a single conversion job."""

        theme: str = Field(default="light", description="CSS theme name.")
        toc: bool = Field(default=False, description="Embed a table of contents.")
        out_dir: Optional[Path] = Field(
            default=None, description="Directory to write generated files into."
        )

        @field_validator("theme")
        @classmethod
        def _theme_must_be_known(cls, value: str) -> str:
            return validate_theme(value)

else:  # pragma: no cover - exercised only without pydantic

    class Options:  # type: ignore[no-redef]
        """Pydantic-less fallback that keeps the same surface area."""

        def __init__(
            self,
            theme: str = "light",
            toc: bool = False,
            out_dir: Optional[Path] = None,
        ) -> None:
            self.theme = validate_theme(theme)
            self.toc = toc
            self.out_dir = out_dir