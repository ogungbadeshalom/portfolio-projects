"""Package-level tests: importable, all four formats, backends."""

from __future__ import annotations

import io

import pytest

import qr
from qr import decode
from qr.decode import DecodeResult, available_backend


def test_package_imports_and_exports():
    # The critical import fix: ``qr`` must import even though decode.py exists
    # and relies on optional native backends.
    assert hasattr(qr, "generate")
    assert hasattr(qr, "decode")
    assert callable(qr.generate)


def test_generate_png_returns_valid_png_bytes():
    png = qr.generate("hello world")
    assert isinstance(png, bytes)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"          # PNG magic
    assert len(png) > 100


def test_generate_png_is_openable_by_pillow():
    from PIL import Image

    png = qr.generate("hello world", size=300)
    img = Image.open(io.BytesIO(png))
    assert img.format == "PNG"
    # Size is the largest multiple of the QR module count that fits in the
    # requested 300px (here a 29-module code -> 290px), always square.
    width, height = img.size
    assert width == height
    assert 0 < width <= 300
    assert width % 10 == 0


def test_generate_svg_bytes():
    svg = qr.generate("hello", format="svg")
    assert isinstance(svg, bytes)
    assert b"<svg" in svg
    assert b"xmlns" in svg


def test_generate_ascii_string():
    art = qr.generate("hello", format="ascii")
    assert isinstance(art, str)
    assert "#" in art
    assert " " in art


def test_generate_terminal_handles_odd_matrix():
    # The QR matrix (quiet zone included) is odd-sized for some versions; the
    # block-art renderer must pad rather than raise.
    art = qr.generate("hello", format="terminal")
    assert isinstance(art, str)
    assert len(art.splitlines()) >= 5


def test_all_error_correction_levels_accepted():
    for level in ("L", "M", "Q", "H"):
        png = qr.generate("data", ec_level=level)
        assert isinstance(png, bytes)


def test_unsupported_format_raises_valueerror():
    with pytest.raises(ValueError):
        qr.generate("x", format="bmp")


def test_backend_reported():
    name = available_backend()
    assert name in ("pyzbar", "opencv", "none")


def test_decode_result_dataclass():
    r = DecodeResult(data="abc", version=None, backend="test")
    assert r.data == "abc"