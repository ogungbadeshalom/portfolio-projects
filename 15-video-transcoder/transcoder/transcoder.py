"""FFmpeg subprocess management.

All transcoding is done with :func:`asyncio.create_subprocess_exec` so the
event loop is never blocked.  Progress is parsed from FFmpeg's
``-progress pipe:1`` key/value stream, which is more reliable than scraping
stderr ``time=`` lines.

Public helpers
--------------
* :func:`probe_duration`       -- read a video's duration via ffprobe.
* :func:`make_thumbnail`       -- extract a frame to a JPEG.
* :func:`transcode_resolution` -- resize + re-encode to an HLS stream (+ mp4).
* :func:`transcode`            -- run every requested resolution for a job.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Callable, List, Optional

from . import config, progress

logger = logging.getLogger(__name__)

#: Progress callback receives an overall percent 0..100.
ProgressCallback = Callable[[float], None]


# --------------------------------------------------------------------------- #
# ffprobe
# --------------------------------------------------------------------------- #


async def probe_duration(input_path: str) -> Optional[float]:
    """Return the input video's duration in seconds, or ``None`` on failure."""
    cmd = [
        config.find_ffprobe(),
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        input_path,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    out, _ = await proc.communicate()
    if proc.returncode != 0:
        logger.warning("ffprobe failed for %s", input_path)
        return None
    try:
        return float(out.decode().strip())
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# Progress parsing
# --------------------------------------------------------------------------- #


async def _run_with_progress(
    cmd: List[str],
    *,
    duration_ms: Optional[int],
    on_progress: Optional[ProgressCallback] = None,
) -> int:
    """Run ``cmd`` reading ``-progress pipe:1``, invoking ``on_progress``.

    Returns the process return code.
    """
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    stderr = bytearray()

    async def feed_progress() -> None:
        assert proc.stdout is not None
        while True:
            chunk = await proc.stdout.read(4096)
            if not chunk:
                break
            _emit_progress(chunk, duration_ms, on_progress)

    async def feed_stderr() -> None:
        assert proc.stderr is not None
        while True:
            chunk = await proc.stderr.read(4096)
            if not chunk:
                break
            stderr.extend(chunk)

    # Read both streams ourselves -- *not* proc.communicate(), which would
    # race read() on stdout with feed_progress().
    await asyncio.gather(feed_progress(), feed_stderr())
    rc = await proc.wait()
    if rc != 0:
        tail = bytes(stderr).decode("utf-8", "replace")[-1200:] if stderr else ""
        logger.error("ffmpeg exit=%s for %s\n%s", rc, cmd, tail)
    if on_progress:
        on_progress(100.0)
    return rc


def _emit_progress(raw: bytes, duration_ms: Optional[int], on_progress) -> None:
    text = raw.decode("utf-8", "replace")
    dur = (duration_ms / 1000.0) if duration_ms else None
    pct = progress.parse_progress_pipe1(text, duration_seconds=dur)
    if pct:
        on_progress(pct)


# --------------------------------------------------------------------------- #
# Single-resolution transcode (HLS + mp4) + thumbnail
# --------------------------------------------------------------------------- #


async def make_thumbnail(
    input_path: str,
    output_jpg: Path,
    at_seconds: float = 0.0,
    duration_seconds: Optional[float] = None,
) -> bool:
    """Extract a frame near ``at_seconds`` into ``output_jpg``.

    Seeks *after* the input (input-seek, ``-i … -ss …``) which is reliable on
    very short clips, and clamps ``at_seconds`` to the midpoint of
    ``duration_seconds`` when given so we never target the final instant
    (which can make the mjpeg encoder bail with "before EOF").
    """
    output_jpg.parent.mkdir(parents=True, exist_ok=True)

    if duration_seconds and duration_seconds > 0:
        at_seconds = min(at_seconds, duration_seconds * 0.5)

    cmd = [
        config.find_ffmpeg(),
        "-y",
        "-i", input_path,
        "-ss", f"{at_seconds:.2f}",
        "-frames:v", "1",
        "-q:v", "2",
        str(output_jpg),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0 and at_seconds > 0.0:
        # Fall back to frame zero if the timed seek failed for a short clip.
        logger.warning(
            "thumbnail seek to %.2fs failed; retrying at 0.0: %s",
            at_seconds, stderr.decode("utf-8", "replace")[-300:],
        )
        return await make_thumbnail(input_path, output_jpg, at_seconds=0.0,
                                    duration_seconds=duration_seconds)
    if proc.returncode != 0:
        logger.error("thumbnail failed for %s: %s", input_path,
                     stderr.decode("utf-8", "replace")[-500:])
        return False
    return output_jpg.exists()


async def transcode_resolution(
    input_path: str,
    out_dir: Path,
    height: int,
    *,
    duration_ms: Optional[int] = None,
    on_progress: Optional[ProgressCallback] = None,
) -> List[Path]:
    """Transcode ``input_path`` to the given height as HLS (+ an mp4 copy).

    Produces into ``out_dir``::

        master.m3u8   media playlist (variants are a single stream here)
        playlist.m3u8 variant playlist
        seg_00000.ts  HLS segments
        video.mp4     direct-download copy

    Returns the list of created files.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    hls_base = str(out_dir / "playlist.m3u8")
    seg_prefix = str(out_dir / "seg_%05d.ts")
    mp4_path = out_dir / "video.mp4"

    cmd = [
        config.find_ffmpeg(),
        "-y",
        "-i", input_path,
        "-vf", f"scale=-2:{height}",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "28",
        "-c:a", "aac",
        "-b:a", "96k",
        "-hls_time", str(config.HLS_SEGMENT_SECONDS),
        "-hls_playlist_type", "vod",
        "-hls_segment_filename", seg_prefix,
        "-progress", "pipe:1",
        "-nostats",
        hls_base,
    ]
    rc = await _run_with_progress(cmd, duration_ms=duration_ms, on_progress=on_progress)
    if rc != 0:
        # Fall back to a plain transcode for the single-resolution path so we
        # never lose output over an HLS packaging quirk.
        return await _transcode_mp4(input_path, mp4_path, height, duration_ms, on_progress)

    # Add a direct-download mp4 copy (second, quick pass from the segments is
    # avoided; we re-encode simply).
    await _transcode_mp4(input_path, mp4_path, height, None, None)

    files = list(out_dir.glob("*"))
    return [p for p in files if p.is_file()]


async def _transcode_mp4(
    input_path: str,
    mp4_path: Path,
    height: int,
    duration_ms: Optional[int],
    on_progress: Optional[ProgressCallback],
) -> List[Path]:
    mp4_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        config.find_ffmpeg(),
        "-y",
        "-i", input_path,
        "-vf", f"scale=-2:{height}",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "28",
        "-c:a", "aac",
        "-b:a", "96k",
        "-movflags", "+faststart",
        "-f", "mp4",
        str(mp4_path),
    ]
    await _run_with_progress(cmd, duration_ms=duration_ms, on_progress=on_progress)
    return [mp4_path] if mp4_path.exists() else []


# --------------------------------------------------------------------------- #
# Whole-job transcode
# --------------------------------------------------------------------------- #


async def transcode(
    input_path: str,
    job_dir: Path,
    heights: List[int],
    *,
    on_progress: Optional[ProgressCallback] = None,
    thumb_at: float = 1.0,
) -> dict:
    """Transcode ``input_path`` into all ``heights`` under ``job_dir``.

    ``on_progress`` receives an overall 0..100 covering all resolutions plus
    the thumbnail.  Returns ``{"resolutions": {...}, "thumbnail": path}``.
    """
    duration_ms = None
    dur = await probe_duration(input_path)
    if dur is not None:
        duration_ms = int(dur * 1000)

    thumb = await make_thumbnail(
        input_path, job_dir / "thumbnail.jpg",
        at_seconds=thumb_at, duration_seconds=dur or None,
    )

    results: dict = {}
    per = 100.0 / max(1, len(heights))
    for idx, height in enumerate(heights):
        base = idx * per
        files = await transcode_resolution(
            input_path,
            job_dir / f"{height}p",
            height,
            duration_ms=duration_ms,
            on_progress=(lambda p, b=base, s=per: on_progress(b + p * s / 100.0))
            if on_progress
            else None,
        )
        results[int(height)] = [str(f.relative_to(job_dir)) for f in files]

    if on_progress:
        on_progress(100.0)
    return {"resolutions": results, "thumbnail": "thumbnail.jpg" if thumb else None}