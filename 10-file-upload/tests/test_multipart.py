"""Tests for the chunked multipart upload flow (init/part/complete)."""
from __future__ import annotations

from fastapi.testclient import TestClient


def test_multipart_flow(client: TestClient) -> None:
    init = client.post("/upload/init", params={"filename": "big.bin"})
    assert init.status_code == 201
    upload_id = init.json()["upload_id"]

    parts = [b"part-one----", b"part-two----"]
    for chunk in parts:
        r = client.post(f"/upload/{upload_id}/part", content=chunk)
        assert r.status_code == 200
        assert r.json()["size"] == len(chunk)

    complete = client.post(f"/upload/{upload_id}/complete")
    assert complete.status_code == 201
    body = complete.json()
    assert len(body["hash"]) == 128  # blake2b (64-byte) hex digest
    assert body["size"] == sum(len(p) for p in parts)
    assert body["filename"] == "big.bin"
    assert body["mime"] == "text/plain"  # ASCII content sniffed from bytes

    # The assembled file must be recoverable via a signed download.
    dl = client.get(f"/files/{body['hash']}/url")
    assert dl.status_code == 200
    signed = dl.json()["url"]
    # Fetch with the signed query.
    from urllib.parse import urlsplit, parse_qs

    qs = parse_qs(urlsplit(signed).query)
    resp = client.get(f"/files/{body['hash']}?expires={qs['expires'][0]}&sig={qs['sig'][0]}")
    assert resp.content == b"part-one----part-two----"


def test_upload_part_missing_upload_404(client: TestClient) -> None:
    r = client.post("/upload/does-not-exist/part", content=b"x")
    assert r.status_code == 404


def test_complete_without_parts_400(client: TestClient) -> None:
    init = client.post("/upload/init")
    upload_id = init.json()["upload_id"]
    r = client.post(f"/upload/{upload_id}/complete")
    assert r.status_code == 400


def test_complete_missing_upload_404(client: TestClient) -> None:
    assert client.post("/upload/nope/complete").status_code == 404