# JSON API → SQLite Cache (with TTL)

## Project Title
JSON API Cache Layer (Python)

## Goal
Build a generic caching layer for HTTP API responses. Cache JSON responses in SQLite with TTL. Auto-refresh on expiry. Manual invalidation by tag. ETag support.

## Why this project
Caching is fundamental to performance. Teaches: TTL management, conditional requests (ETag, If-None-Match), cache keys, tag-based invalidation, async patterns.

## What You Build
A reusable Python library + CLI:

```python
from apicache import APICache

cache = APICache("cache.db", default_ttl=300)

@cache.cached(ttl=600, tags=["users", "user-{user_id}"])
async def fetch_user(user_id: int):
    return await httpx.get(f"https://api.example.com/users/{user_id}")

# Invalidate by tag
await cache.invalidate_tag("user-123")

# Manual cache
await cache.set("key", {"data": "value"}, ttl=300)
result = await cache.get("key")
```

CLI:
```bash
apicache stats                    # show cache stats
apicache list                      # list all keys
apicache clear                     # clear all
apicache clear --tag user-123      # clear by tag
apicache inspect user-123          # show specific key
```

## Tech
- **Python 3.11+**
- **httpx** (HTTP client)
- **aiosqlite** (async SQLite)
- **Pydantic v2** (response models, validation)
- **diskcache** (sync fallback) or custom SQLite impl
- **pytest-asyncio** for tests
- **time-mock** or `freezegun` for TTL testing

## Architecture

```
apicache/
├── apicache/
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py              # Click commands
│   ├── core.py             # APICache class
│   ├── storage.py          # SQLite backend (async)
│   ├── decorator.py        # @cached decorator with template expansion
│   ├── invalidation.py     # Tag-based invalidation
│   ├── etag.py             # ETag/If-None-Match handling
│   ├── stats.py            # Hit/miss tracking
│   ├── models.py           # CacheEntry Pydantic model
│   └── config.py           # DB path, default TTL
├── tests/
├── pyproject.toml
└── CLAUDE.md
```

## Build Order

1. **`models.py`** — `CacheEntry(key, value_json, expires_at, tags_json, etag, created_at)`
2. **`storage.py`** — async SQLite CRUD: `get`, `set`, `delete`, `list_keys`, `cleanup_expired`
3. **`core.py`** — `APICache` class wrapping storage with TTL logic
4. **`etag.py`** — extract ETag from response, send If-None-Match on subsequent requests
5. **`decorator.py`** — `@cached(ttl=600, tags=['user-{user_id}'])` with template expansion
6. **`invalidation.py`** — tag-based: `invalidate_tag(tag)` deletes all entries with that tag
7. **`stats.py`** — track hits/misses, expose via `cache.stats()`
8. **`cli.py`** — Click commands for stats/list/clear/inspect

## Requirements

- TTL-based expiration (configurable per-key)
- Tag-based invalidation (multiple tags per entry)
- ETag/If-None-Match support (HTTP 304 not modified)
- Pattern-based key generation in decorator (`user-{user_id}`)
- Async-first (works with httpx async)
- Stats: hit rate, miss rate, total entries, expired entries
- Background cleanup task (periodic expired-entry removal)
- Thread-safe (multiple async tasks accessing same key)
- Storage abstraction (could swap SQLite for Redis)

## Code Standards

- All public methods are async
- Use type hints everywhere (Pydantic models for stored data)
- Keys always strings, values always JSON-serializable
- Tags always strings (joined with delimiter)
- ETag stored as-is (HTTP header value)
- Expired entries cleaned up lazily (on get) + periodically (background task)
- All operations use parameterized SQL queries (no injection)

## Verification

```bash
pip install -e .

# Test decorator
python -c "
import asyncio
from apicache import APICache

async def main():
    cache = APICache('test.db')
    @cache.cached(ttl=10)
    async def fetch(x):
        print(f'Fetching {x}')
        return {'value': x * 2}
    
    print(await fetch(5))  # Fetching 5
    print(await fetch(5))  # Cached
    print(await fetch(10)) # Fetching 10
    
asyncio.run(main())
"

# CLI tests
apicache stats
apicache list
apicache clear

# Run tests
pytest tests/ -v
```

## Stretch Goals

- Redis backend option
- Cache warming on startup (preload common keys)
- LRU eviction when storage exceeds max size
- Multiple cache layers (in-memory L1 + SQLite L2)
- Distributed cache invalidation (Redis pub/sub)
- Stale-while-revalidate pattern
- Cache stampede prevention (single-flight)
- JSON Schema validation on cached values

## What You'll Learn

- TTL-based cache patterns
- HTTP conditional requests (ETag)
- Tag-based cache invalidation
- Async SQLite patterns
- Decorator factories (with template expansion)
- Cache stampede prevention
- Storage abstraction

## Time Estimate
4-6 hours for MVP. 8-12 hours with decorator + ETag + tag invalidation + tests.