"""md2html -- a Markdown to standalone-HTML converter.

Public library API::

    from md2html import convert
    html = convert("# Hello\\n\\n- one\\n- two", theme="dark")

Also ships a command-line tool, ``md2html``, reached either via ``python -m
md2html`` or an installed console script.
"""

from __future__ import annotations

from .converter import convert, MDIT_LOADED
from .config import Options
from .themes import THEME_NAMES

__version__ = "0.1.0"

__all__ = [
    "convert",
    "Options",
    "THEME_NAMES",
    "MDIT_LOADED",
    "__version__",
]