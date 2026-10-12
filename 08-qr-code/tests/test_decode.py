"""Round-trip decode tests.

When pyzbar (or OpenCV) is available we do a real generate->save->decode
round-trip.  When it is not, we verify that decode degrades with a clear
:class:`DecodeError` and that generation/import still work -- so the suite is
green either way and never flaky.
"""

from __future__ import annotations

import os
import tempfile

import pytest

import qr
from qr.decode import DecodeError, available_backend

HAS_NATIVE = available_backend() != "none"


def _write_png(payload: str, size: int = 300) -> str:
    data = qr.generate(payload, size=size)
    fd, path = tempfile.mkstemp(suffix=".png")
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    return path


@pytest.mark.skipif(not HAS_NATIVE, reason="no pyzbar/OpenCV installed")
def test_roundtrip_generate_then_decode():
    payload = "https://example.com/portfolio-roundtrip"
    path = _write_png(payload)
    try:
        result = qr.decode(path)
        assert result.data == payload
    finally:
        os.unlink(path)


@pytest.mark.skipif(not HAS_NATIVE, reason="no pyzbar/OpenCV installed")
def test_roundtrip_from_bytes():
    payload = "hello bytes decode"
    png = qr.generate(payload)
    result = qr.decode(png)  # accepts raw bytes
    assert result.data == payload


@pytest.mark.skipif(not HAS_NATIVE, reason="no pyzbar/OpenCV installed")
def test_decode_short_alphanumeric_string():
    payload = "ROUNDTRIP-42"
    path = _write_png(payload)
    try:
        assert qr.decode(path).data == payload
    finally:
        os.unlink(path)


def test_decode_missing_file_raises_clean_error():
    with pytest.raises(DecodeError):
        qr.decode(os.path.join(tempfile.gettempdir(), "definitely_missing_1234.png"))


def test_decode_invalid_image_raises_clean_error():
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as fh:
        fh.write(b"this is not a real image")
        path = fh.name
    try:
        with pytest.raises(DecodeError):
            qr.decode(path)
    finally:
        os.unlink(path)


@pytest.mark.skipif(HAS_NATIVE, reason="native backend present")
def test_generation_still_works_without_native_decode():
    # Even with no decode backend, generation and import must keep working.
    assert isinstance(qr.generate("still works"), bytes)