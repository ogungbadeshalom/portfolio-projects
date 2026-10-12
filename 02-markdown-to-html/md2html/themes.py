"""CSS theme definitions.

Each theme is a block of CSS defining the same set of variables and rules,
so ``build_css()`` can assemble a document: the chosen ``<style>`` plus the
reusable component styles (code blocks, tables, the TOC, task lists).

The palettes live in ``themes/`` as ``*.css`` which are also shipped next to
the package for people who want to edit them by hand. This module embeds the
same CSS at build time so the output stays a single standalone file.
"""

from __future__ import annotations

from typing import Dict, List
from pathlib import Path

THEME_DIR = Path(__file__).resolve().parent.parent / "themes"

# Theme name -> (human label, CSS variable palette).
# Colours are kept in one place here; the ``themes/*.css`` files mirror them.
_THEME_VARS: Dict[str, str] = {
    "light": """
:root {
  --bg: #ffffff;
  --fg: #24292f;
  --muted: #57606a;
  --accent: #0969da;
  --border: #d0d7de;
  --code-bg: #f6f8fa;
  --blockquote-border: #d0d7de;
  --table-stripe: #f6f8fa;
  --header-bg: #f6f8fa;
}
""",
    "dark": """
:root {
  --bg: #0d1117;
  --fg: #e6edf3;
  --muted: #8b949e;
  --accent: #58a6ff;
  --border: #30363d;
  --code-bg: #161b22;
  --blockquote-border: #30363d;
  --table-stripe: #161b22;
  --header-bg: #161b22;
}
""",
    "solarized": """
:root {
  --bg: #fdf6e3;
  --fg: #657b83;
  --muted: #93a1a1;
  --accent: #268bd2;
  --border: #eee8d5;
  --code-bg: #f8f5e4;
  --blockquote-border: #839496;
  --table-stripe: #f8f5e4;
  --header-bg: #eee8d5;
}
""",
}

# Reusable component CSS that is identical across themes (variables drive it).
_GLOBAL_CSS = """
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body {
  background: var(--bg);
  color: var(--fg);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
  line-height: 1.6;
}
.page {
  max-width: 860px;
  margin: 0 auto;
  padding: 2rem 1.5rem 4rem;
}
.md2html h1, .md2html h2, .md2html h3, .md2html h4 {
  line-height: 1.25;
  margin: 1.5em 0 0.5em;
  padding-bottom: 0.3em;
  border-bottom: 1px solid var(--border);
}
.md2html h1 { font-size: 2em; }
.md2html h2 { font-size: 1.5em; }
.md2html h3 { font-size: 1.25em; }
.md2html h4 { font-size: 1em; }
.md2html p { margin: 0.6em 0; }
.md2html a { color: var(--accent); text-decoration: none; }
.md2html a:hover { text-decoration: underline; }
.md2html code {
  background: var(--code-bg);
  border-radius: 4px;
  padding: 0.15em 0.35em;
  font-family: ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace;
  font-size: 0.9em;
}
.md2html pre {
  background: var(--code-bg);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 1em;
  overflow-x: auto;
}
.md2html pre code {
  background: transparent;
  padding: 0;
  font-size: 0.88em;
}
.md2html .highlight .code-header {
  margin: -1em -1em 0.6em;
  padding: 0.4em 0.8em;
  border-bottom: 1px solid var(--border);
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 0.78em;
}
.md2html .highlight .lang { color: var(--muted); }
.md2html .tok-code { color: var(--fg); }
.md2html blockquote {
  margin: 1em 0;
  padding: 0.1em 1em;
  border-left: 4px solid var(--blockquote-border);
  color: var(--muted);
  background: var(--code-bg);
}
.md2html blockquote > :first-child { margin-top: 0.5em; }
.md2html blockquote > :last-child { margin-bottom: 0.5em; }
.md2html hr {
  border: none;
  border-top: 3px solid var(--border);
  margin: 2em 0;
}
.md2html img { max-width: 100%; }
.md2html .table-wrap { overflow-x: auto; margin: 1em 0; }
.md2html table {
  border-collapse: collapse;
  width: 100%;
}
.md2html th, .md2html td {
  border: 1px solid var(--border);
  padding: 0.4em 0.8em;
  text-align: left;
}
.md2html thead th {
  background: var(--header-bg);
  font-weight: 600;
}
.md2html tbody tr:nth-child(even) td { background: var(--table-stripe); }
.md2html ul, .md2html ol { padding-left: 1.6em; }
.md2html ul.task-list { list-style: none; padding-left: 0; }
.md2html .task-list-item { list-style: none; }
.md2html .task-list-item input { margin-right: 0.4em; }
/* Table of contents */
.md2html .toc {
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--code-bg);
  padding: 0.8em 1.2em;
  margin-bottom: 1.5em;
}
.md2html .toc summary {
  font-weight: 600;
  cursor: pointer;
  color: var(--fg);
}
.md2html .toc ul { padding-left: 1.3em; margin: 0.5em 0 0; list-style: none; }
.md2html .toc a { color: var(--accent); text-decoration: none; }
.md2html .toc a:hover { text-decoration: underline; }
.md2html .toc .toc-sub { margin-left: 1em; }
"""

THEME_NAMES = frozenset(_THEME_VARS.keys())


def build_css(theme: str) -> str:
    """Assemble the full stylesheet for ``theme``.

    Args:
        theme: One of :data:`THEME_NAMES`.

    Returns:
        The complete CSS string (variables + shared rules).

    Raises:
        ValueError: If ``theme`` is unknown.
    """
    if theme not in _THEME_VARS:
        raise ValueError(
            f"Unknown theme {theme!r}. Available: {', '.join(sorted(_THEME_VARS))}"
        )
    return _THEME_VARS[theme] + _GLOBAL_CSS