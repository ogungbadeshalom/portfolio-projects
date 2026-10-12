"""Unicode block-art rendering for QR matrices.

Converts a boolean module matrix into compact Unicode block art where every
fullwidth glyph encodes a 2x2 block of modules. Because QR matrices (including
the quiet zone) always have an even dimension, the packing is lossless.
"""

from __future__ import annotations

from typing import List, Tuple

#: The canonical 16 Unicode block elements, indexed by bit pattern where
#: 0x1 = top-left, 0x2 = top-right, 0x4 = bottom-left, 0x8 = bottom-right.
BLOCK_CHARS: List[str] = [
    " ", "▘", "▝", "▀", "▖", "▌", "▞", "▛",
    "▗", "▚", "▐", "▜", "▄", "▙", "▟", "█",
]


def _even_pad(matrix: List[List[bool]]) -> List[List[bool]]:
    """Return ``matrix`` with a trailing light row/column if its dimension is
    odd, so the 2x1 block packing always has an even dimension.

    QR matrices can be odd-sized (e.g. ``21 + 2*4 = 29`` for version 1 with a
    4-module quiet zone), so we pad with light modules rather than fail.
    """
    n = len(matrix)
    if n % 2 == 0:
        return matrix
    padded = [row + [False] for row in matrix]
    padded.append([False] * (n + 1))
    return padded


def terminal_render(matrix: List[List[bool]]) -> str:
    """Render a module matrix as Unicode block art.

    Each character packs a 2x1 (rows) x 2 (columns) block of modules. The
    rendered art reads as roughly square in a typical terminal because the
    fullwidth glyphs are about twice as wide as they are tall.

    Args:
        matrix: The module matrix (``True`` = dark).  Odd dimensions are
            padded with a light row and column before rendering.

    Returns:
        A multi-line string of block characters, no trailing blank line.
    """
    matrix = _even_pad(matrix)
    n = len(matrix)
    lines: List[str] = []
    for r in range(0, n, 2):
        top_row = matrix[r]
        bottom_row = matrix[r + 1]
        chars: List[str] = []
        for c in range(0, n, 2):
            top = (top_row[c], top_row[c + 1])
            bottom = (bottom_row[c], bottom_row[c + 1])
            chars.append(block_char(top, bottom))
        lines.append("".join(chars))
    return "\n".join(lines)


def block_char(top: Tuple[bool, bool], bottom: Tuple[bool, bool]) -> str:
    """Return the Unicode block character for a 2x2 module block.

    Args:
        top: ``(left, right)`` dark flags for the upper row.
        bottom: ``(left, right)`` dark flags for the lower row.

    Returns:
        The block element character encoding that combination.
    """
    index = 0
    if top[0]:
        index |= 0x1
    if top[1]:
        index |= 0x2
    if bottom[0]:
        index |= 0x4
    if bottom[1]:
        index |= 0x8
    return BLOCK_CHARS[index]


__all__ = ["terminal_render", "block_char", "BLOCK_CHARS"]