"""QR decoding from image files.

This module wraps optional decoding backends and degrades gracefully:

1. **pyzbar** -- the canonical native decoder.  When importable, real decoding
   is used and returns the payload plus any version/EC metadata it exposes.
2. **OpenCV** (``cv2`` + ``QRCodeDetector``) -- a second native option used
   when pyzbar is missing but ``cv2`` is present.
3. **None** -- if neither native decoder is installed, the module still
   imports cleanly (so :func:`~qr.generate` keeps working) but ``decode``
   raises a clear :class:`DecodeError` telling the caller exactly how to
   enable real decoding.

The public API always returns a :class:`DecodeResult` or raises
:class:`DecodeError`; it never returns ``None``.  This keeps the CLI's
"decode errors return a friendly message, exit code 2" contract simple and
honest: on a machine without zbar the error is about the missing backend, not
a spurious "no QR found".

.. note::
   A dependency-free *decoder* (reconstructing payload bits from sampled
   pixels) is intentionally out of scope here -- that is non-trivial (mask
   unmasking + Reed-Solomon) and pyzbar/OpenCV are the standard way.  This
   module punts to them and degrades loudly rather than silently wrong.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Any, Optional

__all__ = ["decode", "DecodeResult", "DecodeError", "available_backend"]

# The error text surfaced when neither native backend is present.
_NO_BACKEND_HINT = (
    "QR decoding requires a native decoder. Install one with:\n"
    "  pip install pyzbar          (read any QR from images)\n"
    "  pip install opencv-python   (alternative)\n"
    "On Windows, pyzbar needs the zbar DLL (comes with `pip install pyzbar`).\n"
    "QR *generation* and this package import are unaffected."
)


class DecodeError(Exception):
    """Raised when a QR code cannot be located or decoded from an image."""


@dataclass
class DecodeResult:
    """Payload plus, when determinable, the code's format version + EC level.

    Attributes:
        data: The decoded text payload.
        version: QR format version (``None`` when the backend cannot tell).
        ec_level: Error-correction level string or ``None``.
        backend: Which decoder produced this result.
    """

    data: str
    version: Optional[int] = None
    ec_level: Optional[str] = None
    backend: str = "unknown"


# --------------------------------------------------------------------------- #
# Backend detection
# --------------------------------------------------------------------------- #


def _has_pyzbar() -> bool:
    try:
        import pyzbar.pyzbar  # type: ignore  # noqa: F401
    except Exception:
        return False
    return True


def _has_cv2() -> bool:
    try:
        import cv2  # type: ignore  # noqa: F401
    except Exception:
        return False
    return True


def available_backend() -> str:
    """Return the name of the first usable decode backend (``pyzbar``,
    ``opencv``, or ``none``)."""
    if _has_pyzbar():
        return "pyzbar"
    if _has_cv2():
        return "opencv"
    return "none"


# --------------------------------------------------------------------------- #
# Real decoders
# --------------------------------------------------------------------------- #


def _load_image(source):
    """Read ``source`` (image path or raw bytes) into a PIL image.

    Returns ``(PIL.Image, display_name)``.  Raises :class:`DecodeError` if the
    file cannot be opened as an image.
    """
    try:
        from PIL import Image  # type: ignore
    except Exception as exc:  # pragma: no cover - optional dep
        raise DecodeError(
            "Pillow is required to read image files for QR decoding. "
            "Install it with: pip install Pillow"
        ) from exc

    raw: bytes
    name: str
    if isinstance(source, (bytes, bytearray)):
        raw = bytes(source)
        name = "<bytes>"
    else:
        import os

        path = os.fspath(source)
        try:
            with open(path, "rb") as fh:
                raw = fh.read()
        except OSError as exc:
            raise DecodeError(f"could not read image file {path!r}: {exc}") from exc
        name = path

    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except Exception as exc:
        raise DecodeError(f"could not open image {name!r} as a QR source: {exc}") from exc
    return img, name


def _decode_pyzbar(source) -> DecodeResult:
    from pyzbar import pyzbar  # type: ignore

    img, name = _load_image(source)
    results = pyzbar.decode(img)
    if not results:
        raise DecodeError(f"no QR code found in {name!r}")

    result = results[0]
    data = result.data.decode("utf-8", "replace")
    # pyzbar does not expose a portable QR *version* or EC level on the
    # result object, so we leave those as None unless a future backend does.
    version: Optional[int] = None
    return DecodeResult(data=data, version=version, backend="pyzbar")


def _decode_cv2(source) -> DecodeResult:
    import cv2  # type: ignore
    import numpy as np  # type: ignore

    img, name = _load_image(source)
    arr = np.asarray(img.convert("RGB"))
    bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
    detector = cv2.QRCodeDetector()
    data, points, _ = detector.detectAndDecode(bgr)  # noqa: F841
    if not data:
        raise DecodeError(f"no QR code found in {name!r}")
    return DecodeResult(data=data, backend="opencv")


# --------------------------------------------------------------------------- #
# Public decode()
# --------------------------------------------------------------------------- #


def decode(
    source,
    *,
    use_pyzbar: bool = True,
    use_cv2: bool = True,
    error_on_missing_backend: bool = True,
) -> DecodeResult:
    """Decode a QR code from ``source`` (a path/str, a ``Path``, or bytes).

    Args:
        source: File path or raw image bytes (PNG, JPG, BMP, GIF, ...).
        use_pyzbar: Attempt the pyzbar backend first (default True).
        use_cv2: Fall back to OpenCV when pyzbar is absent (default True).
        error_on_missing_backend: When ``True`` (default) and no native
            backend is importable, raise :class:`DecodeError`.  When
            ``False``, return a ``DecodeResult`` with an empty ``data`` and
            ``backend="none"`` instead of raising.

    Returns:
        :class:`DecodeResult` with the decoded payload.

    Raises:
        DecodeError: When no QR is found, an image cannot be read, or (with
            no native backend installed) decoding is unavailable.
    """
    if use_pyzbar and _has_pyzbar():
        return _decode_pyzbar(source)
    if use_cv2 and _has_cv2():
        return _decode_cv2(source)

    if error_on_missing_backend:
        raise DecodeError(_NO_BACKEND_HINT)
    return DecodeResult(data="", backend="none")


decode_bytes = decode  # friendly alias (bytes or path both accepted)


def decode_image(source) -> DecodeResult:
    """Friendly alias for :func:`decode` used by the CLI from ``--decode``."""
    return decode(source)