"""Shared fixtures for the markdown blog tests.

Every test builds a real blog scaffold (via ``init_blog``) in a temp
directory and writes real Markdown posts, then runs the actual build
pipeline -- no mocks of the parser, builder, feeds or templates.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from blog.cli import init_blog, new_post


@pytest.fixture
def blog_root(tmp_path: Path) -> Path:
    """A scaffolded blog root (settings, templates, static, one welcome post)."""
    root = tmp_path / "site"
    init_blog(root, title="Test Blog")
    return root


def write_post(root: Path, slug: str, *, title: str = None, tags=None,
               author: str = "Tester", draft: bool = False,
               extra_frontmatter: str = "", body: str = None) -> Path:
    """Write a complete Markdown post file directly into ``root/posts``."""
    posts = root / "posts"
    posts.mkdir(parents=True, exist_ok=True)
    path = posts / f"{slug}.md"
    title = title or slug.replace("-", " ").title()
    tag_txt = ", ".join(tags or [])
    draft_txt = "true" if draft else "false"
    if body is None:
        body = f"# {title}\n\nSome **markdown** with a [link](https://example.com).\n"
    fm = [
        "---",
        f"title: {title}",
        f"author: {author}",
        f"tags: [{tag_txt}]" if tags else "tags: []",
        f"draft: {draft_txt}",
    ]
    if extra_frontmatter:
        fm.append(extra_frontmatter.rstrip())
    text = "\n".join(fm) + "\n---\n\n" + body.strip() + "\n"
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def populated_blog(blog_root: Path) -> Path:
    """A blog with a few dated, tagged posts (plus one draft)."""
    # Override the welcome post date so ordering is deterministic.
    (blog_root / "posts" / "welcome.md").write_text(
        "---\ntitle: Welcome\ndate: 2024-01-01\nauthor: Tester\n"
        "tags: [hello]\n---\n\nToday we begin.\n",
        encoding="utf-8",
    )
    write_post(blog_root, "python-tips", tags=["python", "hello"],
               extra_frontmatter="date: 2024-02-10\ndescription: Python tips.",
               body="```python\nprint('hi')\n```\n\n- one\n- two\n")
    write_post(blog_root, "draft-post", tags=["python"], draft=True,
               extra_frontmatter="date: 2024-03-01")
    return blog_root