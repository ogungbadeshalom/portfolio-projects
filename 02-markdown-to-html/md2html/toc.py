"""Table of contents generation.

``build_toc()`` scans already-rendered body HTML for ``<h1>``..``<h4>`` tags that
carry an ``id`` attribute (both backends emit those) and builds a nested
``<details>`` list of anchored links. An empty string is returned when the
document has no headings.
"""

from __future__ import annotations

import html
import re
from typing import List, Tuple

__all__ = ["extract_headings", "build_toc"]

_HEADING_RE = re.compile(r"<h([1-4])\s+id=\"([^\"]*)\"[^>]*>(.*?)</h\1>", re.S)
_TAG_RE = re.compile(r"<[^>]+>")


def extract_headings(body_html: str) -> List[Tuple[int, str, str]]:
    """Extract ``(level, anchor, text)`` tuples for headings in ``body_html``.

    Args:
        body_html: The rendered HTML body or document fragment.

    Returns:
        An ordered list of ``(level, id, plain_text)`` tuples. Heading text is
        stripped of inner tags, so bold runs render correctly in the TOC.
    """
    found: List[Tuple[int, str, str]] = []
    for m in _HEADING_RE.finditer(body_html):
        level = int(m.group(1))
        anchor = html.unescape(m.group(2))
        text = _TAG_RE.sub("", m.group(3))
        text = html.unescape(text).strip()
        found.append((level, anchor, text))
    return found


def _list_html(entries: List[Tuple[int, str, str]], index: int = 0) -> Tuple[str, int]:
    """Recursively render nested ``<ul>`` markup for entries from ``index``."""
    if index >= len(entries):
        return "", index

    base = entries[index][0]
    items: List[str] = []
    i = index
    while i < len(entries):
        level, anchor, text = entries[i]
        if level < base:
            break
        li = f'<li><a href="#{html.escape(anchor, quote=True)}">{html.escape(text)}</a>'
        # Collect any deeper headings inside this entry as a nested list.
        if i + 1 < len(entries) and entries[i + 1][0] > level:
            child_html, i = _list_html(entries, i + 1)
            # Only indent one level relative to the current entry.
            child_html = child_html.replace("<ul>", '<ul class="toc-sub">', 1)
            li += child_html
        li += "</li>"
        items.append(li)
        i += 1
    return "<ul>" + "".join(items) + "</ul>", i


def build_toc(body_html: str) -> str:
    """Build the table-of-contents HTML for a rendered document.

    Args:
        body_html: Rendered body HTML (headings must carry ``id`` anchors).

    Returns:
        A ``<details class="toc">`` block, or ``""`` if there are no headings.
    """
    headings = extract_headings(body_html)
    if not headings:
        return ""
    inner, _ = _list_html(headings)
    return (
        '<details class="toc">'
        "<summary>Table of Contents</summary>"
        f"{inner}"
        "</details>\n"
    )