"""A tiny, portfolio-ready static Markdown blog generator.

The :mod:`blog` package turns a folder of Markdown posts into a complete
static site:

* HTML pages for the home page, individual posts and tag indexes,
* RSS 2.0 and Atom 1.0 feeds,
* a sitemap and robots.txt,
* syntax-highlighted code blocks and a CSS-only dark-mode toggle.

It favours ``markdown-it-py`` + ``Jinja2`` + ``Pygments`` + ``Pillow`` when
those libraries are installed, but ships pragmatic built-in fallbacks so that
``blog build`` still completes on a minimal Python 3.10 install.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "1.0.0"