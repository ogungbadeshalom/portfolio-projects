"""Frontmatter + Markdown parsing.

The :mod:`blog.parser` module turns a ``.md`` file on disk into a
:class:`Post` namedtuple with parsed metadata and rendered HTML.

Design
------
* The frontmatter block is an optional YAML document between the very first
  pair of ``---`` lines.  Parsing is defensive: missing fields get sane
  defaults, malformed YAML falls back line-by-line, and bad dates/allowed
  ``Optional`` conversions never raise during a build.
* Markdown bodies are rendered with **markdown-it-py** when it is importable,
  otherwise with a compact built-in renderer covering the common cases:
  headings, blockquotes, fenced/indented code blocks, lists, links, images,
  horizontal rules, paragraphs, inline emphasis and inline code.

The module keeps the two renderers behind a single :func:`render_markdown`
interface so the builder treats them as interchangeable.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

# --------------------------------------------------------------------------- #
# YAML helpers (no PyYAML dependency)
# --------------------------------------------------------------------------- #

# Matches a simple "key: value" line.  Values are trimmed of surrounding
# quotes so a line like  tags: ["a", "b"]  becomes a list.
_YAML_LINE_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_\-]*)\s*:\s*(.*)$")
_QUOTE_TRIM_RE = re.compile(r'^[\'"]?(.*?)[\'"]?$')


def _parse_scalar(value: str) -> object:
    """Coerce a raw frontmatter value into a sensible Python object.

    Handles the common scalar types -- ``bool``, ``int``, ``float``, ``None``
    and quoted strings -- and falls back to the trimmed raw string for
    anything unusual.
    """
    value = value.strip()
    if value == "":
        return None
    lowered = value.lower()
    if lowered in ("true", "yes", "on"):
        return True
    if lowered in ("false", "no", "off"):
        return False
    if lowered in ("null", "none", "~"):
        return None
    # Comma separated list:  tags: python, cli
    if "," in value and not (value.startswith("[") or value.startswith('"')):
        parts = [p.strip().strip("'\"").strip() for p in value.split(",")]
        return [p for p in parts if p]
    try:
        if re.fullmatch(r"[+-]?\d+", value):
            return int(value)
        if re.fullmatch(r"[+-]?\d+\.\d+", value):
            return float(value)
    except ValueError:  # pragma: no cover - regex guards this
        pass
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        parts = [p.strip().strip("'\"").strip() for p in inner.split(",")]
        return [p for p in parts if p]
    return _QUOTE_TRIM_RE.match(value).group(1).strip()


def parse_frontmatter(raw: str) -> Tuple[Dict[str, object], int]:
    """Extract the YAML frontmatter block from ``raw``.

    Returns a ``(metadata, body_offset)`` pair.  ``body_offset`` is the index
    of the first body line, or ``0`` when no frontmatter is present.  Malformed
    YAML never raises: unparseable lines are skipped and the rest retained.

    Parameters
    ----------
    raw:
        The full text of a ``.md`` file.

    Returns
    -------
    (metadata, body_offset)
        ``metadata`` maps field names to parsed values; ``body_offset``
        points just past the closing ``---``.
    """
    lines = raw.splitlines()
    if len(lines) < 2 or lines[0].strip() != "---":
        return {}, 0

    meta: Dict[str, object] = {}
    body = 0
    for i in range(1, len(lines)):
        line = lines[i]
        if line.strip() == "---":
            body = i + 1
            break
        match = _YAML_LINE_RE.match(line)
        if not match:
            continue  # skip malformed lines
        key, raw_value = match.group(1), match.group(2)
        meta[key] = _parse_scalar(raw_value)
    else:
        # No closing delimiter: treat the whole file as body.
        return {}, 0
    return meta, body


# --------------------------------------------------------------------------- #
# Date handling
# --------------------------------------------------------------------------- #

_DATE_FORMATS: Tuple[str, ...] = (
    "%Y-%m-%d",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
)


def parse_date(value: Optional[object], default: Optional[_dt.date] = None) -> Optional[_dt.date]:
    """Parse a date from a frontmatter value, tolerantly.

    Accepts ``datetime.date`` objects, ISO ``YYYY-MM-DD`` strings, and strings
    with a time component.  Returns ``default`` when the value is missing or
    cannot be parsed, so a build never dies over a bad date.
    """
    if value is None:
        return default
    if isinstance(value, _dt.datetime):
        return value.date()
    if isinstance(value, _dt.date):
        return value
    if isinstance(value, (int, float)):
        try:
            return _dt.date.fromtimestamp(float(value))
        except (ValueError, OSError, OverflowError):
            return default
    text = str(value).strip()
    for fmt in _DATE_FORMATS:
        try:
            return _dt.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return default


# --------------------------------------------------------------------------- #
# Post model
# --------------------------------------------------------------------------- #

def slugify(title: str) -> str:
    """Turn arbitrary text into a URL-safe kebab-case slug.

    Lowercases, keeps only ASCII letters/digits/spaces/dashes, pulls the
    digits/letters out of the result and joins words with a single ``-``.
    Empty results fall back to ``"post"`` so generated URLs are never blank.
    """
    text = title.strip().lower()
    text = re.sub(r"[^a-z0-9\s\-]+", "", text)
    words = [w for w in re.split(r"[\s\-]+", text) if w]
    slug = "-".join(words) or "post"
    return slug


@dataclass
class Post:
    """A parsed blog post ready to be rendered.

    Attributes
    ----------
    title:
        Display title, defaults to the file stem when missing.
    date:
        Publication date (date-only), or ``None``.
    author:
        Author name, or ``None``.
    tags:
        Ordered list of tag names (deduplicated, kebab-cased).
    description:
        Short summary used in feeds and ``<meta name="description">``.
    draft:
        Whether this post must be excluded from production builds.
    slug:
        URL-safe identifier, defaults to the title's slug.
    body_html:
        The rendered HTML body.
    headings:
        ``(level, text)`` tuples for a table-of-contents / anchor index.
    """

    title: str
    slug: str
    body_html: str = ""
    date: Optional[_dt.date] = None
    author: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    description: str = ""
    draft: bool = False
    headings: List[Tuple[int, str]] = field(default_factory=list)

    # Computed helpers ------------------------------------------------------ #

    @property
    def url(self) -> str:
        """Absolute URL of this post, e.g. ``/posts/hello-world/``."""
        return f"/posts/{self.slug}/"

    @property
    def iso_date(self) -> Optional[str]:
        """ISO-8601 date string for feeds, or ``None``."""
        return self.date.isoformat() if self.date else None

    def anchor_for(self, heading_text: str) -> str:
        """Return a stable slug anchor for a heading's text."""
        return slugify(heading_text)


# --------------------------------------------------------------------------- #
# Markdown rendering (markdown-it-py preferred, built-in otherwise)
# --------------------------------------------------------------------------- #

_FENCE_RE = re.compile(r"^```([A-Za-z0-9_\-+]*)\s*$")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_UL_RE = re.compile(r"^\s*[-*+]\s+(.*)$")
_OL_RE = re.compile(r"^\s*\d+[.)]\s+(.*)$")
_QUOTE_RE = re.compile(r"^\s*>\s?(.*)$")

_INLINE_URL_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+[\"']([^\"']+)[\"'])?\)")
_INLINE_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)[^)]*\)")
_INLINE_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)(?:\s+[\"']([^\"']+)[\"'])?\)")
_INLINE_CODE_RE = re.compile(r"`([^`]+)`")
_INLINE_BOLD_RE = re.compile(r"\*\*([^*]+)\*\*|__([^_]+)__")
_INLINE_ITALIC_RE = re.compile(r"\*([^*]+)\*|_([^_]+)_")


def _escape_html(text: str) -> str:
    """Escape the five HTML-meaningful characters."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _render_inline(text: str) -> str:
    """Render inline Markdown (emphasis, code, links, images) to HTML."""
    text = _escape_html(text)
    text = _INLINE_URL_IMAGE_RE.sub(
        lambda m: f'<a href="{m.group(2)}" title="{m.group(3) or ""}">{m.group(1)}</a>',
        text,
    )
    text = _INLINE_IMAGE_RE.sub(
        lambda m: f'<img src="{m.group(2)}" alt="{m.group(1)}" loading="lazy">', text
    )
    text = _INLINE_LINK_RE.sub(
        lambda m: f'<a href="{m.group(2)}" title="{m.group(3) or ""}">{m.group(1)}</a>',
        text,
    )
    text = _INLINE_CODE_RE.sub(lambda m: f"<code>{m.group(1)}</code>", text)
    text = _INLINE_BOLD_RE.sub(
        lambda m: f"<strong>{m.group(1) or m.group(2)}</strong>", text
    )
    text = _INLINE_ITALIC_RE.sub(
        lambda m: f"<em>{m.group(1) or m.group(2)}</em>", text
    )
    return text


def _render_list(lines: List[str], start: int, ordered: bool) -> Tuple[str, int]:
    """Render a contiguous list block starting at ``start``."""
    items: List[str] = []
    i = start
    while i < len(lines):
        line = lines[i]
        m = _OL_RE.match(line) if ordered else _UL_RE.match(line)
        if not m:
            break
        # Support simple nested lists on the same item line: "item: sub".
        content = m.group(1)
        items.append(f"<li>{_render_inline(content)}</li>")
        i += 1
        # Consume any immediately-following plain continuation lines.
        while i < len(lines) and lines[i].strip() and not (
            _OL_RE.match(lines[i]) or _UL_RE.match(lines[i]) or _FENCE_RE.match(lines[i])
        ):
            items[-1] = f"{items[-1]}\n{_render_inline(lines[i])}"
            i += 1
    tag = "ol" if ordered else "ul"
    body = "".join(items)
    return f"<{tag}>{body}</{tag}>", i


def _highlight(code: str, lang: str) -> str:
    """Highlight ``code`` for ``lang`` if Pygments is importable."""
    try:
        from pygments import highlight
        from pygments.formatters import HtmlFormatter
        from pygments.lexers import get_lexer_by_name
        from pygments.util import ClassNotFound

        try:
            lexer = get_lexer_by_name(lang or "text", stripall=False)
        except ClassNotFound:
            lexer = None  # fall back to plain <pre> below
        if lexer is not None:
            formatter = HtmlFormatter(nowrap=True, cssclass="highlight")
            return highlight(code, lexer, formatter)
    except ImportError:  # Pygments unavailable
        pass
    return _escape_html(code)


def _total_escape(code: str) -> str:
    """Escape code fence content (no highlighting)."""
    return _escape_html(code)


def render_markdown(body: str, headings: Optional[List[Tuple[int, str]]] = None) -> str:
    """Render a Markdown body to an HTML fragment.

    Uses **markdown-it-py** when importable; otherwise falls back to a compact
    built-in renderer.  ``headings`` (if provided) is filled with
    ``(level, text)`` tuples so the builder can build a table of contents or
    heading anchors without re-parsing.

    Parameters
    ----------
    body:
        The Markdown source (without frontmatter).
    headings:
        Optional list that will be appended to with ``(level, text)`` tuples.

    Returns
    -------
    HTML fragment for the post body.
    """
    if headings is None:
        headings = []

    # Try the preferred parser first.
    try:
        import markdown_it  # type: ignore

        md = markdown_it.MarkdownIt("commonmark", {"html": True}).enable("table")
        out = md.render(body)

        # Pull headings out of the generated HTML for the TOC.
        for match in re.finditer(r"<h([1-6])[^>]*>(.*?)</h\1>", out, flags=re.S):
            level = int(match.group(1))
            clean = re.sub(r"<[^>]+>", "", match.group(2))
            headings.append((level, _unescape_entities(clean)))
        return out
    except ImportError:
        pass

    # ---- Built-in fallback renderer --------------------------------------- #
    lines = body.splitlines()
    html: List[str] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]

        if not line.strip():
            i += 1
            continue

        fence = _FENCE_RE.match(line)
        if fence:
            lang = fence.group(1)
            i += 1
            code_lines: List[str] = []
            while i < n and lines[i].strip() != "```":
                code_lines.append(lines[i])
                i += 1
            i += 1  # skip closing fence
            code = "\n".join(code_lines)
            html.append(f"<pre><code class=\"language-{lang or 'text'}\">{_highlight(code, lang)}</code></pre>")
            continue

        heading = _HEADING_RE.match(line)
        if heading:
            level = len(heading.group(1))
            text = heading.group(2).strip()
            anchor = slugify(text)
            headings.append((level, text))
            html.append(f'<h{level} id="{anchor}">{_render_inline(text)}</h{level}>')
            i += 1
            continue

        # Indented code block (4 spaces or a tab).
        if line.startswith(("    ", "\t")):
            code_lines = []
            while i < n and (lines[i].startswith(("    ", "\t")) or not lines[i].strip()):
                code_lines.append(lines[i][4:] if lines[i].startswith("    ") else lines[i].lstrip("\t"))
                i += 1
            html.append(f'<pre><code class="language-text">{_total_escape(chr(10).join(code_lines))}</code></pre>')
            continue

        quote = _QUOTE_RE.match(line)
        if quote:
            quoted = [_render_inline(quote.group(1))]
            i += 1
            while i < n:
                m2 = _QUOTE_RE.match(lines[i])
                if m2:
                    quoted.append(_render_inline(m2.group(1)))
                    i += 1
                else:
                    break
            html.append(f"<blockquote>{''.join(f'<p>{q}</p>' for q in quoted)}</blockquote>")
            continue

        ul_match = _UL_RE.match(line)
        if ul_match:
            block, i = _render_list(lines, i, ordered=False)
            html.append(block)
            continue
        ol_match = _OL_RE.match(line)
        if ol_match:
            block, i = _render_list(lines, i, ordered=True)
            html.append(block)
            continue

        # Horizontal rule.
        if re.fullmatch(r"(\s*[-*_]\s*){3,}", line):
            html.append("<hr>")
            i += 1
            continue

        # Paragraph: gather until a blank line or a new block starts.
        para = [line.strip()]
        i += 1
        while i < n:
            nxt = lines[i].strip()
            if not nxt or _FENCE_RE.match(nxt) or _HEADING_RE.match(nxt) or _QUOTE_RE.match(nxt):
                break
            if _UL_RE.match(nxt) or _OL_RE.match(nxt):
                break
            para.append(nxt)
            i += 1
        html.append(f"<p>{_render_inline(' '.join(para))}</p>")

    return "\n".join(html)


def _unescape_entities(text: str) -> str:
    """Reverse the escaping applied by markdown-it for heading text."""
    return (
        text.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
    )


# --------------------------------------------------------------------------- #
# File -> Post loader
# --------------------------------------------------------------------------- #

def load_post(path, default_author: Optional[str] = None) -> Post:
    """Read a ``.md`` file and return a filled :class:`Post`.

    Parameters
    ----------
    path:
        The ``pathlib.Path`` to the Markdown file.
    default_author:
        Author to apply when the frontmatter omits ``author``.

    Raises
    ------
    OSError
        If the file cannot be read.
    """
    raw = path.read_text(encoding="utf-8")
    meta, body_offset = parse_frontmatter(raw)
    stem = path.stem

    body = "\n".join(raw.splitlines()[body_offset:]).strip()

    title = str(meta.get("title") or stem)
    slug = str(meta.get("slug") or slugify(title))
    date = parse_date(meta.get("date"))
    author = meta.get("author") or default_author
    description = str(meta.get("description") or "")
    draft = bool(meta.get("draft", False))

    raw_tags = meta.get("tags")
    tags: List[str] = []
    if isinstance(raw_tags, list):
        tags = [slugify(t) for t in raw_tags if str(t).strip()]
    elif isinstance(raw_tags, str) and raw_tags.strip():
        tags = [slugify(t) for t in raw_tags.split(",") if t.strip()]

    headings: List[Tuple[int, str]] = []
    body_html = render_markdown(body, headings)

    return Post(
        title=title,
        slug=slug,
        body_html=body_html,
        date=date,
        author=str(author) if author else None,
        tags=tags,
        description=description,
        draft=draft,
        headings=headings,
    )