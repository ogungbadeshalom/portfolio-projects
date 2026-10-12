"""Unit tests for MIME detection, filename sanitization, and limits."""
from __future__ import annotations

import pytest

from upload.limits import sanitize_filename
from upload.mime import detect_mime


def _png() -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"\x00" * 8 + b"IHDRpayload"


def _jpeg() -> bytes:
    return b"\xff\xd8\xff\xe0" + b"\x00" * 16


def test_detect_png():
    assert detect_mime(_png(), "photo.png") == "image/png"


def test_detect_jpeg():
    assert detect_mime(_jpeg(), "shot.jpg") == "image/jpeg"


def test_detect_pdf():
    assert detect_mime(b"%PDF-1.7\n...", "doc.pdf") == "application/pdf"


def test_detect_webp():
    assert (
        detect_mime(b"RIFF\x10\x00\x00\x00WEBPVP8 " + b"\x00" * 8, "a.webp")
        == "image/webp"
    )


def test_detect_zip_matches_extension():
    assert detect_mime(b"PK\x03\x04" + b"\x00" * 16, "bundle.zip") == "application/zip"


def test_detect_docx_from_zip():
    assert (
        detect_mime(b"PK\x03\x04" + b"\x00" * 16, "report.docx")
        == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )


def test_detect_json():
    assert detect_mime(b'{"a": 1}', "data.json") == "application/json"


def test_detect_text_plain():
    assert detect_mime(b"just some plain text", "notes.txt") == "text/plain"


def test_detect_unknown_binary():
    assert detect_mime(b"\x01\x02\x03\x04\xff\xfe", "blob.bin") == "application/octet-stream"


def test_detect_empty():
    assert detect_mime(b"", "empty") == "application/octet-stream"


def test_sanitize_removes_traversal():
    assert sanitize_filename("../../etc/passwd") == "passwd"
    assert "\\" not in sanitize_filename("..\\..\\evil.exe")
    assert "/" not in sanitize_filename("../a/b.txt")


def test_sanitize_removes_null_bytes():
    assert "\x00" not in sanitize_filename("file\x00name.txt")


def test_sanitize_falls_back():
    assert sanitize_filename("..") == "upload"
    assert sanitize_filename("") == "upload"


@pytest.mark.parametrize(
    "name,expected",
    [
        ("a/b/c.txt", "c.txt"),
        ("C:\\dir\\file.pdf", "file.pdf"),
        ("simple name.txt", "simple name.txt"),
    ],
)
def test_sanitize_basename(name, expected):
    assert sanitize_filename(name) == expected