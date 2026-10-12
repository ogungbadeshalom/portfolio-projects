# GitHub Webhook → Slack Notifier

## Project Title
GitHub Webhook → Slack Notifier (Python + Flask)

## Goal
Receive GitHub webhook events (push, PR, release, star) and forward them to Slack via Incoming Webhook with rich formatting.

## Why this project
Webhooks are how modern systems talk. Teaches: HMAC signature verification, idempotency, async queues, external API integration, secret management.

## What You Build
A Flask app that:

1. Receives GitHub webhook events at `POST /webhook/github`
2. Verifies HMAC SHA-256 signature using shared secret
3. Stores event in DB (idempotent — dedupe by `X-GitHub-Delivery` header)
4. Formats event into rich Slack message (Block Kit)
5. Forwards to Slack via Incoming Webhook URL
6. Exposes `GET /events` to view recent events (web UI)
7. Exposes `GET /health` for monitoring

## Tech
- **Python 3.11+**
- **Flask** (web framework)
- **httpx** (async Slack API calls)
- **SQLAlchemy** + **SQLite** (event persistence)
- **Redis** or **in-memory queue** for retry logic (optional)
- **Gunicorn** for production

## Architecture

```
githook/
├── githook/
│   ├── __init__.py
│   ├── app.py              # Flask app factory
│   ├── webhook.py          # /webhook/github endpoint + HMAC verify
│   ├── slack.py            # Slack Block Kit formatting + sending
│   ├── events.py           # Event model + storage
│   ├── retry.py            # Failed send retry queue
│   ├── config.py           # Secrets from env vars
│   └── formatters/
│       ├── push.py
│       ├── pull_request.py
│       ├── release.py
│       └── star.py
├── tests/
│   ├── test_webhook.py     # HMAC verification, edge cases
│   ├── test_slack.py
│   └── fixtures/
│       └── github_payloads/
├── docker-compose.yml
└── CLAUDE.md
```

## Build Order

1. **`webhook.py`** — Flask route, parse JSON, extract headers, verify HMAC
2. **`events.py`** — Event model (id, delivery_id UNIQUE, event_type, payload, processed_at, status)
3. **`formatters/push.py`** — convert GitHub push payload to Slack Block Kit JSON
4. **`slack.py`** — `send_to_slack(blocks)` with httpx, handle 429s
5. **`webhook.py`** — full flow: receive → verify → store → format → send → update status
6. **`app.py`** — Flask factory, register routes, error handlers
7. **Tests** — `pytest` with sample GitHub payloads

## Requirements

- HMAC verification MUST reject invalid signatures with 401
- Idempotency: same `X-GitHub-Delivery` header processed only once
- Support event types: `push`, `pull_request`, `release`, `star` (delete others silently or 200 OK)
- Slack message must use Block Kit (not plain text) with:
  - Repo name + branch
  - Commit author + message
  - Compare URL (clickable)
- Failed Slack sends retry 3x with exponential backoff
- Secrets via env vars: `GITHUB_WEBHOOK_SECRET`, `SLACK_WEBHOOK_URL`
- All payloads logged with `request_id` for debugging

## Code Standards

- All endpoints have type hints
- Use Flask blueprints for organization
- HMAC verification uses `hmac.compare_digest` (timing-safe)
- Slack sends are async (don't block webhook response)
- All errors logged with context (request_id, event_type)
- Tests use GitHub's real test payloads (saved as fixtures)

## Verification

```bash
# Start server
flask run --port 5000

# Send test webhook (with valid HMAC)
./scripts/test_webhook.sh

# Or use ngrok to expose to internet, then add to GitHub repo webhook

# Test all event types
pytest tests/ -v
```

## Stretch Goals

- Subscribe to specific repos only (filter by repo name)
- Custom message templates per channel
- Dashboard with event stats (events/day, failures)
- Retry dead-letter queue (review failed sends)
- Per-event-type routing (different channels for stars vs releases)
- Webhook signature replay protection (timestamp window)

## What You'll Learn

- HMAC signature verification
- Webhook idempotency patterns
- Slack Block Kit formatting
- Async webhook handling
- Secret management via env vars
- Retry logic with exponential backoff

## Time Estimate
4-6 hours for MVP. 8-12 hours with all event types + retries + tests.