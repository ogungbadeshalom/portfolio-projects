# GitHub Webhook → Slack Notifier

Receive GitHub webhook events (push, pull_request, release, star) and forward
them to Slack via Incoming Webhooks with rich **Block Kit** formatting.

## Features

- **HMAC verification** — validates `X-Hub-Signature-256` with a pure-Python
  timing-safe comparison (`hmac.compare_digest`).
- **Idempotency** — de-duplicates by `X-GitHub-Delivery`; a replayed delivery
  is answered `200` but never re-stored or re-sent.
- **Block Kit formatters** — one module per event type under `githook/formatters`.
- **Retries** — exponential backoff with an in-memory retry queue (`githook/retry`).
- **Testable Slack sends** — the outbound call goes through an injectable
  `httpx` transport, so tests use `httpx.MockTransport` and never touch Slack.

## Run

```bash
set GITHUB_WEBHOOK_SECRET=your-secret
set SLACK_WEBHOOK_URL=https://hooks.slack.com/services/T/B/X

pip install flask sqlalchemy httpx
flask --app githook.app run --port 5000
# or
python -c "from githook.app import create_app; create_app().run(port=5000)"
```

### Test

```bash
python -m pytest tests/ -v
```

### Endpoints

| Method | Path              | Purpose                                  |
|--------|-------------------|------------------------------------------|
| POST   | `/webhook/github` | GitHub webhook receipt (verified, stored) |
| GET    | `/events`         | HTML list of recent events               |
| GET    | `/health`         | liveness                                 |

### Manual webhook

```bash
./scripts/test_webhook.sh push
```

Secrets come from `GITHUB_WEBHOOK_SECRET` / `SLACK_WEBHOOK_URL` (see
`githook/config.py` for dev defaults).