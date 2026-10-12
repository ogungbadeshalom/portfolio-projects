# URL Shortener — FastAPI + SQLite

## Project Title
URL Shortener API (FastAPI + SQLite)

## Goal
Build a tiny URL shortener API. POST a long URL, get a short code back. Visiting the short code redirects to the original. Track click counts.

## Why this project
Covers the full CRUD API stack: database, routing, validation, redirects, hashing/ID generation. Every backend dev needs these patterns.

## What You Build

```
POST /api/shorten          { "url": "https://..." }  →  { "code": "abc123", "short_url": "/abc123" }
GET  /:code                 → 302 redirect to original + increment counter
GET  /api/stats/:code      → { "url": "...", "clicks": 42, "created_at": "..." }
GET  /api/list              → list all short URLs (paginated)
```

## Tech
- **Python 3.11+**
- **FastAPI** (modern, async, auto-docs)
- **SQLAlchemy 2.0** (async ORM)
- **SQLite** (zero-config DB, easy upgrade to Postgres later)
- **Pydantic v2** (validation, settings)
- **Uvicorn** (ASGI server)
- **uvloop** for faster event loop

## Architecture

```
urlshort/
├── urlshort/
│   ├── __init__.py
│   ├── main.py             # FastAPI app entry
│   ├── models.py           # SQLAlchemy URL model
│   ├── schemas.py          # Pydantic request/response models
│   ├── database.py         # async engine + session
│   ├── routes/
│   │   ├── shorten.py      # POST /api/shorten
│   │   ├── redirect.py     # GET /:code
│   │   └── stats.py        # GET /api/stats/:code, /api/list
│   ├── id_generator.py     # nanoid / base62 short code
│   └── config.py           # Pydantic settings
├── tests/
│   ├── test_shorten.py
│   ├── test_redirect.py
│   └── test_stats.py
├── docker-compose.yml      # for Postgres if needed
├── pyproject.toml
└── CLAUDE.md
```

## Build Order

1. **`models.py`** — URL model: id, code (unique), target_url, clicks, created_at, expires_at
2. **`database.py`** — async engine, `get_db()` dependency
3. **`id_generator.py`** — `generate_code(length=7)` using `secrets.token_urlsafe`
4. **`schemas.py`** — ShortenRequest, ShortenResponse, StatsResponse
5. **`routes/shorten.py`** — POST validates URL, generates code, saves to DB, returns
6. **`routes/redirect.py`** — GET looks up code, increments clicks (async), 302 redirects
7. **`routes/stats.py`** — GET stats + list (paginated)
8. **`main.py`** — FastAPI app, mount routers, CORS, exception handlers
9. **Tests** — pytest with httpx AsyncClient

## Requirements

- URL validation: must be valid http/https, max 2048 chars, reject localhost (SSRF prevention)
- Short code: 7 chars, URL-safe alphabet, collision retry
- Click tracking: atomic increment (no race condition on concurrent clicks)
- Rate limiting: 100 requests/minute per IP (use `slowapi`)
- Health check: `GET /health` returns 200 with DB status
- Auto-generated OpenAPI docs at `/docs`
- Proper HTTP status codes: 201 on create, 404 on missing, 422 on invalid input

## Code Standards

- All routes are async
- Type hints everywhere
- Pydantic for ALL input/output (no raw dicts)
- Database operations use `async with` for proper cleanup
- Indexes on `code` (unique) and `created_at` (for pagination)
- Use `selectinload` / `joinedload` to avoid N+1 queries if you add user association later

## Verification

```bash
# Start server
uvicorn urlshort.main:app --reload --port 8000

# Test endpoints
curl -X POST http://localhost:8000/api/shorten \
  -H "Content-Type: application/json" \
  -d '{"url":"https://github.com/yt-dlp/yt-dlp"}'

# Returns: {"code":"abc12345","short_url":"/abc12345","target_url":"...","clicks":0}

# Visit the short URL
curl -I http://localhost:8000/abc12345
# HTTP/1.1 302 Found
# Location: https://github.com/yt-dlp/yt-dlp

# Get stats
curl http://localhost:8000/api/stats/abc12345

# Run tests
pytest tests/ -v --asyncio-mode=auto
```

## Stretch Goals

- Custom aliases (`POST /api/shorten {"url":"...","code":"my-link"}`)
- QR code generation for each short URL
- Expiration dates (auto-delete after N days)
- User accounts with API keys
- Analytics dashboard (clicks per day, referrer, country)
- Bulk URL import (CSV upload)
- Bot detection (skip redirects for crawlers, return HTML page)

## What You'll Learn

- FastAPI routing and dependency injection
- Async SQLAlchemy patterns
- URL validation and SSRF prevention
- HTTP redirects and caching headers
- Pydantic v2 validation
- Rate limiting with slowapi

## Time Estimate
3-5 hours for MVP. 8-10 hours with tests + rate limiting + analytics.