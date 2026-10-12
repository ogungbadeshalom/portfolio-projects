"""Open Graph image generation (best-effort).

:mod:`blog.og` renders a shareable 1200x630 PNG per post carrying the title,
author and site name.  It depends on **Pillow**; when Pillow is missing (or a
font cannot be loaded) the generator **skips gracefully**, logs a warning and
returns 0 -- ``blog build`` always completes.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Sequence

from .config import SiteConfig
from .parser import Post

OG_WIDTH = 1200
OG_HEIGHT = 630

# A tiny selection of common cross-platform fonts tried in order.
_FONT_CANDIDATES = [
    "DejaVuSans-Bold.ttf",
    "Arial Bold.ttf",
    "arialbd.ttf",
    "Arial.ttf",
    "DejaVuSans.ttf",
    "LiberationSans-Bold.ttf",
    "Verdana Bold.ttf",
    "verdana.ttf",
    "Helvetica.ttf",
]


def _find_font(size: int):
    """Return a usable font (resolved from candidate names) or ``None``."""
    try:
        from PIL import ImageFont  # type: ignore
    except ImportError:
        return None
    for name in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    # No system font available: Pillow falls back to its embedded default.
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # older Pillow has no size kwarg on load_default
        return ImageFont.load_default()
    except OSError:
        return None


def _wrap(text: str, font, max_width: int, draw) -> List[str]:
    """Wrap ``text`` into lines that fit ``max_width`` pixels."""
    words = text.split()
    lines: List[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=font) <= max_width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [text]


def generate_for_posts(static_dir: Path, posts: Sequence[Post], config: SiteConfig, dist_dir: Path) -> int:
    """Generate an OG image per post into ``dist_dir/assets/og/``.

    Returns the number of images written.  Never raises due to a missing
    Pillow or a rendering hiccup -- failures are swallowed and logged.

    Parameters
    ----------
    static_dir:
        Source ``static/`` directory (fonts pool; may be missing).
    posts:
        The posts being built.
    config:
        Site configuration for title/author text.
    dist_dir:
        Output directory; images land at ``dist_dir/assets/og/<slug>.png``.
    """
    try:
        from PIL import Image, ImageDraw  # type: ignore
    except ImportError:
        print("[og] Pillow not installed -- skipping Open Graph images")
        return 0

    title_font = _find_font(64) or _find_font(48)
    subtitle_font = _find_font(32) or _find_font(28)
    if title_font is None:
        print("[og] No usable font -- skipping Open Graph images")
        return 0

    out_dir = dist_dir / "assets" / "og"
    out_dir.mkdir(parents=True, exist_ok=True)

    written = 0
    for post in posts:
        try:
            _render_one(post, config, title_font, subtitle_font, out_dir)
            written += 1
        except Exception as exc:  # noqa: BLE001 -- never break a build
            print(f"[og] skipped {post.slug}: {exc}")
    return written


def _render_one(post: Post, config: SiteConfig, title_font, subtitle_font, out_dir: Path) -> None:
    from PIL import Image, ImageDraw  # type: ignore

    img = Image.new("RGB", (OG_WIDTH, OG_HEIGHT), color=(18, 22, 34))
    draw = ImageDraw.Draw(img)

    # Accent bar on the left.
    draw.rectangle([0, 0, 16, OG_HEIGHT], fill=(76, 145, 255))

    title_text = post.title or "Untitled"
    lines = _wrap(title_text, title_font, OG_WIDTH - 120, draw)[:3]
    y = 120
    for line in lines:
        draw.text((80, y), line, font=title_font, fill=(245, 247, 250))
        y += int(title_font.size * 1.2)

    footer = f"{config.title}  •  {post.author or config.author}"
    draw.text((80, OG_HEIGHT - 100), footer, font=subtitle_font, fill=(150, 165, 190))

    img.save(out_dir / f"{post.slug}.png", format="PNG")