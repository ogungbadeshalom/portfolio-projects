# Video Transcoder Queue (FFmpeg)

## Project Title
Video Transcoder Queue (Python + FFmpeg)

## Goal
A job queue that transcodes uploaded videos into multiple resolutions (480p, 720p, 1080p) using FFmpeg. Background workers process jobs, status updates via WebSocket, CDN-ready output.

## Why this project
Video is hard. Teaches: async job queues, subprocess management (FFmpeg), progress tracking, CDN-ready output formats (HLS/DASH), file management, error recovery.

## What You Build

```bash
transcoder submit video.mp4 --resolutions 480,720,1080
transcoder list                        # all jobs
transcoder status JOB_ID               # job progress
transcoder watch JOB_ID                # live progress (streams updates)
```

Web UI at `http://localhost:8080/`:
- Submit video (drag-drop)
- List of jobs with status
- Live progress bars per resolution
- Preview transcoded output
- Download all versions (zip)

API:
```
POST   /api/jobs                     # submit job
GET    /api/jobs                     # list jobs
GET    /api/jobs/{id}                # job details
GET    /api/jobs/{id}/status          # JSON status (polled)
WS     /ws/jobs/{id}                 # WebSocket live progress
GET    /output/{id}/master.m3u8       # serve HLS playlist
```

## Tech
- **Python 3.11+**
- **FastAPI** (web + WebSocket)
- **FFmpeg** (subprocess for transcoding)
- **asyncio.subprocess** (async FFmpeg calls)
- **SQLAlchemy** + **SQLite** (job storage)
- **aiofiles** (async file I/O)
- **Pillow** (thumbnail generation)

## Architecture

```
transcoder/
├── transcoder/
│   ├── __init__.py
│   ├── __main__.py
│   ├── main.py             # FastAPI entry
│   ├── cli.py              # Click commands
│   ├── models.py           # Job, Resolution, OutputFile
│   ├── queue.py            # In-process job queue (asyncio)
│   ├── transcoder.py       # FFmpeg subprocess management
│   ├── progress.py         # Parse FFmpeg progress from stderr
│   ├── hls.py              # HLS output generator
│   ├── thumbnail.py        # Generate video thumbnails
│   ├── routes/
│   │   ├── jobs.py
│   │   └── ws.py
│   ├── templates/
│   └── static/
├── storage/
│   ├── input/              # uploaded videos
│   └── output/             # transcoded videos (per-job)
├── tests/
└── CLAUDE.md
```

## Build Order

1. **`models.py`** — Job (id, filename, status, progress_pct, created_at), Resolution (id, job_id, resolution, status, progress_pct, output_path), OutputFile (id, resolution_id, filename, size_bytes)
2. **`transcoder.py`** — `transcode(input, output, resolution)` runs FFmpeg subprocess
3. **`progress.py`** — Parse FFmpeg stderr for `time=00:01:23.45` to compute progress %
4. **`queue.py`** — In-process asyncio queue, worker coroutine pulls jobs, runs transcoder
5. **`thumbnail.py`** — FFmpeg extracts frame at 00:00:05, saves as JPG
6. **`hls.py`** — Generate HLS playlist (master.m3u8 + segments) for streaming
7. **`routes/jobs.py`** — submit, list, status endpoints
8. **`routes/ws.py`** — WebSocket for live progress
9. **`cli.py`** — Click commands (submit, list, status, watch)
10. **Templates** — drag-drop submit, job list with progress bars

## Requirements

- Submit via API or web UI (drag-drop)
- Multiple resolutions transcoded in parallel (480p, 720p, 1080p)
- HLS output (master.m3u8 + segment files) for streaming
- Thumbnail generated at 00:00:05
- Live progress updates via WebSocket
- Cancel in-progress job
- Re-encoding on retry (transient FFmpeg errors)
- Cleanup: remove output files after N days
- Concurrency limit: max 2 parallel transcodes (CPU-bound)
- Error recovery: failed job retries up to 3x, then marks failed

## Code Standards

- All FFmpeg calls via `asyncio.create_subprocess_exec` (non-blocking)
- Parse FFmpeg stderr line-by-line (don't buffer)
- Progress reported via callback or queue (not return value)
- Use FFmpeg's `-progress pipe:1` flag for parseable progress output
- HLS segment naming: `seg_00000.ts`, `seg_00001.ts`, etc.
- Master playlist references all resolutions with bandwidth hints
- All subprocess errors logged with full FFmpeg stderr

## Verification

```bash
# Install FFmpeg
apt install ffmpeg

# Start server
uvicorn transcoder.main:app --port 8080

# Submit a test video
transcoder submit test.mp4 --resolutions 480,720,1080

# Watch progress
transcoder watch JOB_ID

# Check output
ls -la storage/output/JOB_ID/
file storage/output/JOB_ID/720p/playlist.m3u8

# Play HLS output
ffplay storage/output/JOB_ID/720p/playlist.m3u8

# Run tests
pytest tests/ -v
```

## Stretch Goals

- Adaptive bitrate (ABR) HLS with multiple bitrates per resolution
- Video thumbnails at multiple timestamps (preview strip)
- Video preview player (HTML5 video tag)
- Watermark overlay
- Audio normalization (EBU R128)
- Subtitle burn-in
- Auto-crop to 16:9
- GPU acceleration (NVENC)
- S3/GCS upload of transcoded output

## What You'll Learn

- Async subprocess management
- FFmpeg CLI patterns
- Progress parsing from stderr
- HLS streaming format
- Job queue patterns (in-process + Redis-backed)
- WebSocket progress streaming
- File system patterns for large media files

## Time Estimate
8-12 hours for MVP. 20-30 hours with HLS + WebSocket progress + thumbnails + retry logic.