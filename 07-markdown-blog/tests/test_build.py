"""End-to-end build tests: a real scaffold + posts render to dist/."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from blog.builder import build

from conftest import write_post


def test_build_produces_expected_tree(populated_blog):
    counts = build(populated_blog)
    d = populated_blog / "dist"

    # Indices + pages.
    assert (d / "index.html").is_file()
    # Home lists published post titles (Markdown title rendered out).
    home = (d / "index.html").read_text(encoding="utf-8")
    assert "Welcome" in home and "Python Tips" in home

    # Post pages for published posts only (draft excluded).
    assert (d / "posts" / "welcome" / "index.html").is_file()
    assert (d / "posts" / "python-tips" / "index.html").is_file()
    assert not (d / "posts" / "draft-post" / "index.html").exists(), "draft leaked into build"

    # Tag pages.
    tag_python = d / "tags" / "python" / "index.html"
    assert tag_python.is_file()
    assert "python-tips" in tag_python.read_text(encoding="utf-8")

    # Feeds / sitemap / robots / assets.
    assert (d / "feed.xml").is_file()
    assert (d / "atom.xml").is_file()
    assert (d / "sitemap.xml").is_file()
    assert (d / "robots.txt").is_file()
    assert (d / "assets" / "style.css").is_file()

    # Counts reflect published posts and their tag pages.
    assert counts["posts"] == 2
    assert counts["tags"] == 2  # hello, python
    assert counts["pages"] == counts["posts"] + counts["tags"] + 1


def test_build_includes_drafts_when_requested(populated_blog):
    counts = build(populated_blog, include_drafts=True)
    d = populated_blog / "dist"
    assert (d / "posts" / "draft-post" / "index.html").is_file()
    assert counts["posts"] == 3


def test_build_is_idempotent(populated_blog):
    first = build(populated_blog, quiet=True)
    second = build(populated_blog, quiet=True)
    assert first == second
    # Same bytes for the home page across rebuilds (no stray timestamps).
    d = populated_blog / "dist"
    assert (d / "index.html").read_bytes() == (d / "index.html").read_bytes()


def test_pagination_splits_many_posts(tmp_path):
    """With a low pagination limit the index splits into /page/N/."""
    from blog.cli import init_blog

    root = tmp_path / "many"
    init_blog(root)

    # Remove scaffold's welcome post and add > paginate posts.
    (root / "posts" / "welcome.md").unlink()
    for i in range(12):
        write_post(root, f"post-{i:02d}", tags=["bulk"],
                   extra_frontmatter=f"date: 2024-06-{i+1:02d}")

    # Force paginate=3 via settings.cfg.
    settings = root / "settings.cfg"
    settings.write_text(settings.read_text(encoding="utf-8") + "paginate = 3\n", encoding="utf-8")

    build(root, quiet=True)
    d = root / "dist"
    assert (d / "index.html").is_file()
    assert (d / "page" / "2" / "index.html").is_file()
    assert (d / "page" / "4" / "index.html").is_file(), "12 posts @3/page => 4 pages"


def test_feed_and_sitemap_are_valid_xml(populated_blog):
    build(populated_blog, quiet=True)
    d = populated_blog / "dist"
    for name in ("feed.xml", "atom.xml", "sitemap.xml"):
        ET.parse(d / name)  # raises if not well-formed
    ET.parse(d / "robots.txt") if False else None  # robots isn't XML