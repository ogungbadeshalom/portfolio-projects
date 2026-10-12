"""Route tests for simple upload and content-addressable dedup.

Uses FastAPI's ``TestClient`` with an isolated temp storage directory.
"""
from __future__ import annotations

from fastapi.testclient import TestClient
from httpx import Response


def _upload(client: TestClient, data: bytes, filename: str = "photo.png") -> Response:
    return client.post(
        "/upload",
        files={"file": (filename, data, "image/png")},
    )


def test_upload_png(client: TestClient) -> None:
    content = (
        b"\x89PNG\r\n\x1a\n" + b"\x00" * 8 + b"IHDR" + b"\x00" * 64
    )
    resp = _upload(client, content)
    assert resp.status_code == 201
    body = resp.json()
    assert body["mime"] == "image/png"
    assert body["size"] == len(content)
    assert len(body["hash"]) == 128  # blake2b (64-byte) hex digest
    assert body["url"] == f"/files/{body['hash']}"
    assert body["filename"] == "photo.png"


def test_upload_dedup_same_content_same_hash(client: TestClient, storage_dir) -> None:
    content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
    h1 = _upload(client, content).json()["hash"]
    # Same bytes again → same hash; content-addressable storage collides.
    resp2 = _upload(client, content)
    assert resp2.json()["hash"] == h1
    # Exactly one physical copy exists for the hash (no duplicate writes).
    blob = storage_dir / "files" / h1[:2] / h1
    assert blob.is_file()
    assert blob.read_bytes() == content


def test_upload_sets_mime_from_bytes_not_extension(client: TestClient) -> None:
    # Filename lies but bytes are PNG → MIME from content.
    content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24
    resp = _upload(client, content, filename="fake.txt")
    assert resp.json()["mime"] == "image/png"


def test_upload_rejects_disallowed_type(client: TestClient) -> None:
    # A gzip archive (MIME application/gzip) is not in the default whitelist
    # → rejected server-side from *content*, not any client claim.
    blob = b"\x1f\x8b" + b"\x08\x00" + b"\x00" * 64
    resp = client.post(
        "/upload", files={"file": ("archive.gz", blob, "application/gzip")}
    )
    assert resp.status_code == 415


def test_upload_multiple_files(client: TestClient) -> None:
    a = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
    b_txt = b"hello plain text"
    resp = client.post(
        "/upload",
        files=[
            ("file", ("a.png", a, "image/png")),
            ("file", ("b.txt", b_txt, "text/plain")),
        ],
    )
    assert resp.status_code == 201
    results = resp.json()["results"]
    assert len(results) == 2
    assert {r["mime"] for r in results} == {"image/png", "text/plain"}