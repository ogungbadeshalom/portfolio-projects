"""Core build engine.

The :mod:`blog.builder` module walks a ``posts/`` directory, renders every
page and generates the full static site under ``dist/``:

* ``index.html`` and paginated ``index.html`` pages (10 posts each),
* ``posts/<slug>/index.html`` for each post,
* ``tags/<tag>/index.html`` pages,
* ``feed.xml`` (RSS 2.0), ``atom.xml`` (Atom 1.0),
* ``sitemap.xml`` and ``robots.txt``,
* a copy of ``static/`` and optional per-post OG images.

The build is **deterministic and idempotent**: re-running ``build`` after a
content change produces the same bytes for unchanged posts, and never leaves
stale files behind (``dist/`` is cleaned first).
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from . import og
from .config import SiteConfig
from .parser import Post, load_post, slugify
from .rss import build_atom, build_rss, rss_doc
from .sitemap import build_sitemap, build_robots
from .templating import TemplateEngine

# Filenames of the template files bundled in ``blog/templates/``.
BASE_TEMPLATE = "base.html"
INDEX_TEMPLATE = "index.html"
POST_TEMPLATE = "post.html"
TAG_TEMPLATE = "tag.html"

PUBLIC_HTML = "index.html"


def collect_posts(posts_dir: Path, default_author: Optional[str], include_drafts: bool = False) -> List[Post]:
    """Load every ``*.md`` post under ``posts_dir``, newest first.

    Parameters
    ----------
    posts_dir:
        Directory of Markdown posts.
    default_author:
        Author applied to posts missing an ``author`` field.
    include_drafts:
        When ``True`` draft posts are kept (used by ``blog serve`` to preview
        drafts); production builds pass ``False``.

    Returns
    -------
    Posts sorted by date descending (posts without a date sort last).
    """
    posts: List[Post] = []
    if not posts_dir.is_dir():
        return posts
    for path in sorted(posts_dir.glob("*.md")):
        try:
            post = load_post(path, default_author=default_author)
        except (OSError, UnicodeDecodeError):
            continue
        if post.draft and not include_drafts:
            continue
        posts.append(post)

    def sort_key(post: Post) -> Tuple[int, str]:
        # Naive epoch for missing dates so they sort to the end.
        return (post.date.toordinal() if post.date else 0, post.slug)

    posts.sort(key=sort_key, reverse=True)
    return posts


def collect_tags(posts: Sequence[Post]) -> Dict[str, List[Post]]:
    """Build ``{tag: [posts]}`` preserving the newest-first posting order."""
    tags: Dict[str, List[Post]] = {}
    for post in posts:
        for tag in post.tags:
            tags.setdefault(tag, []).append(post)
    return tags


def render_paginated_index(
    engine: TemplateEngine,
    config: SiteConfig,
    posts: Sequence[Post],
    page: int,
    root: str,
    tag: Optional[str] = None,
) -> str:
    """Render one index page (page 1, 2, ...) or a tag page (page 1 only)."""
    total = len(posts)
    pages = max(1, (total + config.paginate - 1) // config.paginate)
    start = (page - 1) * config.paginate
    page_posts = list(posts[start : start + config.paginate])

    prev_page = page - 1 if page > 1 else None
    next_page = page + 1 if page < pages else None

    return engine.render(
        INDEX_TEMPLATE,
        config=config,
        posts=page_posts,
        total=total,
        pages=pages,
        current_page=page,
        next_page=next_page,
        prev_page=prev_page,
        tag=tag,
        page_title=tag,
        root=root,
    )


def render_tag_pages(engine: TemplateEngine, config: SiteConfig, tags: Dict[str, List[Post]], root: str) -> None:
    """Render all tag index pages into ``root``."""
    for tag, tag_posts in sorted(tags.items()):
        dest = root / "tags" / tag / PUBLIC_HTML
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(
            render_paginated_index(engine, config, tag_posts, page=1, root="/../..", tag=tag),
            encoding="utf-8",
        )


def copy_assets(src_dir: Path, dest_dir: Path) -> None:
    """Recursively copy ``static/`` into an output ``assets/`` folder."""
    if not src_dir.is_dir():
        return
    shutil.copytree(src_dir, dest_dir, dirs_exist_ok=True)


def build(
    root: Path,
    *,
    include_drafts: bool = False,
    generate_og: bool = True,
    quiet: bool = False,
) -> Dict[str, int]:
    """Run a full build of the blog rooted at ``root``.

    Parameters
    ----------
    root:
        The blog directory containing ``posts/``, ``static/``, ``templates/``
        and (optionally) ``settings.cfg``.
    include_drafts:
        Keep draft posts (default ``False`` for production).
    generate_og:
        Attempt per-post Open Graph images; skipped gracefully if Pillow is
        missing or generation fails.
    quiet:
        Suppress progress output.

    Returns
    -------
    ``{"posts": n, "pages": n, "tags": n, "og_images": n}`` counts.
    """
    posts_dir = root / "posts"
    static_dir = root / "static"
    templates_dir = root / "templates"
    dist_dir = root / "dist"

    config = SiteConfig.from_file(root / "settings.cfg")

    engine = TemplateEngine(templates_dir)
    posts = collect_posts(posts_dir, config.author, include_drafts=include_drafts)
    tags = collect_tags(posts)

    # Reset the output tree so builds stay idempotent / stale-free.
    if dist_dir.exists():
        shutil.rmtree(dist_dir)
    dist_dir.mkdir(parents=True, exist_ok=True)

    og_count = 0
    if generate_og:
        og_count = og.generate_for_posts(static_dir, posts, config, dist_dir)

    # Copy static assets.
    copy_assets(static_dir, dist_dir / "assets")

    # ----- Index (paginated) and post pages -------------------------------- #
    total = len(posts)
    pages = max(1, (total + config.paginate - 1) // config.paginate)
    index_root = "."

    for page in range(1, pages + 1):
        html_text = render_paginated_index(engine, config, posts, page=page, root=index_root)
        if page == 1:
            (dist_dir / PUBLIC_HTML).write_text(html_text, encoding="utf-8")
        else:
            page_dir = dist_dir / "page" / str(page)
            page_dir.mkdir(parents=True, exist_ok=True)
            (page_dir / PUBLIC_HTML).write_text(html_text, encoding="utf-8")

    for post in posts:
        post_dir = dist_dir / "posts" / post.slug
        post_dir.mkdir(parents=True, exist_ok=True)
        og_image = f"/assets/og/{post.slug}.png" if (dist_dir / "assets" / "og" / f"{post.slug}.png").exists() and generate_og else None
        html_text = engine.render(
            POST_TEMPLATE,
            config=config,
            post=post,
            root="/../..",
            og_image=og_image,
        )
        (post_dir / PUBLIC_HTML).write_text(html_text, encoding="utf-8")

    # ----- Tag pages -------------------------------------------------------- #
    render_tag_pages(engine, config, tags, dist_dir)

    # ----- Feeds and sitemap ------------------------------------------------- #
    absolute_posts = posts  # sitemap/feeds consume the Post list
    (dist_dir / "feed.xml").write_text(build_rss(absolute_posts, config), encoding="utf-8")
    (dist_dir / "atom.xml").write_text(build_atom(absolute_posts, config), encoding="utf-8")
    (dist_dir / "sitemap.xml").write_text(build_sitemap(absolute_posts, tags, config), encoding="utf-8")
    (dist_dir / "robots.txt").write_text(build_robots(config), encoding="utf-8")

    counts = {
        "posts": len(posts),
        "pages": pages + len(posts) + len(tags),
        "tags": len(tags),
        "og_images": og_count,
    }
    if not quiet:
        print(f"Built {counts['posts']} posts, {counts['tags']} tags, "
              f"{counts['pages']} pages, {counts['og_images']} OG images -> {dist_dir}")
    return counts


def available_templates(root: Path) -> List[str]:
    """List the template names a blog root can render (for debugging)."""
    tdir = root / "templates"
    if not tdir.is_dir():
        return []
    return sorted(p.name for p in tdir.iterdir() if p.is_file())