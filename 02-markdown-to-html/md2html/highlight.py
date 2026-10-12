"""Token-based syntax highlighting for fenced code blocks.

``highlight()`` is the only public entry point. It prefers Pygments when it
is installed and silently falls back to a plain ``<pre>`` renderer when it is
not, so the tool keeps working in a bare environment.

Token spans are emitted as ``<span class="tok-...">`` and the matching
Pygments stylesheet is scoped with the same ``tok-`` prefix so the embedded
theme CSS can style them. ``pygments_css()`` returns that stylesheet.
"""

from __future__ import annotations

import html

try:  # Pygments is optional but recommended.
    from pygments import highlight as _pygments_highlight
    from pygments.formatters import HtmlFormatter
    from pygments.lexers import get_lexer_by_name
    from pygments.util import ClassNotFound
except ImportError:  # pragma: no cover - exercised only without Pygments.
    _pygments_highlight = None
    HtmlFormatter = None  # type: ignore[assignment]
    get_lexer_by_name = None  # type: ignore[assignment]
    ClassNotFound = None  # type: ignore[misc]

__all__ = ["highlight", "pygments_css", "PYGMENTS_LOADED"]

PYGMENTS_LOADED = _pygments_highlight is not None


def _highlight_pygments(code: str, language: str) -> str:
    """Highlight ``code`` with Pygments into ``tok-`` prefixed spans.

    ``nowrap`` keeps every token on a single output line and avoids the extra
    ``<div class="highlight">`` wrapper, so the result slots directly into a
    ``<pre>`` element.
    """
    assert _pygments_highlight is not None and get_lexer_by_name is not None
    try:
        lexer = get_lexer_by_name(language)
    except ClassNotFound:
        # Unknown or empty language: Pygments's "text" lexer is a sane default
        # that still recognises a few common constructs.
        from pygments.lexers.text import TextLexer

        lexer = TextLexer()
    formatter = HtmlFormatter(nowrap=True, classprefix="tok-")
    return _pygments_highlight(code, lexer, formatter)


def _highlight_plain(code: str, language: str) -> str:
    """Escape ``code`` and emit a single token span.

    Used when Pygments is unavailable. Keeps the markup shape compatible with
    the Pygments path so a theme's ``.tok-code`` rule applies either way.
    """
    return '<span class="tok-code">' + html.escape(code) + "</span>"


_impl = _highlight_pygments if PYGMENTS_LOADED else _highlight_plain


def highlight(code: str, language: str = "") -> str:
    """Return syntax-highlighted inline HTML for ``code``.

    Args:
        code: The raw source text of a code block.
        language: Optional lexer name (``python``, ``json``, ``shell``, ...).
            Empty or unknown languages degrade to plain text.

    Returns:
        A ``<span>``-wrapped HTML fragment safe to embed inside ``<pre>``.
    """
    return _impl(code, language)


def pygments_css(theme: str) -> str:
    """Return the Pygments stylesheet for ``theme`` scoped to ``.tok``.

    Args:
        theme: A Pygments style name (e.g. ``default``, ``monokai``, ``xcode``).

    Returns:
        The generated CSS, or an empty string when Pygments is unavailable
        (the static theme CSS already styles ``.tok-code``).
    """
    if not PYGMENTS_LOADED or HtmlFormatter is None or theme == "plain":
        return ""
    return HtmlFormatter(nowrap=True, style=theme, classprefix="tok-").get_style_defs(
        ".md2html .highlight"
    )