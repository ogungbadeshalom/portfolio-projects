"""RSS 2.0 and Atom 1.0 feed generation.

Both feeds are produced from the same ``Post`` list and the site
:class:`~blog.config.SiteConfig`.  We build the XML by hand (with rigorous
escaping) rather than depending on a feed library so the module works with zero
third-party installs.
"""

from __future__ import annotations

import datetime as _dt
from email.utils import format_datetime, formatdate
from typing import List, Sequence

from .config import SiteConfig
from .parser import Post


def _escape(text: str) -> str:
    """XML-escape attribute/text content.

    ``&`` must come first so previously-escaped entities survive; the other
    escapes guard the XML reserved characters.
    """
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _abs(post_url: str, config: SiteConfig) -> str:
    """Turn a site-relative URL (``/posts/x/``) into an absolute one."""
    return f"{config.base_url()}{post_url.rstrip('/')}/" if post_url else config.base_url()


def _pub_date_string(ts: _dt.datetime) -> str:
    """RFC 2822 date, mandate of RSS ``<pubDate>``."""
    return formatdate(ts.timestamp(), localtime=False)


def _rss_last_build(now: _dt.datetime) -> str:
    return format_datetime(now)


def build_rss(posts: Sequence[Post], config: SiteConfig) -> str:
    """Return a complete RSS 2.0 document as a string.

    Parameters
    ----------
    posts:
        Posts, newest first.
    config:
        Site configuration (title, URL, author, description).
    """
    now = _dt.datetime.now(_dt.timezone.utc)
    items: List[str] = []
    for post in posts:
        link = _abs(post.url, config)
        guid = link
        items.append(
            "\n".join(
                [
                    "    <item>",
                    f"      <title>{_escape(post.title)}</title>",
                    f"      <link>{_escape(link)}</link>",
                    f"      <guid isPermaLink=\"true\">{_escape(guid)}</guid>",
                    _rss_date_item(post),
                    f"      <description>{_escape(post.description or post.body_html[:400])}</description>",
                    *(_tag_entries(post.tags)),
                    f"      <author>{_escape(post.author or config.author)}</author>",
                    "    </item>",
                ]
            )
        )
    body = "\n".join(
        [
            "<rss version=\"2.0\" xmlns:atom=\"http://www.w3.org/2005/Atom\" xmlns:dc=\"http://purl.org/dc/elements/1.1/\">",
            "  <channel>",
            f"    <title>{_escape(config.title)}</title>",
            f"    <link>{_escape(config.base_url())}</link>",
            f"    <description>{_escape(config.description)}</description>",
            f"    <language>{_escape(config.language)}</language>",
            f"    <lastBuildDate>{_rss_last_build(now)}</lastBuildDate>",
            f"    <atom:link href=\"{_escape(_abs('/feed.xml', config))}\" rel=\"self\" type=\"application/rss+xml\"/>",
            "    <generator>blog-markdown-generator/1.0</generator>",
            *items,
            "  </channel>",
            "</rss>",
        ]
    )
    return "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n" + body


def _tag_entries(tags: List[str]) -> List[str]:
    return [f'      <category>{_escape(t)}</category>' for t in tags]


def _rss_date_item(post: Post) -> str:
    if not post.date:
        return f"      <pubDate>{formatdate(timeval=0)}</pubDate>"
    d = _dt.datetime.combine(post.date, _dt.time.min, tzinfo=_dt.timezone.utc)
    return f"      <pubDate>{formatdate(d.timestamp(), localtime=False)}</pubDate>"


def build_atom(posts: Sequence[Post], config: SiteConfig) -> str:
    """Return a complete Atom 1.0 document as a string.

    Parameters
    ----------
    posts:
        Posts, newest first.
    config:
        Site configuration.
    """
    now = _dt.datetime.now(_dt.timezone.utc)
    updated = max(
        ((post.date and _dt.datetime.combine(post.date, _dt.time.min, tzinfo=_dt.timezone.utc)) or now)
        for post in posts
    ) if posts else now

    entries: List[str] = []
    for post in posts:
        link = _abs(post.url, config)
        entry_updated = (
            _dt.datetime.combine(post.date, _dt.time.min, tzinfo=_dt.timezone.utc)
            if post.date
            else now
        )
        entries.append(
            "\n".join(
                [
                    "  <entry>",
                    f"    <title>{_escape(post.title)}</title>",
                    f"    <link href=\"{_escape(link)}\" rel=\"alternate\" type=\"text/html\"/>",
                    f"    <id>tag:{config.base_url()},1:{post.slug}</id>",
                    f"    <updated>{_atom_ts(entry_updated)}</updated>",
                    *(_atom_authors(post, config)),
                    *(_atom_tags(post)),
                    f"    <summary type=\"html\">{_escape(post.description or '')}</summary>",
                    f"    <content type=\"html\">{_escape(post.body_html)}</content>",
                    "  </entry>",
                ]
            )
        )

    body = "\n".join(
        [
            "<?xml version=\"1.0\" encoding=\"UTF-8\"?>",
            "<feed xmlns=\"http://www.w3.org/2005/Atom\">",
            f"  <title>{_escape(config.title)}</title>",
            f"  <subtitle>{_escape(config.description)}</subtitle>",
            f"  <id>tag:{config.base_url()},1:feed</id>",
            f"  <updated>{_atom_ts(updated)}</updated>",
            f"  <link href=\"{_escape(config.base_url())}\" rel=\"alternate\" type=\"text/html\"/>",
            f"  <link href=\"{_escape(_abs('/atom.xml', config))}\" rel=\"self\" type=\"application/atom+xml\"/>",
            f"  <author><name>{_escape(config.author)}</name></author>",
            *entries,
            "</feed>",
        ]
    )
    return body


def _atom_ts(ts: _dt.datetime) -> str:
    """Atom requires an UTC ``YYYY-MM-DDTHH:MM:SSZ`` timestamp."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=_dt.timezone.utc)
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def _atom_authors(post: Post, config: SiteConfig) -> List[str]:
    name = _escape(post.author or config.author)
    return [f"    <author><name>{name}</name></author>"]


def _atom_tags(post: Post) -> List[str]:
    return [f'    <category term="{_escape(t)}"/>' for t in post.tags]


# Backwards / convenience alias used by introspection examples.
rss_doc = build_rss