"""QR Code Generator & Decoder.

A small, portfolio-grade library for generating QR codes and decoding them
from images.

Public API
----------
- :func:`generate`: turn text into a QR code rendered as bytes (PNG), an SVG
  string, ASCII art, or Unicode block art.
- :func:`decode`: read a QR code back from an image file and return its
  payload plus, when determinable, the format version and error-correction
  level.
"""

from __future__ import annotations

from .config import (
    ERROR_CORRECTION_CHOICES,
    ErrorCorrectionLevel,
    DEFAULT_EC_LEVEL,
    DEFAULT_SIZE,
    SUPPORTED_FORMATS,
)
from .generate import generate
from .decode import decode, DecodeResult, DecodeError

__all__ = [
    "generate",
    "decode",
    "DecodeResult",
    "DecodeError",
    "ErrorCorrectionLevel",
    "DEFAULT_EC_LEVEL",
    "DEFAULT_SIZE",
    "ERROR_CORRECTION_CHOICES",
    "SUPPORTED_FORMATS",
]

__version__ = "1.0.0"