"""Tests for signed-URL issuance, authenticated download, and delete."""
from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient


def _store_png(client: TestClient, content: bytes | None = None) -> str:
    content = content or (b"\x89PNG\r\n\x1a\n" + b"\x00" * 40)
    resp = client.post(
        "/upload", files={"file": ("a.png", content, "image/png")}
    )
    assert resp.status_code == 201
    return resp.json()["hash"]


def _signed_query(client: TestClient, hash_: str) -> tuple[str, str]:
    resp = client.get(f"/files/{hash_}/url?expires=3600")
    assert resp.status_code == 200
    url = resp.json()["url"]
    parts = urlsplit(url)
    qs = parse_qs(parts.query)
    return qs["expires"][0], qs["sig"][0]


def test_issue_signed_url(client: TestClient) -> None:
    hash_ = _store_png(client)
    resp = client.get(f"/files/{hash_}/url?expires=600")
    assert resp.status_code == 200
    body = resp.json()
    assert body["hash"] == hash_
    assert body["expires_in"] == 600
    assert body["url"].startswith(f"/files/{hash_}?")
    assert "sig=" in body["url"]


def test_download_with_valid_signature(client: TestClient) -> None:
    content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
    hash_ = _store_png(client, content)
    expires, sig = _signed_query(client, hash_)
    resp = client.get(f"/files/{hash_}?expires={expires}&sig={sig}")
    assert resp.status_code == 200
    assert resp.content == content
    assert resp.headers["content-type"].startswith("image/png")


def test_download_requires_signature(client: TestClient) -> None:
    hash_ = _store_png(client)
    resp = client.get(f"/files/{hash_}")
    assert resp.status_code == 401


def test_download_rejects_tampered_signature(client: TestClient) -> None:
    hash_ = _store_png(client)
    expires, _ = _signed_query(client, hash_)
    resp = client.get(f"/files/{hash_}?expires={expires}&sig=deadbeef")
    assert resp.status_code == 401


def test_download_rejects_expired_signature(client: TestClient) -> None:
    hash_ = _store_png(client)
    # A signed URL that already expired (expires in the past).
    resp = client.get(
        f"/files/{hash_}/url?expires=1",  # min allowed by validation
    )
    # Fetch a URL with a past expiry by querying with expires=1 then waiting
    # would be flaky; instead craft one directly:
    from upload.signed_url import _sig

    past = int(__import__("time").time()) - 100
    bad_sig = _sig("dev-insecure-secret-change-me", hash_, past)
    rejected = client.get(f"/files/{hash_}?expires={past}&sig={bad_sig}")
    assert rejected.status_code == 401


def test_download_signed_for_wrong_hash_rejected(client: TestClient) -> None:
    h_a = _store_png(client, b"\x89PNG\r\n\x1a\n" + b"\x00" * 40)
    h_b = _store_png(client, b"\x89PNG\r\n\x1a\n" + b"\x00" * 41)
    expires, sig = _signed_query(client, h_a)
    resp = client.get(f"/files/{h_b}?expires={expires}&sig={sig}")
    assert resp.status_code == 401  # sig bound to a different hash


def test_delete_removes_file(client: TestClient) -> None:
    hash_ = _store_png(client)
    resp = client.delete(f"/files/{hash_}")
    assert resp.status_code == 204
    # File is gone: metadata gone and download now 404 (unknown hash).
    assert client.get(f"/files/{hash_}").status_code == 404


def test_delete_missing_is_404(client: TestClient) -> None:
    resp = client.delete("/files/" + "0" * 64)
    assert resp.status_code == 404


def test_range_request_returns_206(client: TestClient, storage_dir) -> None:
    content = b"\x89PNG\r\n\x1a\n" + bytes(range(256))
    hash_ = _store_png(client, content)
    expires, sig = _signed_query(client, hash_)
    resp = client.get(
        f"/files/{hash_}?expires={expires}&sig={sig}",
        headers={"Range": "bytes=0-9"},
    )
    assert resp.status_code == 206
    assert resp.content == content[0:10]
    assert resp.headers["content-range"] == f"bytes 0-9/{len(content)}"
    assert int(resp.headers["content-length"]) == 10