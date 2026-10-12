"""Feed and sitemap generators: real RSS/Atom/sitemap XML from Post objects."""

from __future__ import annotations

import datetime as dt
import xml.etree.ElementTree as ET

from blog.config import SiteConfig
from blog.parser import Post
from blog.rss import build_rss, build_atom
from blog.sitemap import build_sitemap, build_robots


def _sample_posts():
    return [
        Post(
            title="First Post",
            slug="first-post",
            date=dt.date(2024, 1, 1),
            author="Ada",
            tags=["python", "hi"],
            description="Opening entry.",
        ),
        Post(
            title="Second Post",
            slug="second-post",
            date=dt.date(2024, 2, 2),
            author="Bob",
            tags=["web"],
        ),
    ]


def test_rss_feed_is_valid_rss2():
    config = SiteConfig(title="T", site_url="https://blog.example")
    xml = build_rss(_sample_posts(), config)
    root = ET.fromstring(xml)
    assert root.tag == "rss"
    assert root.attrib["version"] == "2.0"
    channel = root.find("channel")
    assert channel.findtext("title") == "T"
    items = channel.findall("item")
    assert len(items) == 2
    # Each item exposes an absolute link and a title.
    links = [i.findtext("link") for i in items]
    assert "/posts/first-post/" in links[0]
    assert links[0].startswith("https://blog.example")
    categories = items[0].findall("category")
    assert {c.text for c in categories} == {"python", "hi"}


def test_atom_feed_is_valid_atom1():
    config = SiteConfig(title="T", site_url="https://blog.example")
    xml = build_atom(_sample_posts(), config)
    root = ET.fromstring(xml)
    # Atom uses a namespace.
    ns = {"a": "http://www.w3.org/2005/Atom"}
    assert root.tag == "{http://www.w3.org/2005/Atom}feed"
    entries = root.findall("a:entry", ns)
    assert len(entries) == 2
    assert entries[0].findtext("a:title", namespaces=ns) == "First Post"
    # Atom uses a stable tag: URI id referencing the post slug.
    eid = entries[0].find("a:id", ns).text
    assert eid.startswith("tag:") and eid.endswith(":first-post")
    # Author present from frontmatter.
    assert entries[0].findtext("a:author/a:name", namespaces=ns) == "Ada"
    # The alternate link is the absolute post URL.
    alt = entries[0].find("a:link", ns).attrib["href"]
    assert alt == "https://blog.example/posts/first-post/"


def test_sitemap_lists_posts_and_tags():
    config = SiteConfig(site_url="https://blog.example")
    tags = {"python": [_sample_posts()[0]]}
    xml = build_sitemap(_sample_posts(), tags, config)
    root = ET.fromstring(xml)
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    locs = {n.text for n in root.findall("./s:url/s:loc", ns)}
    assert "https://blog.example/posts/second-post/" in locs
    assert "https://blog.example/tags/python/" in locs
    assert "https://blog.example/" in locs  # home page


def test_robots_txt_mentions_sitemap():
    config = SiteConfig(site_url="https://blog.example")
    robots = build_robots(config)
    assert "sitemap.xml" in robots
    assert "User-agent" in robots