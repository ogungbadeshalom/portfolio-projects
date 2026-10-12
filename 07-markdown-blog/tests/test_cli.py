"""CLI behaviour tests: scaffolding, new posts, and the build command."""

from __future__ import annotations

from pathlib import Path

import pytest

from blog.cli import init_blog, new_post
from blog.parser import load_post


def test_init_scaffolds_full_tree(tmp_path):
    root = tmp_path / "site"
    init_blog(root, title="My World")

    for sub in ("posts", "templates", "static"):
        assert (root / sub).is_dir()
    assert (root / "settings.cfg").is_file()
    assert (root / "posts" / "welcome.md").is_file()
    assert (root / "templates" / "base.html").is_file()
    assert (root / "static" / "style.css").is_file()

    # Settings reflect the title and site URL is derived from the root name.
    from blog.config import SiteConfig

    cfg = SiteConfig.from_file(root / "settings.cfg")
    assert cfg.title == "My World"


def test_new_post_writes_frontmatter_and_body(blog_root):
    path = new_post(blog_root, "My Fresh Idea", tags=["alpha", "beta"], author="Zed")
    assert path.is_file()
    post = load_post(path, default_author="x")
    assert post.slug == "my-fresh-idea"
    assert post.title == "My Fresh Idea"
    assert post.tags == ["alpha", "beta"]
    assert post.author == "Zed"
    assert not post.draft
    assert post.body_html and "My Fresh Idea" in post.body_html


def test_new_post_refuses_duplicate(blog_root):
    new_post(blog_root, "Once")
    with pytest.raises(FileExistsError):
        new_post(blog_root, "Once")


def test_draft_post_flagged_and_excluded_from_build(blog_root):
    draft_path = new_post(blog_root, "WIP Piece", draft=True)
    from blog.parser import load_post

    assert load_post(draft_path, default_author="x").draft is True

    from blog.builder import build

    build(blog_root, quiet=True)
    assert not (blog_root / "dist" / "posts" / "wip-piece" / "index.html").exists()
    # The non-draft scaffold post still builds.
    assert (blog_root / "dist" / "posts" / "welcome" / "index.html").is_file()