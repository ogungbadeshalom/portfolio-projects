"""Markdown -> HTML conversion core.

``convert()`` is the public entry point exposed as ``md2html.convert``.

Two Markdown backends are supported and chosen at import time:

* **markdown-it-py** (primary) -- a full CommonMark + GFM parser with official
  plugins (tables, strikethrough, task lists). Used automatically when the
  package is installed.
* **built-in fallback** (pragmatic) -- a small self-contained renderer covering
  the common GFM subset (headings, emphasis, lists, task lists, fenced code,
  links, images, tables, blockquotes and rules). Used when markdown-it-py is
  unavailable so the tool still works standalone.

Both backends produce a complete, standalone HTML document with the selected
theme's CSS embedded, so the rendered output needs no network access.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .highlight import highlight, pygments_css
from .themes import THEME_NAMES, build_css
from .toc import build_toc

# --- Primary backend availability ------------------------------------------- #
try:
    from markdown_it import MarkdownIt
    from mdit_py_plugins.tasklists import tasklists_plugin

    MDIT_LOADED = True
except ImportError:  # pragma: no cover - only exercised without markdown-it-py
    MDIT_LOADED = False

__all__ = ["convert", "MDIT_LOADED"]


# =========================================================================== #
# markdown-it-py backend
# =========================================================================== #
def _mdit_render(text: str, theme: str) -> str:
    """Render Markdown with markdown-it-py and wrap it in a document."""
    md = (
        MarkdownIt("commonmark", {"html": True, "linkify": True})
        .enable("table")
        .enable("strikethrough")
        .enable("fence")
    )
    md.use(tasklists_plugin)
    body = md.render(text)
    return _assemble_document(body, theme)


# =========================================================================== #
# Fallback AST
# =========================================================================== #
@dataclass
class Block:
    """A node in the lightweight fallback AST."""

    kind: str
    text: str = ""
    level: int = 0
    checked: Optional[bool] = None
    children: List["Block"] = field(default_factory=list)


@dataclass
class ListItem:
    """A parsed list item (before it becomes a :class:`Block`)."""

    text: str
    ordered: bool
    checked: Optional[bool] = None
    nested_blocks: List[Block] = field(default_factory=list)


# =========================================================================== #
# Inline parsing
# =========================================================================== #
def _inline(text: str) -> str:
    """Convert inline Markdown to HTML.

    Handles escapes (``\\*``), code spans (`` `x` ``), images (``![alt](url)``),
    links (``[label](url)``), bold (``**x**`` / ``__x__``), emphasis
    (``*x*`` / ``_x_``), and strikethrough (``~~x~~``) with correct nesting.
    Everything else is HTML-escaped.
    """
    out: List[str] = []
    buf: List[str] = []
    i, n = 0, len(text)

    def flush() -> None:
        if buf:
            out.append(html.escape("".join(buf)))
            buf.clear()

    while i < n:
        ch = text[i]
        # Escapes
        if ch == "\\" and i + 1 < n:
            buf.append(text[i + 1])
            i += 2
            continue
        # Code spans
        if ch == "`":
            j = i + 1
            while j < n and text[j] == "`":
                j += 1
            ticks = text[i:j]
            end = text.find(ticks, j)
            if end != -1:
                flush()
                out.append("<code>" + html.escape(text[j:end]) + "</code>")
                i = end + len(ticks)
                continue
            buf.append(ticks)
            i = j
            continue
        # Images
        if ch == "!" and text[i + 1 : i + 2] == "[":
            nxt, frag = _try_linklike(text, i + 1, img=True)
            if frag is not None:
                flush()
                out.append(frag)
                i = nxt
                continue
        # Links
        if ch == "[":
            nxt, frag = _try_linklike(text, i, img=False)
            if frag is not None:
                flush()
                out.append(frag)
                i = nxt
                continue
        # Bold: **...** or __...__
        marker = "**" if text[i : i + 2] == "**" else ("__" if text[i : i + 2] == "__" else None)
        if marker is not None:
            end = text.find(marker, i + 2)
            if end != -1:
                flush()
                out.append("<strong>" + _inline(text[i + 2 : end]) + "</strong>")
                i = end + 2
                continue
            buf.append(marker)
            i += 2
            continue
        # Strikethrough: ~~...~~
        if ch == "~" and text[i : i + 2] == "~~":
            end = text.find("~~", i + 2)
            if end != -1:
                flush()
                out.append("<del>" + _inline(text[i + 2 : end]) + "</del>")
                i = end + 2
                continue
        # Emphasis: *...* or _...
        if ch == "*" or ch == "_":
            end = text.find(ch, i + 1)
            if end != -1:
                flush()
                out.append("<em>" + _inline(text[i + 1 : end]) + "</em>")
                i = end + 1
                continue
        buf.append(ch)
        i += 1
    flush()
    return "".join(out)


def _try_linklike(
    text: str, start: int, img: bool
) -> Tuple[int, Optional[str]]:
    """Try to parse a link or image at ``start``.

    Returns ``(next_index, fragment)`` on success or ``(start, None)`` when the
    text at ``start`` is not a well-formed ``[label](target)`` construction.
    """
    j = text.find("]", start + 1)
    if j == -1 or j + 1 >= len(text) or text[j + 1] != "(":
        return start, None
    rp = text.find(")", j + 1)
    if rp == -1 or rp < j:
        return start, None
    label = text[start + 1 : j]
    target = text[j + 2 : rp].strip()
    title = ""
    if " " in target:
        target, _, title = target.partition(" ")
    href = target.strip("<>\"'")
    title_attr = (
        f' title="{html.escape(title.strip("\"'"), quote=True)}"' if title.strip() else ""
    )
    esc_href = html.escape(href, quote=True)
    if img:
        return rp + 1, f'<img src="{esc_href}" alt="{html.escape(label, quote=True)}">'
    inner = _inline(label)
    return rp + 1, f'<a href="{esc_href}"{title_attr}>{inner}</a>'


# =========================================================================== #
# Block parsing (fallback backend)
# =========================================================================== #
def _split(text: str) -> List[str]:
    """Normalise line endings and split into lines."""
    return text.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _is_list_item(line: str) -> bool:
    return bool(re.match(r"^\s*(?:[-*+]|\d+\.)\s+", line))


def _parse_blocks(lines: List[str]) -> List[Block]:
    """Parse source lines into the fallback block AST."""
    blocks: List[Block] = []
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
            continue
        # Fenced code block
        m = re.match(r"^(```+|~~~+)\s*([^\s`]*)\s*$", line)
        if m:
            fence, lang = m.group(1), m.group(2)
            buf: List[str] = []
            j = i + 1
            while j < n and not lines[j].startswith(fence):
                buf.append(lines[j])
                j += 1
            blocks.append(Block("code", text="\n".join(buf), level=lang))
            i = j + 1
            continue
        # ATX headings
        m = re.match(r"^(#{1,4})\s+(.*?)\s*#*\s*$", line)
        if m:
            blocks.append(
                Block("heading", text=m.group(2), level=len(m.group(1)))
            )
            i += 1
            continue
        # Setext headings
        if i + 1 < n and re.match(r"^={3,}\s*$", lines[i + 1]):
            blocks.append(Block("heading", text=stripped, level=1))
            i += 2
            continue
        if i + 1 < n and re.match(r"^-{3,}\s*$", lines[i + 1]):
            # A lone `---` directly under a paragraph is a Setext h2 unless the
            # line is itself a divider; treat a bare paragraph + `---` as h2.
            blocks.append(Block("heading", text=stripped, level=2))
            i += 2
            continue
        # Horizontal rule
        if re.match(r"^\s*(?:-\s*){3,}$", stripped) or re.match(
            r"^\s*(?:\*\s*){3,}$", stripped
        ):
            blocks.append(Block("hr"))
            i += 1
            continue
        # Blockquote
        if stripped.startswith(">"):
            quote_lines: List[str] = []
            while i < n and (lines[i].strip().startswith(">") or not lines[i].strip()):
                if lines[i].strip().startswith(">"):
                    quote_lines.append(lines[i].lstrip()[1:].lstrip())
                i += 1
            inner = "\n".join(quote_lines)
            blocks.append(
                Block("blockquote", children=_parse_blocks(_split(inner)))
            )
            continue
        # Lists
        if _is_list_item(line):
            items, i = _parse_list(lines, i)
            ordered = items[0].ordered if items else False
            blocks.append(
                Block(
                    "list",
                    level=1 if ordered else 0,
                    children=[_list_item_block(it) for it in items],
                )
            )
            continue
        # Tables
        if _is_table(lines, i):
            blocks.append(_parse_table(lines, i))
            i = _table_body_end(lines, i)
            continue
        # Paragraph (possibly multi-line)
        para: List[str] = []
        while i < n and lines[i].strip() and not _starts_new_block(lines[i]):
            if not _is_table(lines, i):
                para.append(lines[i].strip())
            else:
                break
            i += 1
        if para:
            blocks.append(Block("para", text=" ".join(para)))
    return blocks


def _starts_new_block(line: str) -> bool:
    """Return True if ``line`` begins a new block-level element."""
    s = line.strip()
    return bool(
        re.match(r"^#{1,4}\s+", s)
        or re.match(r"^(```+|~~~+)", s)
        or _is_list_item(s)
        or s.startswith(">")
        or re.match(r"^\s*(?:-\s*){3,}$", s)
        or re.match(r"^\s*(?:\*\s*){3,}$", s)
    )


def _parse_list(lines: List[str], start: int) -> Tuple[List[ListItem], int]:
    """Parse a list (flat-scan flavour) starting at ``start``.

    Returns the parsed items and the index of the first line after the list.
    Nested lists and lazy paragraph continuations are captured as blocks.
    """
    ordered = bool(re.match(r"^\s*\d+\.\s+", lines[start]))
    base = _indent_of(lines[start])
    items: List[ListItem] = []
    i, n = start, len(lines)

    def list_item_pattern():
        return r"^\s*(?:[-*+]|\d+\.)\s+(.*)$"

    while i < n:
        line = lines[i]
        if not line.strip():
            break
        m = re.match(list_item_pattern(), line)
        if not m:
            break
        marker_ordered = re.match(r"^\s*\d+\.\s+", line) is not None
        if marker_ordered != ordered:
            break
        content = m.group(1)
        checked: Optional[bool] = None
        tm = re.match(r"^\[([ xX])\]\s+(.*)$", content)
        if tm:
            checked = tm.group(1).lower() == "x"
            content = tm.group(2)
        item = ListItem(text=content, ordered=ordered, checked=checked)
        items.append(item)
        i += 1
        # Gather continuation lines (indented deeper than the item marker).
        cont: List[str] = []
        while i < n:
            l2 = lines[i]
            if not l2.strip():
                # A blank ends continuation unless the following line is a
                # deeper list item that belongs to this item.
                if i + 1 < n and _is_list_item(lines[i + 1]) and _indent_of(lines[i + 1]) > base:
                    i += 1
                    continue
                break
            if _indent_of(l2) > base:
                cont.append(l2.lstrip(" "))
                i += 1
                continue
            break
        while cont and not cont[-1].strip():
            cont.pop()
        if cont:
            if _is_list_item(cont[0]):
                sub_items, _ = _parse_list(cont, 0)
                item.nested_blocks.append(
                    Block(
                        "list",
                        level=1 if (sub_items and sub_items[0].ordered) else 0,
                        children=[_list_item_block(si) for si in sub_items],
                    )
                )
            elif _is_table(cont, 0):
                item.nested_blocks.append(_parse_table(cont, 0))
            else:
                item.nested_blocks.append(
                    Block("para", text=" ".join(x.strip() for x in cont))
                )
    return items, i


def _list_item_block(item: ListItem) -> Block:
    """Convert a :class:`ListItem` into a renderable item block."""
    block = Block("item", text=item.text, checked=item.checked)
    block.children = list(item.nested_blocks)
    return block


# --- Tables ---------------------------------------------------------------- #
def _is_table(lines: List[str], i: int) -> bool:
    if i + 1 >= len(lines):
        return False
    sep = lines[i + 1].strip()
    return (
        "|" in sep
        and "-" in sep
        and re.match(r"^\s*\|?[\s:|+│-]+-[\s:|+-]*\|?\s*$", sep) is not None
    )


def _table_body_end(lines: List[str], start: int) -> int:
    i = start
    n = len(lines)
    while i < n and lines[i].strip() and "|" in lines[i]:
        i += 1
    return i


def _parse_table(lines: List[str], start: int) -> Block:
    header = [c.strip() for c in lines[start].strip().strip("|").split("|")]
    rows: List[Block] = []
    i = start + 2
    while i < len(lines) and lines[i].strip() and "|" in lines[i]:
        cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
        rows.append(Block("row", text="\x00".join(cells)))
        i += 1
    node = Block("table", text="\x00".join(header))
    node.children = rows
    return node


# =========================================================================== #
# Fallback rendering
# =========================================================================== #
def _slugify(text: str) -> str:
    """Turn heading text into a GitHub-style URL fragment."""
    slug = text.lower()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    return slug.strip("-")


def _render_blocks(blocks: List[Block]) -> str:
    parts: List[str] = []
    for b in blocks:
        if b.kind == "heading":
            tag = f"h{b.level}"
            anchor = _slugify(b.text)
            parts.append(f'<{tag} id="{anchor}">{_inline(b.text)}</{tag}>')
        elif b.kind == "para":
            parts.append(f"<p>{_inline(b.text)}</p>")
        elif b.kind == "code":
            lang = html.escape(b.level)
            badge = f'<span class="lang">{lang}</span>' if lang else ""
            parts.append(
                f'<div class="highlight"><pre><div class="code-header">{badge}</div>'
                f"<code>{highlight(b.text, b.level)}</code></pre></div>"
            )
        elif b.kind == "hr":
            parts.append("<hr>")
        elif b.kind == "blockquote":
            parts.append(f"<blockquote>{_render_blocks(b.children)}</blockquote>")
        elif b.kind == "list":
            parts.append(_render_list(b))
        elif b.kind == "table":
            parts.append(_render_table(b))
    return "".join(parts)


def _render_list(b: Block) -> str:
    tag = "ol" if b.level == 1 else "ul"
    lis: List[str] = []
    for item in b.children:
        cls = ' class="task-list-item"' if item.checked is not None else ""
        check = ""
        if item.checked is not None:
            state = " checked" if item.checked else ""
            check = f'<input type="checkbox" disabled{state}> '
        extra = _render_blocks(item.children)
        lis.append(f"<li{cls}>{check}{_inline(item.text)}{extra}</li>")
    return f"<{tag}>{''.join(lis)}</{tag}>"


def _render_table(b: Block) -> str:
    headers = b.text.split("\x00")
    thead = "<tr>" + "".join(f"<th>{_inline(h)}</th>" for h in headers) + "</tr>"
    body_rows = []
    for row in b.children:
        cells = row.text.split("\x00")
        body_rows.append(
            "<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in cells) + "</tr>"
        )
    tbody = "<tbody>" + "".join(body_rows) + "</tbody>"
    return f'<div class="table-wrap"><table><thead>{thead}</thead>{tbody}</table></div>'


def _fallback_render(text: str, theme: str) -> str:
    """Render Markdown to a standalone document using the built-in backend."""
    blocks = _parse_blocks(_split(text))
    body = _render_blocks(blocks)
    return _assemble_document(body, theme)


# =========================================================================== #
# Document assembly
# =========================================================================== #
def _pygments_style_for(theme: str) -> str:
    """Map a UI theme name to a complementary Pygments style."""
    return {
        "light": "default",
        "dark": "monokai",
        "solarized": "solarized-light",
    }.get(theme, "default")


def _assemble_document(body: str, theme: str) -> str:
    """Wrap rendered body HTML in a complete, standalone HTML document."""
    toc_html = build_toc(body)
    css = build_css(theme)
    extra_pyg = pygments_css(_pygments_style_for(theme))
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Markdown Document</title>
<style>
{css}
{extra_pyg}
</style>
</head>
<body>
<div class="page">
<div class="md2html">
{toc_html}
{body}
</div>
</div>
</body>
</html>
"""


# =========================================================================== #
# Public API
# =========================================================================== #
def convert(markdown_text: str, theme: str = "light") -> str:
    """Convert Markdown text into a standalone HTML document.

    Args:
        markdown_text: The Markdown source to convert.
        theme: CSS theme name (``light``, ``dark``, or ``solarized``).

    Returns:
        A complete HTML document string with the theme CSS embedded.

    Raises:
        ValueError: If ``theme`` is not a recognised theme name.
    """
    if theme not in THEME_NAMES:
        raise ValueError(
            f"Unknown theme {theme!r}. Available: {', '.join(sorted(THEME_NAMES))}"
        )
    if MDIT_LOADED:
        return _mdit_render(markdown_text, theme)
    return _fallback_render(markdown_text, theme)