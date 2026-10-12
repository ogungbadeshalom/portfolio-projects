# webtrap — Webhook Replay & Debug Tool

Capture incoming webhooks (like ngrok / RequestBin), inspect them, and replay
them against a real endpoint — no external service needed.

## Features

- **Capture** any HTTP method and content type at `/incoming/{token}` with
  full headers (multi-value preserved), raw body bytes, query params, and
  source IP — persisted to SQLite (survives restarts).
- **Inspect** via a web UI or the JSON API (with a copy-paste `curl`).
- **Replay** a captured request preserving method / headers / body / query,
  with an optional delay.
- **Forward** (mirror) mode: stream a captured request live to a real target.
- **CLI**: `start`, `list`, `show`, `replay`, `forward`, `trap`.

All replay/forward hops run through an injectable `httpx` transport, so tests
drive an in-process ASGI echo and make zero network calls.

## Run

```bash
pip install fastapi uvicorn httpx click jinja2 sqlalchemy aiosqlite pydantic

# Server + web UI (http://localhost:8085)
python -m uvicorn webtrap.main:app --port 8085

# Send a test webhook
curl -X POST http://localhost:8085/incoming/my-token -d '{"event":"test"}'

# CLI (python -m webtrap.cli)
python -m webtrap.cli list
python -m webtrap.cli show 1
python -m webtrap.cli replay 1 --target https://prod.example.com/webhook
python -m webtrap.cli forward https://prod.example.com/webhook --token my-token
```

## Test

```bash
python -m pytest tests/ -v
```

## Layout

```
webtrap/
├── main.py        # FastAPI app + web UI + JSON API
├── capture.py     # /incoming/{token} capture endpoint
├── forwarder.py   # live streaming mirror mode
├── replay.py      # replay captured requests
├── models.py      # Request ORM + schemas
├── database.py    # async SQLAlchemy engine + deps
├── cli.py         # Click CLI
├── templates/     # base, list, inspect
└── static/        # stylesheet
```