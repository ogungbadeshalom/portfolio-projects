"""Central configuration for the QR package.

Holds the default error-correction level, default image size, the set of
supported output formats, and a small type/constant set that the rest of the
package (and CLI) share so that defaults live in exactly one place.
"""

from __future__ import annotations

import enum
from typing import Dict, List

# ---------------------------------------------------------------------------
# Error correction levels
# ---------------------------------------------------------------------------


class ErrorCorrectionLevel(str, enum.Enum):
    """QR error-correction levels (fraction of the code recoverable).

    Attributes:
        L (:class:`str`): Recovers ~7% of codewords.
        M (:class:`str`): Recovers ~15% of codewords (default).
        Q (:class:`str`): Recovers ~25% of codewords.
        H (:class:`str`): Recovers ~30% of codewords.
    """

    L = "L"
    M = "M"
    Q = "Q"
    H = "H"


# The selection offered by the CLI, in a stable human-friendly order.
ERROR_CORRECTION_CHOICES: List[str] = ["H", "Q", "M", "L"]

DEFAULT_EC_LEVEL: ErrorCorrectionLevel = ErrorCorrectionLevel.M

#: Map a CLI/API level string to the ``qrcode`` library constant value.
QRCODE_EC_LEVELS: Dict[str, int] = {
    "L": 1,
    "M": 0,
    "Q": 3,
    "H": 2,
}

#: Map the ``qrcode`` constant value back to our enum.
_QRCODE_TO_NAME: Dict[int, str] = {v: k for k, v in QRCODE_EC_LEVELS.items()}


def qrcode_ec_value(level: ErrorCorrectionLevel | str) -> int:
    """Return the numeric EC constant expected by the ``qrcode`` library.

    Args:
        level: An :class:`ErrorCorrectionLevel` or its string value.

    Returns:
        The integer constant accepted by :class:`qrcode.QRCode`.

    Raises:
        ValueError: If ``level`` is not a recognised error-correction level.
    """
    name = level.value if isinstance(level, ErrorCorrectionLevel) else str(level).upper()
    if name not in QRCODE_EC_LEVELS:
        raise ValueError(
            f"Unknown error-correction level {level!r}; "
            f"expected one of {ERROR_CORRECTION_CHOICES}"
        )
    return QRCODE_EC_LEVELS[name]


def ec_level_from_qrcode_value(value: int) -> ErrorCorrectionLevel:
    """Translate a ``qrcode`` library EC constant back to our enum.

    Args:
        value: An integer returned by the ``qrcode`` library.

    Returns:
        The corresponding :class:`ErrorCorrectionLevel`.

    Raises:
        ValueError: If ``value`` does not map to a known level.
    """
    name = _QRCODE_TO_NAME.get(value)
    if name is None:
        raise ValueError(f"Unknown qrcode error-correction value {value!r}")
    return ErrorCorrectionLevel(name)


# ---------------------------------------------------------------------------
# Output formats
# ---------------------------------------------------------------------------

SUPPORTED_FORMATS: List[str] = ["png", "svg", "ascii", "terminal"]

#: Default pixel width/height for a rendered PNG image.
DEFAULT_SIZE: int = 300

#: Quiet-zone (finder-pattern border) width in modules, in line with the spec.
DEFAULT_BORDER: int = 4


def normalize_format(fmt: str | None) -> str:
    """Normalise a user-supplied format name to a canonical key.

    Args:
        fmt: A format value; ``None`` and ``"png"`` both mean PNG.

    Returns:
        The lower-cased, validated format name.

    Raises:
        ValueError: If ``fmt`` is not one of :data:`SUPPORTED_FORMATS`.
    """
    if fmt is None:
        return "png"
    normalized = str(fmt).lower()
    if normalized not in SUPPORTED_FORMATS:
        raise ValueError(
            f"Unsupported format {fmt!r}; choose from {SUPPORTED_FORMATS}"
        )
    return normalized