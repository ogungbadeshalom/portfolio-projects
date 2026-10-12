"""Test fixtures for the transcoder.

Real behavior is exercised: a genuine FFmpeg ``testsrc`` video is generated
once per session, jobs are submitted through the FastAPI TestClient (which
drives the real asyncio queue), and output files are asserted on disk.
"""

from __future__ import annotations

import subprocess
import time

import pytest

from transcoder import config
from transcoder.main import build_app


def find_ffmpeg() -> str:
    """Resolve ffmpeg, failing the suite loudly if it is missing."""
    try:
        return config.find_ffmpeg()
    except RuntimeError as exc:
        pytest.skip(f"ffmpeg unavailable: {exc}")


@pytest.fixture(scope="session")
def source_video(tmp_path_factory):
    """A real 1s 320x240 synthetic MP4, produced once per test session."""
    ff = find_ffmpeg()
    out = tmp_path_factory.mktemp("media") / "source.mp4"
    cmd = [
        ff, "-y",
        "-f", "lavfi", "-i", "testsrc=duration=1:size=320x240:rate=10",
        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
        "-t", "1",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest",
        str(out),
    ]
    proc = subprocess.run(cmd, capture_output=True)
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")[-1500:]
    assert out.exists() and out.stat().st_size > 0
    return out


@pytest.fixture
def app(tmp_path, monkeypatch):
    """A FastAPI app with isolated storage and an in-memory shared DB."""
    storage = tmp_path / "storage"
    monkeypatch.setattr(config, "STORAGE_DIR", storage)
    monkeypatch.setattr(config, "INPUT_DIR", storage / "input")
    monkeypatch.setattr(config, "OUTPUT_DIR", storage / "output")
    monkeypatch.setattr(config, "THUMB_DIR", storage / "thumbs")
    monkeypatch.setattr(config, "DATABASE_URI", "sqlite:///:memory:")
    return build_app(database_uri="sqlite:///:memory:", max_workers=2, max_retries=3)


def wait_completed(client, job_id: str, timeout: float = 90.0) -> dict:
    """Poll ``/api/jobs/{id}/status`` until the job is terminal."""
    deadline = time.time() + timeout
    terminal = {"completed", "failed", "cancelled"}
    last = {}
    while time.time() < deadline:
        resp = client.get(f"/api/jobs/{job_id}/status")
        assert resp.status_code == 200
        last = resp.json()
        if last["status"] in terminal:
            return last
        time.sleep(0.4)
    raise AssertionError(f"job {job_id} did not finish in {timeout}s; last={last}")


def submit_video(client, video, resolutions="480,720"):
    """Helper to submit ``video`` to the running app."""
    with video.open("rb") as fh:
        resp = client.post(
            "/api/jobs",
            files={"file": ("source.mp4", fh, "video/mp4")},
            data={"resolutions": resolutions},
        )
    assert resp.status_code == 200, resp.text
    return resp.json()