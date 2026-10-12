"""Unit tests for pure logic: progress parsing, models, CLI wiring."""

from __future__ import annotations

import pytest

from transcoder import models, progress
from transcoder.models import Job, JobStatus, Resolution


# --------------------------------------------------------------------------- #
# Progress parsing
# --------------------------------------------------------------------------- #


def test_parse_progress_pipe1_percent_with_duration():
    raw = (
        "frame=12\nfps=0.0\nstream_0_0_q=28.0\n"
        "out_time_us=1500000\nout_time_ms=1500000\nout_time=00:00:01.500000\n"
        "dup_frames=0\ndrop_frames=0\nspeed=4.5x\nprogress=continue\n"
    )
    assert progress.parse_progress_pipe1(raw, duration_seconds=10.0) == pytest.approx(15.0)


def test_parse_progress_pipe1_empty_returns_zero():
    assert progress.parse_progress_pipe1("", duration_seconds=5.0) == 0.0


def test_parse_progress_pipe1_caps_below_100():
    raw = "out_time_ms=99999999\nprogress=continue\n"
    assert progress.parse_progress_pipe1(raw, duration_seconds=1.0) == pytest.approx(99.0)


def test_parse_stderr_clock_time():
    raw = "frame= 40 fps= 0.0 q=28.0 size=  12kB time=00:00:02.50 bitrate="
    assert progress.parse_stderr_progress(raw) == pytest.approx(2.5)


def test_parse_stderr_no_time_returns_none():
    assert progress.parse_stderr_progress("frame=1\n") is None


# --------------------------------------------------------------------------- #
# Models + DB
# --------------------------------------------------------------------------- #


def test_job_category_filters():
    session_factory = models.make_session_factory("sqlite:///:memory:")
    s = session_factory()
    for i, st in enumerate([JobStatus.QUEUED, JobStatus.PROCESSING, JobStatus.COMPLETED]):
        j = Job(id=f"j{i}", filename=f"f{i}.mp4", source_path=f"/in/f{i}.mp4", status=st)
        j.resolutions.append(Resolution(height=480, status=JobStatus.QUEUED))
        s.add(j)
    s.commit()

    active = models.list_jobs(s, status="active")
    assert {j.status for j in active} == {JobStatus.QUEUED, JobStatus.PROCESSING}

    done = models.list_jobs(s, status="completed")
    assert len(done) == 1 and done[0].id == "j2"

    assert models.get_job(s, "missing") is None
    s.close()


def test_job_to_dict_shape():
    session_factory = models.make_session_factory("sqlite:///:memory:")
    s = session_factory()
    j = Job(id="abc123", filename="clip.mp4", source_path="/in/clip.mp4",
            status=JobStatus.QUEUED, progress_pct=12.5)
    j.resolutions.append(Resolution(height=1080, status=JobStatus.PROCESSING, progress_pct=40.0))
    s.add(j)
    s.commit()
    d = j.to_dict()
    assert d["id"] == "abc123" and d["status"] == "queued"
    assert d["progress_pct"] == 12.5
    assert d["resolutions"][0]["height"] == 1080
    s.close()


# --------------------------------------------------------------------------- #
# CLI wiring
# --------------------------------------------------------------------------- #


def test_cli_import_and_click_group():
    from transcoder import cli
    command = cli.make_cli()
    # Click group exposes its subcommands.
    names = set(command.commands.keys())
    assert {"submit", "list", "status", "watch", "serve"} <= names


def test_package_exports_version():
    import transcoder
    assert isinstance(transcoder.__version__, str)