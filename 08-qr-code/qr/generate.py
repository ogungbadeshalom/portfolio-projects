"""QR code generation.

Two backends are supported:

- The third-party :mod:`qrcode` package, when importable (the preferred path).
- A compact built-in encoder in :mod:`qr._encoder` as an automatic fallback.

Both backends expose the same two things the rest of the package needs: a
boolean module matrix (with the quiet zone included) and ``(version,
ec_level)`` metadata. Choosing the backend happens once at import time.
"""

from __future__ import annotations

import io
from typing import Optional, Tuple

from . import config
from .config import ErrorCorrectionLevel, qrcode_ec_value

#: ``True`` when the third-party ``qrcode`` package is available.
HAS_QRCODE_LIB = False
try:  # pragma: no cover - exercised only when the optional dep is present
    import qrcode
    import qrcode.constants

    HAS_QRCODE_LIB = True
except ImportError:  # pragma: no cover - exercised only when absent
    HAS_QRCODE_LIB = False

class MatrixResult:
    """A QR code's module matrix plus its version and EC-level metadata.

    Attributes:
        matrix: A square list-of-lists of bool (``True`` = dark module),
            including the quiet-zone border.
        version: The QR format version (1..10 here, larger under the lib).
        ec_level: The :class:`~qr.config.ErrorCorrectionLevel` label.
    """

    __slots__ = ("matrix", "version", "ec_level")

    def __init__(self, matrix: list, version: int, ec_level: str) -> None:
        self.matrix = matrix
        self.version = version
        self.ec_level = ec_level


def _make_matrix_with_lib(data: str, ec_level: ErrorCorrectionLevel) -> MatrixResult:
    """Build a matrix using the third-party ``qrcode`` package."""
    import qrcode
    import qrcode.constants

    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode_ec_value(ec_level),
        box_size=1,
        border=config.DEFAULT_BORDER,
    )
    qr.add_data(data)
    qr.make(fit=True)
    version = int(qr.version) if hasattr(qr, "version") and qr.version else 1
    return MatrixResult(matrix=qr.get_matrix(), version=version, ec_level=ec_level.value)


def _make_matrix_fallback(data: str, ec_level: ErrorCorrectionLevel) -> MatrixResult:
    """Build a matrix using our built-in encoder in :mod:`qr._encoder`."""
    from . import _encoder

    matrix, version, ec = _encoder.make_matrix(data, ec_level=ec_level.value)
    return MatrixResult(matrix=matrix, version=version, ec_level=ec)


_get_matrix_backend = _make_matrix_with_lib if HAS_QRCODE_LIB else _make_matrix_fallback


def _matrix_for(data: str, ec_level: ErrorCorrectionLevel) -> MatrixResult:
    """Return a :class:`MatrixResult` for ``data`` at ``ec_level``."""
    return _get_matrix_backend(data, ec_level)


def generate(
    data: str,
    format: str = "png",
    size: int = config.DEFAULT_SIZE,
    ec_level: ErrorCorrectionLevel | str = config.DEFAULT_EC_LEVEL,
    border: int = config.DEFAULT_BORDER,
) -> bytes | str:
    """Generate a QR code for ``data`` in the requested format.

    The function never touches disk; callers decide where (if anywhere) the
    result is written. PNG and SVG return ``bytes`` (SVG as UTF-8 bytes); the
    ASCII and terminal formats return ``str`` of rendered art.

    Args:
        data: The text to encode (up to the QR capacity for the chosen level).
        format: One of ``png``, ``svg``, ``ascii`` or ``terminal``.
        size: Pixel dimension for raster output (PNG). Ignored for vectors/art.
        ec_level: An :class:`~qr.config.ErrorCorrectionLevel` or its string
            value (``L``/``M``/``Q``/``H``).
        border: Quiet-zone width in modules.

    Returns:
        ``bytes`` for ``png``/``svg``; ``str`` for ``ascii``/``terminal``.

    Raises:
        ValueError: If ``format`` or ``ec_level`` is unsupported, or the input
            is too large.
    """
    fmt = config.normalize_format(format)
    level = config.ErrorCorrectionLevel(ec_level) if isinstance(ec_level, str) else ec_level
    matrix = _matrix_for(data, level)

    from . import formats  # import late to avoid a circular import at load time

    if fmt == "png":
        return formats.png_bytes(matrix.matrix, size=size)
    if fmt == "svg":
        return formats.svg_bytes(matrix.matrix)
    if fmt == "ascii":
        return formats.ascii_render(matrix.matrix)
    return formats.terminal_render(matrix.matrix)


def generate_pil(matrix: list, size: int = config.DEFAULT_SIZE, scale: Optional[int] = None):
    """Render a module matrix to a :class:`PIL.Image.Image`.

    Used internally for PNG output and available so callers can customise the
    image (e.g. logo embedding) before saving.

    Args:
        matrix: The boolean module matrix.
        size: Desired output width/height in pixels.
        scale: Optional exact pixels-per-module; overrides ``size``.

    Returns:
        A :class:`PIL.Image.Image` in mode ``"1"`` (black on white).
    """
    from PIL import Image

    n = len(matrix)
    if scale is not None and scale > 0:
        final = n * scale
    else:
        final = size
    module = max(1, final // n)
    img = Image.new("1", (n * module, n * module), 1)  # 1 = white
    pixels = img.load()
    for r in range(n):
        for c in range(n):
            if matrix[r][c]:
                for dy in range(module):
                    for dx in range(module):
                        pixels[c * module + dx, r * module + dy] = 0  # dark
    return img


def png_bytes(matrix: list, size: int) -> bytes:
    """Encode a matrix as PNG ``bytes`` via Pillow.

    Args:
        matrix: The boolean module matrix.
        size: Desired output width/height in pixels.

    Returns:
        The raw PNG file bytes.
    """
    img = generate_pil(matrix, size=size)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def svg_bytes(matrix: list) -> bytes:
    """Encode a matrix as a minimal, self-contained SVG document (bytes).

    Args:
        matrix: The boolean module matrix.

    Returns:
        The SVG document as UTF-8 encoded ``bytes``.
    """
    from . import formats

    return formats.svg_bytes(matrix)


def current_backend_name() -> str:
    """Return the name of the active generation backend for diagnostics."""
    return "qrcode" if HAS_QRCODE_LIB else "builtin (_encoder)"


__all__ = ["generate", "png_bytes", "svg_bytes", "current_backend_name", "MatrixResult"]