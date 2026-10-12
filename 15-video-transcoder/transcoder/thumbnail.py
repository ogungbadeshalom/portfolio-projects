"""Video thumbnail generation via FFmpeg frame extraction.

Extracts a single frame (default: near ``00:00:05``) and saves it as a JPEG,
per the project spec.
"""

from __future__ import annotations

from pathlib import Path

from .transcoder import make_thumbnail  # noqa: F401  (re-exported API)

DEFAULT_AT_SECONDS = 5.0


async def generate_thumbnail(
    input_path: str,
    output_jpg: Path,
    at_seconds: float = DEFAULT_AT_SECONDS,
) -> bool:
    """Extract a frame from ``input_path`` at ``at_seconds`` into ``output_jpg``."""
    return await make_thumbnail(input_path, output_jpg, at_seconds=at_seconds)