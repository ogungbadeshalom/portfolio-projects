"""Site configuration for the blog generator.

A small blog is described by a ``config.toml``-style set of values kept in a
plain settings file (``settings.cfg``) so we avoid pulling in TOML/YAML
parsers.  :class:`SiteConfig` bundles everything the builder needs and knows
how to read/write itself, defaulting gracefully when a key is missing.
"""

from __future__ import annotations

import datetime as _dt
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

# Default key order written to ``settings.cfg``.
_DEFAULTS: Dict[str, Any] = {
    "title": "My Blog",
    "description": "A tiny static blog built with Python.",
    "author": "Anonymous",
    "site_url": "https://example.com",
    "language": "en",
    "paginate": 10,
    "default_og_image": "",
}

_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")


class SiteConfig:
    """Carrier of every knobs the build needs.

    Attributes
    ----------
    title, description, author
        Human-facing metadata used across pages and the feeds.
    site_url:
        The absolute base URL (no trailing slash).  Used to build absolute
        feed/sitemap URLs.
    language:
        ``<html lang>`` value.
    paginate:
        Number of posts shown per index page.
    default_og_image:
        Optional path (relative to ``static/``) used as the OG image fallback.
    """

    def __init__(
        self,
        title: str = "My Blog",
        description: str = "A tiny static blog built with Python.",
        author: str = "Anonymous",
        site_url: str = "https://example.com",
        language: str = "en",
        paginate: int = 10,
        default_og_image: str = "",
    ) -> None:
        self.title = title
        self.description = description
        self.author = author
        self.site_url = site_url.rstrip("/")
        self.language = language
        self.paginate = max(1, int(paginate))
        self.default_og_image = default_og_image

    def base_url(self) -> str:
        """The absolute URL root (no trailing slash)."""
        return self.site_url

    # -- serialisation ------------------------------------------------------ #

    @classmethod
    def from_file(cls, path: Path) -> "SiteConfig":
        """Load a config from ``path``, falling back to defaults per key."""
        cfg = cls()
        if not path.is_file():
            return cfg
        values: Dict[str, str] = {}
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return cfg
        for line in text.splitlines():
            m = _KEY_RE.match(line.strip())
            if m:
                values[m.group(1)] = m.group(2).strip().strip('"')
        cfg.title = values.get("title", cfg.title)
        cfg.description = values.get("description", cfg.description)
        cfg.author = values.get("author", cfg.author)
        cfg.site_url = values.get("site_url", cfg.site_url).rstrip("/")
        cfg.language = values.get("language", cfg.language)
        try:
            cfg.paginate = max(1, int(values.get("paginate", cfg.paginate)))
        except ValueError:
            pass
        cfg.default_og_image = values.get("default_og_image", cfg.default_og_image)
        return cfg

    def save(self, path: Path) -> None:
        """Write the config to ``path`` in a friendly, commentable format."""
        lines = [
            "# Blog settings.  `site_url` has no trailing slash.",
            f'title = "{self.title}"',
            f'description = "{self.description}"',
            f'author = "{self.author}"',
            f'site_url = "{self.site_url}"',
            f'language = "{self.language}"',
            f"paginate = {self.paginate}",
            f'default_og_image = "{self.default_og_image}"',
            "",
        ]
        path.write_text("\n".join(lines), encoding="utf-8")

    @property
    def now(self) -> _dt.datetime:
        """Current UTC timestamp used for feed ``lastBuildDate``."""
        return _dt.datetime.now(_dt.timezone.utc)