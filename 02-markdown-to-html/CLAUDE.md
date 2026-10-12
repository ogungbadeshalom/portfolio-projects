# Markdown → HTML Converter

## Project Title
Markdown to HTML Converter (Python)

## Goal
Convert Markdown files to standalone HTML files with syntax highlighting, table of contents, and customizable themes. Works as both a CLI tool and a Python library.

## Why this project
Text parsing is fundamental. This teaches AST-based transformation (the Markdown parser produces a tree of blocks you walk), regex pitfalls, and how to design clean library APIs.

## What You Build
A `md2html` command and a Python library.

```bash
md2html README.md                    # writes README.html
md2html posts/*.md -o dist/          # batch convert
md2html doc.md --theme dark --toc    # with dark theme + TOC
md2html README.md --serve            # local preview server
```

Library:
```python
from md2html import convert
html = convert("# Hello\n\n**Bold**", theme="light")
```

## Tech
- **Python 3.11+**
- **markdown-it-py** (Markdown parser, well-maintained, MIT-licensed fork of markdown-it)
- **Pygments** for syntax highlighting
- **Click** for CLI (or Typer)
- **Pydantic** for config validation
- **uvicorn + FastAPI** for the `--serve` preview mode

## Architecture

```
md2html/
├── md2html/
│   ├── __init__.py
│   ├── __main__.py
│   ├── converter.py        # core Markdown → HTML conversion
│   ├── themes.py           # CSS theme definitions
│   ├── toc.py              # Table of contents generation
│   ├── highlight.py        # Pygments wrapper
│   ├── serve.py            # FastAPI preview server
│   └── config.py           # Pydantic settings model
├── themes/
│   ├── light.css
│   ├── dark.css
│   └── solarized.css
├── tests/
├── examples/
├── pyproject.toml
└── CLAUDE.md
```

## Build Order

1. **`converter.py`** — wrap markdown-it-py, add plugins (anchors, tables, footnotes)
2. **`highlight.py`** — Pygments integration, CSS class output
3. **`themes.py`** — embed CSS in HTML output
4. **`toc.py`** — parse rendered HTML for h1/h2/h3, generate nested TOC
5. **`config.py`** — Pydantic model for CLI args + config file
6. **`__main__.py` + CLI** — Click/Typer commands
7. **`serve.py`** — FastAPI server at `/file/{path}` showing rendered HTML
8. **Themes** — at least 3 stylesheets (light, dark, solarized)

## Requirements

- Standalone HTML (CSS embedded, no external assets required)
- Code blocks with syntax highlighting (Pygments)
- Auto-generate table of contents from headings (anchored links)
- Support GitHub-Flavored Markdown (tables, task lists, fenced code)
- Custom CSS themes selectable via CLI flag
- CLI returns non-zero exit on error
- Library API: `convert(markdown_text, theme='light') → html_string`

## Code Standards

- All public functions have type hints + docstrings
- Use `markdown-it-py`'s official plugins, don't reinvent
- CSS in themes/ should be ~200 lines max each
- Error messages include the file path that failed
- No regex for Markdown parsing — use the AST the parser gives you

## Verification

```bash
# Run tests
pytest tests/ -v

# Convert a real Markdown file
md2html tests/fixtures/sample.md --theme dark --toc -o dist/

# Verify output
xdg-open dist/sample.html

# Library test
python -c "from md2html import convert; print(convert('# Hello\n\n- item 1\n- item 2'))"
```

## Stretch Goals

- Add Mermaid diagram support (via mermaid-cli)
- Add MathJax/KaTeX for math
- Watch mode (rebuild on file change)
- Auto-detect output path (input.md → input.html in same dir)
- Copy assets (images) to output dir

## What You'll Learn

- Markdown AST parsing
- Plugin architecture (markdown-it plugins)
- Embedding CSS in HTML
- Pygments integration
- FastAPI for preview servers

## Time Estimate
4-6 hours for core + themes. 8-10 hours with preview server.