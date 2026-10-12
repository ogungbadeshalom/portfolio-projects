# File Upload Service — S3-Compatible

## Project Title
File Upload Service (Python + FastAPI)

## Goal
A simple file upload service. Accept files via multipart upload or direct PUT (presigned URLs). Store on disk with content-addressable names (hash). Serve via signed URLs with expiration.

## Why this project
File uploads are everywhere. Teaches: multipart parsing, streaming uploads, MIME detection, signed URLs (HMAC), content hashing, storage abstractions.

## What You Build

```
POST   /upload                    # multipart form upload
POST   /upload/init                # start multipart upload, returns upload_id
POST   /upload/{upload_id}/part    # upload a part
POST   /upload/{upload_id}/complete  # complete multipart upload
GET    /files/{hash}               # download (checks auth)
GET    /files/{hash}/url?expires=3600  # get signed URL
DELETE /files/{hash}                # delete
```

Direct upload flow:
1. Client calls `POST /files/init` → gets `upload_url` (signed PUT URL)
2. Client PUTs file directly to that URL
3. File is stored, client gets the hash

## Tech
- **Python 3.11+**
- **FastAPI** (web framework)
- **python-multipart** (multipart parsing)
- **aiofiles** (async file I/O)
- **Pillow** (image resizing, MIME detection)
- **python-magic** (better MIME detection)
- **HMAC** (stdlib, for signed URLs)
- **blake2b** (stdlib, for file hashing)

## Architecture

```
upload/
├── upload/
│   ├── __init__.py
│   ├── main.py             # FastAPI entry
│   ├── models.py           # File, MultipartUpload, UploadPart
│   ├── routes/
│   │   ├── upload.py       # POST /upload (multipart, simple)
│   │   ├── multipart.py    # Multipart chunked upload
│   │   └── files.py        # GET/DELETE /files/{hash}
│   ├── storage.py          # disk storage with content-addressable naming
│   ├── signed_url.py       # HMAC-signed URL generation/verification
│   ├── mime.py             # MIME detection (python-magic + Pillow)
│   ├── limits.py           # File size/type limits
│   └── config.py           # Max file size, allowed types, storage path
├── storage/
│   └── files/              # actual stored files (content-addressable)
├── tests/
└── CLAUDE.md
```

## Build Order

1. **`storage.py`** — `save_file(content) → hash`, `get_file(hash) → bytes`, `delete_file(hash)`. Content-addressable: `storage/files/{hash[:2]}/{hash}`
2. **`mime.py`** — Detect MIME from bytes (magic numbers + python-magic)
3. **`routes/upload.py`** — simple multipart POST `/upload`
4. **`signed_url.py`** — `generate_signed_url(file_hash, expires_in)` using HMAC
5. **`routes/files.py`** — `GET /files/{hash}` verifies signature, returns file
6. **`routes/multipart.py`** — init / part / complete for chunked uploads
7. **`main.py`** — FastAPI app, mount routers, size limits via middleware
8. **Limits** — max file size (default 100MB), allowed types (configurable)

## Requirements

- Multipart upload handles large files (10GB+) via streaming
- File deduplication via content hashing (BLAKE2b)
- Signed URLs with expiration (default 1 hour, configurable)
- MIME detection from file content, not extension
- Max file size enforced (return 413 Payload Too Large)
- Allowed MIME types whitelist (configurable, default: images, PDFs, common docs)
- Filename sanitization (no path traversal)
- Files served with correct Content-Type
- Range request support for video/audio (HTTP 206)

## Code Standards

- All routes are async
- File hashing done while streaming (don't load full file in memory)
- Signed URLs use HMAC-SHA256 with timestamp (prevent replay)
- MIME type whitelist checked server-side, never trust client extension
- Filename sanitization removes path separators, null bytes
- Range requests supported via FastAPI's `Range` header handling

## Verification

```bash
# Start server
uvicorn upload.main:app --port 8001

# Simple upload
curl -X POST http://localhost:8001/upload \
  -F "file=@/tmp/test.pdf"

# Returns: {"hash":"abc123...","size":12345,"mime":"application/pdf","url":"/files/abc123..."}

# Get signed URL
curl "http://localhost:8001/files/abc123.../url?expires=3600"

# Download with signed URL
curl "http://localhost:8001/files/abc123...?expires=...&sig=..."

# Multipart upload (for large files)
curl -X POST http://localhost:8001/upload/init
curl -X POST http://localhost:8001/upload/{upload_id}/part --data-binary @chunk1
curl -X POST http://localhost:8001/upload/{upload_id}/complete

# Run tests
pytest tests/ -v
```

## Stretch Goals

- Image processing on upload (auto-resize, WebP conversion)
- Virus scanning (ClamAV integration)
- Cloud storage backends (S3, GCS) via storage abstraction
- Signed URL with content-type override
- Multipart upload resumption
- File metadata extraction (EXIF for images, page count for PDFs)
- Deduplication across users (same hash = same file)
- Per-user storage quotas

## What You'll Learn

- Multipart form data parsing
- Streaming file uploads (no full memory load)
- Content-addressable storage (like git)
- HMAC-signed URLs with expiration
- MIME detection from bytes
- HTTP range requests (streaming downloads)
- File I/O patterns (async, streaming)

## Time Estimate
6-8 hours for MVP. 12-16 hours with multipart chunked upload + signed URLs + range requests.