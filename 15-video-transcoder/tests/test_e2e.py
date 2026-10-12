"""End-to-end tests: real video in through the API, transcoded files out."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from transcoder import config

from conftest import submit_video, wait_completed


def test_submit_creates_job_and_transcodes(app, source_video):
    """Submitting a real video yields a queued job that completes."""
    with TestClient(app) as client:
        data = submit_video(client, source_video, resolutions="480,720")
        jid = data["id"]
        assert data["status"] == "queued"
        assert data["resolutions"] == [480, 720]

        status = wait_completed(client, jid)
        assert status["status"] == "completed"
        assert status["progress_pct"] > 99.0

        # Job detail matches.
        detail = client.get(f"/api/jobs/{jid}").json()
        assert detail["filename"] == "source.mp4"
        assert len(detail["resolutions"]) == 2


def test_hls_thumbnail_and_segments_exist_on_disk(app, source_video):
    """The worker writes HLS playlists, segments, an mp4 and a thumbnail."""
    with TestClient(app) as client:
        jid = submit_video(client, source_video, resolutions="480,720")["id"]
        wait_completed(client, jid)

        job_dir = config.OUTPUT_DIR / jid
        for res in ("480p", "720p"):
            dir_ = job_dir / res
            assert (dir_ / "playlist.m3u8").is_file(), f"missing {res}/playlist.m3u8"
            assert (dir_ / "video.mp4").is_file(), f"missing {res}/video.mp4"
            segs = list(dir_.glob("seg_*.ts"))
            assert segs, f"no HLS segments in {res}/"

        assert (job_dir / "thumbnail.jpg").is_file()
        assert (job_dir / "thumbnail.jpg").stat().st_size > 0


def test_master_playlist_is_served(app, source_video):
    with TestClient(app) as client:
        jid = submit_video(client, source_video, resolutions="480")["id"]
        wait_completed(client, jid)
        resp = client.get(f"/output/{jid}/master.m3u8")
        assert resp.status_code == 200
        body = resp.text
        assert "EXTM3U" in body
        # References a variant playlist for the requested resolution.
        assert "480p/playlist.m3u8" in body or "playlist.m3u8" in body


def test_segment_serving_returns_passthrough(app, source_video):
    with TestClient(app) as client:
        jid = submit_video(client, source_video, resolutions="480")["id"]
        wait_completed(client, jid)
        seg = next((config.OUTPUT_DIR / jid / "480p").glob("seg_*.ts"))
        rel = f"480p/{seg.name}"
        resp = client.get(f"/output/{jid}/{rel}")
        assert resp.status_code == 200
        assert resp.content[:1] == b"\x47"  # transport-stream sync byte


def test_zip_download_for_completed_job(app, source_video):
    with TestClient(app) as client:
        jid = submit_video(client, source_video, resolutions="480")["id"]
        wait_completed(client, jid)
        resp = client.get(f"/api/jobs/{jid}/download")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/zip"
        assert resp.content.startswith(b"PK")


def test_web_ui_pages_render(app):
    """The drag-drop and job-list pages render without error."""
    with TestClient(app) as client:
        for path, marker in (("/", "Video Transcoder"), ("/jobs", "Jobs")):
            resp = client.get(path)
            assert resp.status_code == 200
            assert marker in resp.text


def test_static_assets_are_served(app):
    with TestClient(app) as client:
        css = client.get("/static/style.css")
        assert css.status_code == 200
        assert "body" in css.text
        js = client.get("/static/submit.js")
        assert js.status_code == 200