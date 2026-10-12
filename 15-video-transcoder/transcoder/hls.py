"""HLS output generation (FFmpeg).

Produces a *master* playlist referencing per-resolution *variant* playlists,
plus transport-stream segments named ``seg_00000.ts``, ``seg_00001.ts``, ...
per the project spec.

API
---
* :func:`transcode_hls` -- encode one resolution to an HLS set inside a dir.
* :func:`master_playlist` -- build a master.m3u8 pointing at variant dirs.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from . import config, transcoder


async def transcode_hls(
    input_path: str,
    out_dir: Path,
    height: int,
    *,
    duration_ms: Optional[int] = None,
    on_progress=None,
) -> List[Path]:
    """Encode ``input_path`` to height ``height`` as HLS inside ``out_dir``.

    Returns the list of produced files (variant playlist, segments, mp4 copy).
    """
    return await transcoder.transcode_resolution(
        input_path, out_dir, height, duration_ms=duration_ms, on_progress=on_progress
    )


def master_playlist(resolution_stubs: list[tuple[int, str]]) -> str:
    """Return the text of a master.m3u8 referencing ``resolution_stubs``.

    Each stub is ``(height, variant_uri)`` where ``variant_uri`` is relative
    to the directory holding the master playlist (e.g. ``"720p/playlist.m3u8"``).
    A bandwidth hint is derived as a rough linear function of resolution.
    """
    lines = ["#EXTM3U", "#EXT-X-VERSION:3"]
    for height, uri in sorted(resolution_stubs, reverse=True):
        bandwidth = 500_000 + height * 2_000
        lines.append(f"#EXT-X-STREAM-INF:BANDWIDTH={bandwidth},RESOLUTION=0x{height}")
        lines.append(uri)
    lines.append("")
    return "\n".join(lines)