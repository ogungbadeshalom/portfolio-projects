# Email Newsletter Service

## Project Title
Email Newsletter Service (Python)

## Goal
A full-featured newsletter service: subscribe, manage list, compose campaigns, send bulk emails, track opens/clicks/unsubscribes. Built for solo creators or small businesses.

## Why this project
Every business sends newsletters. Teaches: email deliverability, list management, queue-based sending, open/click tracking, unsubscribe handling (CAN-SPAM compliance).

## What You Build
A web app + CLI:

```bash
newsletter init                          # setup admin account
newsletter subscribe user@example.com    # public signup endpoint
newsletter list                          # list all subscribers
newsletter campaign new "Subject line"    # create campaign
newsletter campaign send CAMPAIGN_ID      # send to all subscribers
newsletter stats                          # subscribers, sends, opens, clicks
```

Web UI at `http://localhost:8080/`:
- Public subscribe form (POST email → welcome email)
- Admin dashboard (subscriber list, campaign list, stats)
- Campaign composer (write in HTML, preview, schedule or send)
- Subscriber management (import CSV, export, unsubscribe)
- Analytics (opens, clicks, bounces per campaign)

API:
```
POST   /api/subscribe                   # public, add subscriber
GET    /api/unsubscribe?token=...       # public, one-click unsubscribe
GET    /api/track/open/{campaign_id}     # open pixel (1x1 GIF)
GET    /api/track/click/{campaign_id}    # click redirect
```

## Tech
- **Python 3.11+**
- **FastAPI** (web + API)
- **aiosmtplib** (async SMTP sending)
- **Jinja2** (email templates)
- **SQLAlchemy** + **SQLite** (subscribers, campaigns, events)
- **Pandas** (CSV import/export)
- **htmx** (admin UI, no React)

## Architecture

```
newsletter/
├── newsletter/
│   ├── __init__.py
│   ├── main.py             # FastAPI entry
│   ├── cli.py              # Click commands
│   ├── models.py           # Subscriber, Campaign, Send, Open, Click
│   ├── subscribe.py        # public subscribe/unsubscribe
│   ├── campaigns.py        # campaign CRUD
│   ├── sender.py           # bulk email sending
│   ├── templates/
│   │   ├── welcome.html
│   │   ├── campaign.html
│   │   ├── unsubscribe.html
│   │   └── admin/
│   │       ├── dashboard.html
│   │       ├── subscribers.html
│   │       └── campaign_compose.html
│   ├── tracking.py         # open/click tracking pixels
│   ├── bounce.py           # bounce handling (SNS webhook or polling)
│   └── config.py
├── tests/
└── CLAUDE.md
```

## Build Order

1. **`models.py`** — Subscriber (id, email UNIQUE, name, status (active/unsubscribed/bounced), subscribed_at, unsubscribe_token), Campaign (id, subject, html_body, text_body, status, sent_at), Send (id, campaign_id, subscriber_id, sent_at, opened_at, clicked_at, bounced)
2. **`subscribe.py`** — public POST /api/subscribe adds subscriber, generates unsubscribe_token, sends welcome
3. **`unsubscribe.py`** — public GET /api/unsubscribe?token= marks subscriber inactive
4. **`campaigns.py`** — admin CRUD for campaigns
5. **`templates/welcome.html`** + `campaign.html` + `unsubscribe.html`
6. **`sender.py`** — `send_campaign(campaign_id)` queues sends, sends via aiosmtplib with rate limit
7. **`tracking.py`** — open pixel (1x1 transparent GIF), click redirect with logging
8. **`templates/admin/`** — dashboard, subscribers, campaign composer
9. **Rate limiting** — max 100 emails per minute (avoid spam filters)
10. **Bounce handling** — webhook endpoint for SES/SendGrid bounce notifications

## Requirements

- Public subscribe endpoint with double opt-in (sends confirmation email)
- One-click unsubscribe (CAN-SPAM required)
- Email templates render in HTML and plaintext
- Personalization: `{{name}}`, `{{unsubscribe_url}}` replaced per email
- Open tracking via 1x1 pixel GIF embedded in HTML
- Click tracking via redirect URL wrapping all links
- Rate limiting: max 100 emails/minute (avoid spam flags)
- Bounce handling: SES/SendGrid webhook or POP3 polling
- Campaign stats: sent, delivered, opened, clicked, bounced, unsubscribed
- CSV import/export for subscribers
- Admin authentication (basic auth or JWT)

## Code Standards

- All email sends use `aiosmtplib` (async, non-blocking)
- Personalization tokens replaced in a sandboxed template engine (no Jinja in user input — use string.Template)
- Unsubscribe links signed with HMAC (prevent abuse)
- Open pixel returns 1x1 transparent GIF (no caching headers)
- Click redirect validates URL (no open redirect vulnerability)
- Bounce webhook verifies SNS signature (or SendGrid signature)
- All subscriber emails stored lowercase
- HTML and plaintext versions of every email

## Verification

```bash
# Start server
uvicorn newsletter.main:app --port 8080

# Create admin
newsletter init

# Subscribe (use mailtrap.io for testing)
curl -X POST http://localhost:8080/api/subscribe \
  -d "email=test@example.com"

# Compose campaign in browser
open http://localhost:8080/admin/

# Send campaign (uses configured SMTP - mailtrap for testing)
newsletter campaign send 1

# Check stats
newsletter stats

# Run tests
pytest tests/ -v
```

## Stretch Goals

- Drip campaigns (automated sequences based on subscriber behavior)
- Segmentation (tag subscribers, send to segments)
- A/B testing (test subject lines)
- RSS-to-email (auto-send when blog posts)
- Webhooks for subscriber events (notify your CRM)
- Bounce categorization (hard vs soft)
- Spam score checking (SpamAssassin integration)
- DKIM/SPF/DMARC validation
- Multi-tenant (multiple newsletters from one instance)

## What You'll Learn

- Email deliverability fundamentals
- SMTP and async email sending
- CAN-SPAM compliance (one-click unsubscribe, sender info)
- Bulk sending with rate limiting
- Open/click tracking (pixels + redirects)
- Bounce handling
- Personalization and template safety
- List management patterns

## Time Estimate
12-16 hours for MVP. 20-28 hours with drip campaigns + A/B testing + bounces + admin UI.