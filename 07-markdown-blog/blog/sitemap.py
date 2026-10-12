"""Sitemap protocol and robots.txt generation."""

from __future__ import annotations

from typing import Dict, List, Sequence

from .config import SiteConfig
from .parser import Post


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _abs(url: str, config: SiteConfig) -> str:
    if url.startswith("http"):
        return url
    return f"{config.base_url()}{url.rstrip('/')}/"


def build_sitemap(posts: Sequence[Post], tags: Dict[str, List[Post]], config: SiteConfig) -> str:
    """Return a ``sitemap.xml`` document covering home, posts and tags.

    Parameters
    ----------
    posts:
        Non-draft posts (newest first).
    tags:
        Mapping of tag name to its posts.
    config:
        Site configuration providing the base URL.
    """
    entries: List[str] = []

    # Home page and tag pages (rarely change).
    entries.append(f"  <url><loc>{_escape(_abs('/', config))}</loc><priority>1.0</priority></url>")
    for tag in sorted(tags):
        entries.append(
            f"  <url><loc>{_escape(_abs(f'/tags/{tag}/', config))}</loc><priority>0.6</priority></url>"
        )
    # Each post with its own lastmod.
    for post in posts:
        lastmod = post.iso_date or ""
        loc = _abs(post.url, config)
        lastmod_tag = f"<lastmod>{_escape(lastmod)}</lastmod>" if lastmod else ""
        entries.append(
            f"  <url><loc>{_escape(loc)}</loc>{lastmod_tag}<priority>0.8</priority></url>"
        )

    body = "\n".join(
        [
            "<?xml version=\"1.0\" encoding=\"UTF-8\"?>",
            "<urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">",
            *entries,
            "</urlset>",
        ]
    )
    return body + "\n"


def build_robots(config: SiteConfig) -> str:
    """Return a minimal ``robots.txt`` pointing crawlers at the sitemap."""
    return "\n".join(
        [
            "User-agent: *",
            "Allow: /",
            "",
            f"Sitemap: {_abs('/sitemap.xml', config)}",
            "",
        ]
    )