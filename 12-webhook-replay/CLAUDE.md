# Webhook Replay & Debug Tool

## Project Title
Webhook Replay & Debug Tool (Python)

## Goal
Capture incoming webhooks (like ngrok/RequestBin), inspect them, and replay them. Useful for debugging webhook integrations without setting up ngrok.

## Why this project
Webhooks fail in production. You need a way to capture them, inspect, and replay. Teaches: HTTP server, payload inspection, replay with timing, signed webhook verification testing.

## What You Build
A self-hosted webhook capture tool:

```bash
webhook-trap start --port 8085             # start capture server
# Webhooks will now hit: http://your-host:8085/incoming/{token}
# Token identifies which "trap" they hit

webhook-trap list                          # list captured requests
webhook-trap show 5                        # inspect request #5
webhook-trap replay 5 --delay 1000         # replay with 1s delay
webhook-trap replay --all --target https://prod.example.com/webhook
webhook-trap forward https://prod.example.com/webhook  # live forward mode
```

Web UI at `http://localhost:8085/`:
- List of all captured requests
- Click to inspect full headers + body
- Replay button (with delay option)
- Forward mode (live mirror to a real endpoint)
- Generate unique trap URLs for each test

## Tech
- **Python 3.11+**
- **FastAPI** (web + API)
- **httpx** (replay outbound requests)
- **Jinja2** (HTML templates)
- **HTMX** (no React)
- **SQLAlchemy** + **SQLite** (request storage)

## Architecture

```
webtrap/
├── webtrap/
│   ├── __init__.py
│   ├── main.py             # FastAPI entry
│   ├── cli.py              # Click CLI (start, list, replay, forward)
│   ├── capture.py          # /incoming/{token} endpoint
│   ├── replay.py           # replay outbound requests
│   ├── forwarder.py        # live forward mode
│   ├── models.py           # Request, Response, Trap
│   ├── database.py
│   ├── templates/
│   │   ├── base.html
│   │   ├── list.html
│   │   └── inspect.html
│   └── static/
├── tests/
└── CLAUDE.md
```

## Build Order

1. **`models.py`** — Request (id, token, method, path, headers_json, body, query_json, received_at, source_ip)
2. **`database.py`** — async engine, `get_db()` dep
3. **`capture.py`** — FastAPI route `/incoming/{token}` accepts ANY method, stores request, returns 200
4. **`cli.py`** — Click: `list`, `show <id>`, `replay <id>`, `forward <url>`
5. **`replay.py`** — replay captured request via httpx (preserves headers, body, method)
6. **`forwarder.py`** — middleware mode: capture AND forward to a real endpoint live
7. **`templates/list.html`** — list captured requests (method, path, time, source)
8. **`templates/inspect.html`** — full request detail with headers/body/replay button
9. **Web UI** — buttons for replay with delay, delete, export

## Requirements

- Capture any HTTP method (GET, POST, PUT, DELETE, PATCH, OPTIONS)
- Capture full request: headers, body, query params, source IP
- Persist to SQLite (survive restarts)
- Web UI to inspect and replay
- Replay preserves original headers + body + method + URL
- Replay can add delay (test webhook timeout handling)
- Forward mode: capture and forward to real endpoint live (mirror)
- Token-based trap URLs (so you can tell different integrations apart)
- Replay response is shown (status code, body, headers)
- Export captured request as cURL command

## Code Standards

- All endpoints accept any content type
- Request body stored as bytes (don't assume JSON)
- Headers stored as JSON dict (handle multi-value headers)
- Replay preserves original request exactly (no modifications)
- Forward mode uses streaming (don't buffer huge payloads)
- All operations are async
- Use Pydantic for request/response models

## Verification

```bash
# Start capture server
webtrap start --port 8085

# In another terminal, send a test webhook
curl -X POST http://localhost:8085/incoming/test-token-123 \
  -H "Content-Type: application/json" \
  -d '{"event":"test","data":{"foo":"bar"}}'

# List captured
webtrap list

# Inspect #1
webtrap show 1

# Replay to a real endpoint
webtrap replay 1 --target https://webhook.site/your-uuid

# Open web UI
open http://localhost:8085/

# Run tests
pytest tests/ -v
```

## Stretch Goals

- HMAC signature verification (validate incoming webhooks against shared secret)
- Diff view (compare two captured requests side-by-side)
- Search/filter by header value, body content, source IP
- Webhook replay with response diff (compare captured vs replayed response)
- Save "trap" configurations (token + forward URL + signing secret)
- Group captures by token (one per integration)
- Export as Postman collection or HAR file
- Slack/Discord notification on new capture

## What You'll Learn

- HTTP server design for capturing arbitrary requests
- Request inspection and replay
- HMAC signature verification
- Live forwarding / mirroring patterns
- Async HTTP client/server patterns
- Database storage of binary data (request bodies)

## Time Estimate
4-6 hours for MVP. 8-12 hours with forward mode + HMAC + diff + tests.