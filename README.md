# Portfolio Projects

A collection of **20 self-contained projects** in **Python** and **TypeScript**, built as a hands-on portfolio. Each project lives in its own folder with its own `CLAUDE.md` spec, source code, and a passing test suite.

## Projects

| # | Project | Type | Stack | Tests |
|---|---------|------|-------|-------|
| 01 | CLI Todo App | CLI | Python, Typer, Rich | 27 ✅ |
| 02 | Markdown → HTML | CLI/tool | Python, markdown-it-py, Click | 11 ✅ |
| 03 | URL Shortener | API | FastAPI, SQLAlchemy, SQLite | 17 ✅ |
| 04 | Weather CLI | CLI | Python, httpx, Open-Meteo | 23 ✅ |
| 05 | Pomodoro Timer | Web app | Vanilla HTML/CSS/JS | browser ✅ |
| 06 | GitHub → Slack Webhook | Service | Flask, HMAC, Block Kit | 26 ✅ |
| 07 | Markdown Blog | Generator | Python, Jinja2, RSS/Atom | 24 ✅ |
| 08 | QR Code | CLI/library | Python, qrcode/Pillow | 21 ✅ |
| 09 | Cron Monitor | Service | FastAPI, SQLite, watchdog | 48 ✅ |
| 10 | File Upload | API | FastAPI, BLAKE2b, signed URLs | 34 ✅ |
| 11 | API Cache | Library/CLI | Python, aiosqlite, TTL | 30 ✅ |
| 12 | Webhook Replay | Service | FastAPI, sqlite | 17 ✅ |
| 13 | Invoice Generator | Service | Flask, ReportLab, Stripe-verify | 24 ✅ |
| 14 | Realtime Chat | Service+UI | FastAPI, WebSockets, JWT | 19 ✅ |
| 15 | Video Transcoder | Service | FastAPI, FFmpeg, HLS | 19 ✅ |
| 16 | Newsletter Service | Service | FastAPI, HMAC, tracking | 15 ✅ |
| 17 | API Gateway | Service | FastAPI, rate limit, proxy | 17 ✅ |
| 18 | Task Scheduler | Service | Python, queue, retries, DLQ | 40 ✅ |
| 19 | E2E Encrypted Messaging | TS app | TypeScript, libsodium, X3DH, Double Ratchet | 6 ✅ |
| 20 | Analytics Pipeline | Service+UI | FastAPI, SQLite, funnels | 31 ✅ |

> All tests run locally with no external services or secret keys — network/services are mocked (e.g. HTTP mock transports, local disk storage, in-memory or SQLite stores as Redis/S3/SMTP fallbacks).

## Layout

```
NN-project-name/
├── CLAUDE.md      # the project brief: goal, architecture, requirements, verification
├── README.md      # how to run the project
├── <pkg>/         # source code
├── tests/         # pytest / node --test suite
└── pyproject.toml  # dependencies + entry points (Python projects)
```

## Getting started

Each folder is independent. For a Python project:

```bash
cd NN-project-name
pip install -e .
python -m pytest tests/ -v  # or the CLI/`uvicorn` entrypoint shown in its README
```

For the TypeScript project (19):

```bash
cd 19-e2e-encrypted-messaging
npm install
npm test
```