# Multi-Tenant API Gateway

A production-grade FastAPI API gateway: API-key auth, per-tenant sliding-window
rate limiting, monthly quota/meteting, batched usage logging, and proxying to a
backend — with an in-memory rate limiter (`SlidingWindowLimiter`) as the Redis
fallback so it runs anywhere.

## Endpoints

| Method | Path                 | Auth        | Purpose                     |
|--------|----------------------|-------------|-----------------------------|
| POST   | `/api/auth/register` | —           | create a tenant             |
| POST   | `/api/auth/login`    | —           | verify password → JWT       |
| POST   | `/api/keys`          | Bearer JWT  | create an API key           |
| GET    | `/api/keys`          | Bearer JWT  | list my keys                |
| DELETE | `/api/keys/{id}`     | Bearer JWT  | revoke a key                |
| GET    | `/api/usage`         | Bearer JWT  | my usage stats              |
| `ANY`  | `/v1/{path}`         | `X-API-Key` | proxy to the protected backend |

## Behaviour

- **Auth** — API keys look like `sk_live_<random>`; only an HMAC-SHA256 hash is
  stored (`gateway/keys.py`). Invalid/revoked/expired keys → `401` with
  `WWW-Authenticate: API-Key`.
- **Rate limit** — per tenant + endpoint, in-memory sliding window → `429`
  with `Retry-After` and `X-RateLimit-*` headers.
- **Quota** — per tenant per month (plan-based; enterprises unlimited). Uses a
  single indexed aggregate over `usage_logs` → `402` when exceeded.
- **Usage logging** — batched background writes so the request path never
  blocks on a DB write.
- **Proxy** — streams to `settings.backend_base_url` through an injectable
  `httpx` transport (tests use `MockTransport` → zero network).

## Run

```bash
pip install fastapi uvicorn httpx sqlalchemy pydantic

# Point at a backend (any HTTP service), then start the gateway
set GATEWAY_BACKEND_URL=http://127.0.0.1:9000
python -m uvicorn gateway.main:app --port 8080
```

Try it:

```bash
curl -X POST localhost:8080/api/auth/register -H 'content-type: application/json' -d '{"email":"a@b.com","password":"secret1"}'
TOKEN=$(curl -X POST localhost:8080/api/auth/login -H 'content-type: application/json' -d '{"email":"a@b.com","password":"secret1"}' | python -c 'import sys,json;print(json.load(sys.stdin)["token"])')
KEY=$(curl -X POST localhost:8080/api/keys -H "Authorization: Bearer $TOKEN" | python -c 'import sys,json;print(json.load(sys.stdin)["key"])')
curl -H "X-API-Key: $KEY" localhost:8080/v1/ping
```

## Test

```bash
python -m pytest tests/ -v
```

## Test-ish portability

The gateway uses no external services: SQLite for storage, an in-memory token
bucket for rate limiting, and an injectable httpx transport for the backend so
tests run a fully in-process echo backend.