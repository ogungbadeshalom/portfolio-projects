"""Central configuration for the transcoder."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
STORAGE_DIR = Path(os.environ.get("TRANSCODER_STORAGE", str(BASE_DIR / "storage")))
INPUT_DIR = STORAGE_DIR / "input"
OUTPUT_DIR = STORAGE_DIR / "output"
THUMB_DIR = STORAGE_DIR / "thumbs"

DATABASE_URI = os.environ.get("TRANSCODER_DATABASE_URL", "sqlite:///" + str(STORAGE_DIR / "transcoder.db").replace("\\", "/"))

# ---------------------------------------------------------------------------
# Transcode settings
# ---------------------------------------------------------------------------
RESOLUTIONS: list[int] = [480, 720, 1080]
HLS_SEGMENT_SECONDS = 4

# Concurrency limit: at most this many ffmpeg processes in flight (CPU-bound).
MAX_CONCURRENT = int(os.environ.get("TRANSCODER_MAX_CONCURRENT", "2"))

# Transient-failure retry count before a job is marked failed.
MAX_RETRIES = int(os.environ.get("TRANSCODER_MAX_RETRIES", "3"))

# FFmpeg binary resolution (Windows build already on PATH via shutil.which).
def find_ffmpeg() -> str:
    """Return the ffmpeg executable, or raise RuntimeError with install help."""
    exe = os.environ.get("FFMPEG_BIN")
    if exe and Path(exe).exists():
        return exe
    found = shutil.which("ffmpeg")
    if found:
        return found
    # Common fallback location provided by the environment.
    fallback = Path(os.environ.get("FFMPEG_PATH", r"C:\Program Files\yt-dlp\ffmpeg.exe"))
    if fallback.exists():
        return str(fallback)
    raise RuntimeError(
        "ffmpeg not found on PATH. Install it or set FFMPEG_BIN to its location."
    )


def find_ffprobe() -> str:
    """Return the ffprobe executable (must ship alongside ffmpeg)."""
    exe = os.environ.get("FFPROBE_BIN")
    if exe and Path(exe).exists():
        return exe
    found = shutil.which("ffprobe")
    if found:
        return found
    fallback = Path(os.environ.get("FFPROBE_PATH", r"C:\Program Files\yt-dlp\ffprobe.exe"))
    if fallback.exists():
        return str(fallback)
    # ffprobe often lives next to ffmpeg; derive it.
    ff = find_ffmpeg()
    probe = Path(ff).parent / "ffprobe.exe"
    if probe.exists():
        return str(probe)
    raise RuntimeError("ffprobe not found. It normally ships with ffmpeg.")


def ensure_dirs() -> None:
    """Create the storage directories the worker writes to."""
    for path in (INPUT_DIR, OUTPUT_DIR, THUMB_DIR):
        path.mkdir(parents=True, exist_ok=True)