# Multi-Tenant API Gateway

## Project Title
Multi-Tenant API Gateway (FastAPI + API Key Auth + Rate Limiting)

## Goal
A production-grade API gateway: API key authentication, per-tenant rate limiting, usage tracking, billing-ready metering, request logging, dashboard.

## Why this project
Every SaaS needs this. Teaches: auth patterns, rate limiting algorithms, quota tracking, multi-tenancy isolation, billing-metering primitives.

## What You Build

```
POST   /api/auth/register              # create tenant
POST   /api/auth/login                  # returns JWT
POST   /api/keys                        # create API key
GET    /api/keys                        # list my keys
DELETE /api/keys/{id}                  # revoke key
GET    /api/usage                       # current usage stats
```

Proxy to protected backend:
```
GET    /v1/{path}                       # all requests here need API key
       Header: X-API-Key: sk_...
```

Gateway responsibilities:
- Authenticate API key (check signature, lookup tenant)
- Rate limit (per tenant, per endpoint, per IP)
- Quota check (does tenant have remaining quota?)
- Usage log (every request: tenant_id, endpoint, status, latency)
- Forward to backend if allowed
- Return 429 if rate limited, 402 if quota exceeded, 401 if invalid key

## Tech
- **Python 3.11+**
- **FastAPI** (gateway + admin API)
- **httpx** (forward requests to backend)
- **Redis** or in-memory token bucket (rate limiting)
- **SQLAlchemy** + **PostgreSQL** (production) or **SQLite** (dev)
- **Pydantic v2** (validation)
- **structlog** (structured logging)

## Architecture

```
gateway/
├── gateway/
│   ├── __init__.py
│   ├── main.py             # FastAPI entry
│   ├── auth.py             # JWT + API key auth
│   ├── keys.py             # API key generation, hashing, verification
│   ├── ratelimit.py        # Token bucket + sliding window
│   ├── quota.py            # Quota tracking
│   ├── proxy.py            # Forward to backend
│   ├── usage.py            # Usage logging + metering
│   ├── models.py           # Tenant, ApiKey, UsageLog, Endpoint
│   ├── middleware.py        # API key + rate limit + quota middleware
│   ├── routes/
│   │   ├── auth.py
│   │   ├── keys.py
│   │   ├── usage.py
│   │   └── proxy.py        # /v1/{path} catches all
│   ├── templates/
│   │   └── admin/
│   └── config.py
├── tests/
└── CLAUDE.md
```

## Build Order

1. **`models.py`** — Tenant (id, email, name, plan, monthly_quota, created_at), ApiKey (id, tenant_id, key_hash UNIQUE, prefix, name, last_used_at, expires_at, revoked), UsageLog (id, tenant_id, endpoint, method, status_code, latency_ms, timestamp)
2. **`keys.py`** — `generate_key()` returns `sk_live_...`, stores only HMAC hash in DB, `verify_key(plaintext) → ApiKey`
3. **`auth.py`** — JWT for admin UI, API key for /v1/* endpoints
4. **`ratelimit.py`** — Token bucket (in-memory or Redis), `check_limit(tenant_id, endpoint) → allowed/denied`
5. **`quota.py`** — `check_quota(tenant_id)` queries monthly usage, denies if exceeded
6. **`usage.py`** — async log every request to DB (don't block response)
7. **`middleware.py`** — extracts API key, runs auth → rate limit → quota, forwards if allowed
8. **`proxy.py`** — uses httpx to forward to configured backend URL
9. **`routes/admin/`** — dashboard, keys list, usage stats
10. **Tests** — full integration tests with multiple tenants

## Requirements

- API keys format: `sk_live_<random>` (visible prefix) + HMAC hash stored
- Rate limiting: per tenant per endpoint (default: 100 req/min)
- Quota: per tenant per month (default: 10K requests, configurable per plan)
- Rate limit response: 429 with `Retry-After` header
- Quota exceeded: 402 with link to upgrade
- Invalid key: 401 with `WWW-Authenticate: API-Key` header
- Usage logging: every request logged async (don't block)
- Dashboard: requests/sec, top tenants, error rates, quota usage
- Plans: free (1K/mo), starter (10K/mo), pro (100K/mo), enterprise (unlimited)
- Webhook on quota threshold (notify tenant at 80%, 100%)

## Code Standards

- API key hashing uses HMAC-SHA256 with server-side secret
- Rate limit uses sliding window (not fixed window — smoother)
- Quota check is single SQL query with index on (tenant_id, month)
- Usage log writes are batched (every 5 seconds, not every request)
- Proxy never buffers entire request body (stream through)
- All responses include rate limit headers: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`
- Errors return structured JSON: `{"error": {"code": "...", "message": "...", "request_id": "..."}}`

## Verification

```bash
# Start gateway (with mock backend on :9000)
uvicorn gateway.main:app --port 8080
# Backend: any Flask/FastAPI app on :9000 for testing

# Register tenant
curl -X POST http://localhost:8080/api/auth/register \
  -d '{"email":"test@example.com","password":"secret"}'

# Login → JWT
TOKEN=$(curl -X POST http://localhost:8080/api/auth/login \
  -d '{"email":"test@example.com","password":"secret"}' | jq -r .token)

# Create API key
API_KEY=$(curl -X POST http://localhost:8080/api/keys \
  -H "Authorization: Bearer $TOKEN" | jq -r .key)

# Use it
curl -H "X-API-Key: $API_KEY" http://localhost:8080/v1/test

# Hammer to trigger rate limit
for i in {1..200}; do
  curl -H "X-API-Key: $API_KEY" http://localhost:8080/v1/test
done

# Should see 429 after limit
curl -H "X-API-Key: $API_KEY" -i http://localhost:8080/v1/test

# Run tests
pytest tests/ -v
```

## Stretch Goals

- Per-endpoint rate limits (different limits for /v1/expensive vs /v1/cheap)
- Burst allowance (e.g., 1000 req in 1 second OK, then back to normal)
- Tiered plans with hard/soft limits
- Auto-suspend tenant on payment failure
- Webhook delivery for usage events
- API key scopes (read-only vs read-write)
- IP whitelisting per API key
- Geo-restrictions per tenant
- Request signing (HMAC of body, prevent replay)

## What You'll Learn

- Multi-tenant SaaS architecture
- API key generation, hashing, verification
- Token bucket rate limiting
- Sliding window rate limiting
- Quota tracking and metering
- Async usage logging
- Request proxying and streaming
- Authentication patterns (JWT + API keys)

## Time Estimate
10-14 hours for MVP. 20-28 hours with rate limiting + quota + admin UI + tests.