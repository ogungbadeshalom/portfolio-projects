# Markdown Blog with RSS

## Project Title
Markdown Blog with RSS Feed (Python)

## Goal
Static site generator that turns a folder of Markdown files into a blog. Pages, RSS feed, sitemap, OG images, code highlighting, dark mode. No frameworks — pure Python + HTML/CSS.

## Why this project
Content sites are everywhere. Teaches: file system traversal, frontmatter parsing, template rendering, atomic file generation, RSS spec, sitemap protocol.

## What You Build

A `blog` command:

```bash
blog init ./my-blog                  # create scaffold
blog new "My first post" --tags python
blog build                          # generate dist/
blog serve                          # local preview at :8000
blog deploy                         # push to GitHub Pages
```

Build produces:
```
dist/
├── index.html                  # home with post list
├── posts/
│   ├── my-first-post/
│   │   └── index.html          # post page
│   └── another-post/
│       └── index.html
├── feed.xml                    # RSS 2.0
├── atom.xml                    # Atom 1.0
├── sitemap.xml                 # sitemap protocol
├── robots.txt
├── tags/
│   └── python/
│       └── index.html          # posts tagged "python"
└── assets/                     # CSS, images
```

## Tech
- **Python 3.11+**
- **markdown-it-py** (Markdown parser with frontmatter support)
- **Jinja2** (template engine)
- **Pygments** (syntax highlighting)
- **Click** for CLI
- **watchdog** for live reload (stretch)

## Architecture

```
blog/
├── blog/
│   ├── __init__.py
│   ├── cli.py              # Click commands
│   ├── builder.py         # core: walk posts dir → render → write
│   ├── parser.py          # frontmatter + markdown
│   ├── templates/
│   │   ├── base.html
│   │   ├── post.html
│   │   ├── index.html
│   │   ├── tag.html
│   │   ├── feed.xml
│   │   └── sitemap.xml
│   ├── rss.py             # RSS 2.0 generator
│   ├── sitemap.py         # sitemap.xml generator
│   ├── og.py              # OG image generator (Pillow)
│   └── serve.py           # `blog serve` local server
├── posts/                 # user content goes here
│   └── example.md
├── templates/             # default templates
├── static/                # CSS, fonts
├── tests/
├── pyproject.toml
└── CLAUDE.md
```

## Build Order

1. **`parser.py`** — read .md files, extract YAML frontmatter, parse Markdown body
2. **`builder.py`** — iterate posts, apply Jinja2 template, write to `dist/`
3. **`rss.py`** — generate RSS 2.0 feed from post list
4. **`sitemap.py`** — generate sitemap.xml with all post URLs
5. **`og.py`** — generate OG image per post (title + author + site name)
6. **`cli.py`** — Wire up `init`, `new`, `build`, `serve`, `deploy`
7. **Templates** — base.html (header/footer/nav), post.html, index.html, tag.html
8. **CSS** — clean typography, code highlighting, dark mode

## Requirements

- Frontmatter: `title`, `date`, `author`, `tags`, `description`, `draft` (bool)
- Markdown body supports: headings, code blocks, lists, images, blockquotes
- Code blocks syntax-highlighted (Pygments)
- Dark mode toggle (localStorage)
- RSS 2.0 feed valid (validate at https://validator.w3.org/feed/)
- Atom 1.0 feed valid
- sitemap.xml valid (https://www.xml-sitemaps.com/validate-xml-sitemap.html)
- Pagination: 10 posts per page on index
- Tag pages: `/tags/python/` lists all posts with that tag
- Draft posts excluded from production build
- `blog serve` auto-rebuilds on file change (stretch)

## Code Standards

- Templates use Jinja2 with `autoescape` enabled
- All output files use UTF-8
- URLs: kebab-case, no trailing slash, lowercase
- Frontmatter parsing handles edge cases (missing fields, malformed YAML)
- Builder is idempotent (re-running produces same output)
- No external CDN dependencies at runtime (CSS embedded or local)

## Verification

```bash
# Initialize
blog init ./test-blog && cd test-blog
blog new "Hello World"
blog new "Python tips" --tags python
blog build

# Verify outputs
ls dist/posts/
cat dist/feed.xml | head -20
cat dist/sitemap.xml

# Serve
blog serve
# Visit http://localhost:8000

# Validate RSS
xmllint --noout dist/feed.xml
```

## Stretch Goals

- Series / collections (group related posts)
- Full-text search (client-side JS index)
- Reading time estimate
- Table of contents (auto-generated from headings)
- Related posts (by tag overlap)
- RSS per tag
- JSON Feed (jsonfeed.org)
- WebSub (PubSubHubbub) for instant RSS updates
- Draft preview URLs

## What You'll Learn

- File system traversal patterns
- Frontmatter + Markdown parsing
- Jinja2 template inheritance
- RSS/Atom/sitemap XML spec
- OG image generation with Pillow
- Static site generation concepts (used by Hugo, Jekyll, etc.)

## Time Estimate
6-10 hours for MVP with templates. 12-16 hours with RSS + sitemap + OG + dark mode + tests.