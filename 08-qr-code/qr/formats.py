"""Output format renderers.

Turns a boolean QR module matrix into one of the supported deliverables:
PNG bytes, SVG bytes, plain ASCII art, or rich Unicode-block terminal art.
Callers in :mod:`qr.generate` dispatch here; the functions never write files
themselves.
"""

from __future__ import annotations

import io
from typing import List

from . import config
from .ascii_art import terminal_render as _ascii_terminal_render, block_char, BLOCK_CHARS

#: Re-exported for convenience / backwards-friendly API.
_BLOCK_CHARS = BLOCK_CHARS


# ---------------------------------------------------------------------------
# Raster / SVG
# ---------------------------------------------------------------------------


def png_bytes(matrix: List[List[bool]], size: int = config.DEFAULT_SIZE) -> bytes:
    """Render a module matrix to PNG ``bytes`` using Pillow.

    Args:
        matrix: The boolean module matrix (quiet zone included).
        size: Desired width/height in pixels.

    Returns:
        Raw PNG file bytes.

    Raises:
        ImportError: If Pillow is not installed.
    """
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise ImportError(
            "PNG output requires Pillow. Install it with: pip install Pillow"
        ) from exc

    n = len(matrix)
    module = max(1, size // n)
    img = Image.new("1", (n * module, n * module), color=1)  # 1 = white
    pixels = img.load()
    for r in range(n):
        for c in range(n):
            if matrix[r][c]:
                for dy in range(module):
                    for dx in range(module):
                        pixels[c * module + dx, r * module + dy] = 0
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def svg_bytes(matrix: List[List[bool]]) -> bytes:
    """Render a module matrix to a minimal, self-contained SVG document.

    Uses small ``<rect>`` elements for the dark modules and omits the quiet
    zone from sizing (it is pushed by a translated group) so the SVG scales to
    the exact symbol size.

    Args:
        matrix: The boolean module matrix.

    Returns:
        The SVG document as UTF-8 ``bytes``.
    """
    n = len(matrix)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {n} {n}" '
        f'width="{n * 8}" height="{n * 8}" shape-rendering="crispEdges">',
        f'<rect width="100%" height="100%" fill="#ffffff"/>',
    ]
    for r in range(n):
        for c in range(n):
            if matrix[r][c]:
                parts.append(f'<rect x="{c}" y="{r}" width="1" height="1" fill="#000000"/>')
    parts.append("</svg>")
    return "".join(parts).encode("utf-8")


# ---------------------------------------------------------------------------
# Text art
# ---------------------------------------------------------------------------


def ascii_render(matrix: List[List[bool]]) -> str:
    """Render a module matrix as plain, monospace ASCII (``#`` / space).

    One matrix module maps to one character. Intended for terminals and
    copy-paste into plain-text contexts.

    Args:
        matrix: The boolean module matrix.

    Returns:
        A multi-line string without a trailing blank line.
    """
    lines = ["".join("#" if cell else " " for cell in row) for row in matrix]
    return "\n".join(lines)


def terminal_render(matrix: List[List[bool]]) -> str:
    """Render a module matrix as widely-spaced Unicode block art.

    Delegates to :func:`qr.ascii_art.terminal_render`, which pads odd-sized
    matrices so the 2:1 packing stays even-dimensioned.

    Args:
        matrix: The boolean module matrix.

    Returns:
        A multi-line string of Unicode block characters.
    """
    return _ascii_terminal_render(matrix)


def _block_char(top: tuple, bottom: tuple) -> str:
    """Map a 2x2 module block to its Unicode block character index.

    Each pair ``(left, right)`` of booleans becomes a bit; the four bits
    combine to an index into ``BLOCK_CHARS``.

    Args:
        top: ``(left, right)`` dark flags for the upper row.
        bottom: ``(left, right)`` dark flags for the lower row.

    Returns:
        A single fullwidth block character.
    """
    return block_char(top, bottom)


def format_bytes(matrix: List[List[bool]], fmt: str, size: int) -> bytes:
    """Return the raw bytes for a given format (used by tests / diagnostics).

    Args:
        matrix: The boolean module matrix.
        fmt: One of ``png`` or ``svg``.
        size: Pixel size for PNG.

    Returns:
        The file bytes for the requested raster/vector format.

    Raises:
        ValueError: For any format other than ``png`` or ``svg``.
    """
    fmt = config.normalize_format(fmt)
    if fmt == "png":
        return png_bytes(matrix, size=size)
    if fmt == "svg":
        return svg_bytes(matrix)
    raise ValueError(f"format_bytes only handles raster/vector formats, got {fmt!r}")


__all__ = [
    "png_bytes",
    "svg_bytes",
    "ascii_render",
    "terminal_render",
    "_block_char",
    "format_bytes",
]