"""Unit tests for frontmatter parsing, Markdown rendering and slugs."""

from __future__ import annotations

import datetime as dt

import pytest

from blog.parser import (
    Post,
    load_post,
    parse_frontmatter,
    parse_date,
    render_markdown,
    slugify,
)


def test_parse_frontmatter_basic():
    raw = "---\ntitle: Hello World\ndate: 2024-01-15\ntags: [a, b]\ndraft: true\n---\n# body"
    fm, end = parse_frontmatter(raw)
    assert fm["title"] == "Hello World"
    assert fm["tags"] == ["a", "b"]
    assert fm["draft"] is True
    # ``end`` is a line index just past the closing ``---``.
    body_lines = raw.splitlines()[end:]
    assert body_lines[0].startswith("# body")


def test_parse_frontmatter_missing_fields():
    fm, end = parse_frontmatter("---\ntitle: Only Title\n---\nbody")
    assert fm["title"] == "Only Title"
    # No date/tags/draft keys -> they are simply absent, not erroring.
    assert "date" not in fm


def test_parse_date_variants():
    assert parse_date("2024-01-05") == dt.date(2024, 1, 5)
    assert parse_date(None) is None
    assert parse_date("2024/three/03") is None  # malformed -> None, not crash
    assert parse_date("garbage", default=dt.date(2020, 1, 1)) == dt.date(2020, 1, 1)


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Hello World", "hello-world"),
        ("My-post & You", "my-post-you"),
        ("  Spaces   galore  ", "spaces-galore"),
        ("Python 101: Lists", "python-101-lists"),
    ],
)
def test_slugify(title, expected):
    assert slugify(title) == expected


def test_load_post_returns_post_with_rendered_body():
    from pathlib import Path

    import tempfile

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "python.md"
        p.write_text(
            "---\ntitle: Python\nauthor: Tester\ntags: [py, code]\n"
            "description: About python.\n---\n\n## Heading\n\n`print(1)`\n",
            encoding="utf-8",
        )
        post = load_post(p, default_author="Default Author")
    assert isinstance(post, Post)
    assert post.title == "Python"
    assert post.slug == "python"
    assert post.author == "Tester"
    assert post.tags == ["py", "code"]
    assert "<h2" in post.body_html
    assert "print" in post.body_html


def test_load_post_defaults_author_from_arg():
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "noauthor.md"
        p.write_text("---\ntitle: No Auth\n---\ntext\n", encoding="utf-8")
        post = load_post(p, default_author="Fallback Person")
    assert post.author == "Fallback Person"


def test_render_markdown_supports_lists_links_and_code():
    html = render_markdown("# T\n\n- one\n- two\n\n[a link](https://x.dev)\n\n`code`\n")
    assert "<h1" in html and "<li>" in html and "x.dev" in html
    assert "code" in html


def test_post_url_and_iso_date():
    p = Post(title="Hi", slug="hi", date=dt.date(2024, 5, 6))
    assert p.url == "/posts/hi/"
    assert p.iso_date == "2024-05-06"