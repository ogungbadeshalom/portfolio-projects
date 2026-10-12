# Weather CLI — httpx + JSON API

## Project Title
Weather CLI (Python)

## Goal
Command-line weather lookup. Get current conditions + 3-day forecast for any city. Pretty output, JSON output mode, caching to avoid hammering the API.

## Why this project
APIs are everywhere. This teaches API auth, error handling, caching, rate limits, and how to design clean CLI UX with multiple output formats.

## What You Build

```bash
weather "Lagos"                      # current + forecast, pretty table
weather "Lagos" --json               # JSON output
weather "Lagos" --days 7 --units metric
weather "London" --save-cache        # cache to ~/.weather.json
weather --favorites                  # show saved locations
weather "Tokyo" --no-emoji           # ASCII-only output for piping
```

## Tech
- **Python 3.11+**
- **httpx** (async HTTP client, modern, type-safe)
- **Open-Meteo API** (free, no API key required!)
- **Click** for CLI
- **Rich** for pretty tables
- **diskcache** or simple JSON cache

## Architecture

```
weather/
├── weather/
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py              # Click commands
│   ├── api.py              # Open-Meteo client (async)
│   ├── models.py           # Pydantic weather models
│   ├── cache.py            # Disk cache wrapper
│   ├── formatters.py       # Pretty table + JSON formatters
│   └── config.py           # Cache TTL, default units, favorites file
├── tests/
├── pyproject.toml
└── CLAUDE.md
```

## Build Order

1. **`api.py`** — async client for Open-Meteo geocoding + forecast APIs
2. **`models.py`** — Pydantic models: `Location`, `CurrentWeather`, `DailyForecast`
3. **`cache.py`** — diskcache wrapper with TTL (30 min for current, 1 hour for forecast)
4. **`formatters.py`** — Rich table formatter + JSON formatter (dataclass → dict)
5. **`cli.py`** — Click app with subcommands
6. **`__main__.py`** — entry point
7. **Tests** — mock the API, test formatters, test cache behavior

## Requirements

- No API key needed (use Open-Meteo which is free)
- Cache results to `~/.cache/weather/` with TTL
- Support both metric and imperial units
- Handle network failures gracefully (cached fallback if available)
- Multiple cities in one command: `weather "Lagos" "Tokyo" "Berlin"`
- `--no-emoji` mode for piping to logs
- Favorites file at `~/.config/weather/favorites.json`

## Code Standards

- All API calls are async
- Use `httpx.AsyncClient` as a singleton (don't create new client per request)
- Cache key = `f"{city.lower()}:{day_count}:{units}"`
- Errors: print friendly message, exit code 1, never stack trace
- Type hints everywhere
- Tests use `respx` to mock httpx

## Verification

```bash
pip install -e .

weather "Lagos"
weather "Lagos" --json
weather "Tokyo" "Berlin" "NYC"
weather "London" --units imperial
weather --favorites
pytest tests/ -v
```

## Stretch Goals

- ASCII art weather icons (☀ → [SUN])
- Compare two cities side-by-side
- Historical data (past 7 days from archive API)
- Alerts for severe weather (storms, heat waves)
- Integration with shell prompt (show weather in PS1)
- Cache TTL: 30 min for current, 1 hour for daily, 24 hours for historical
- Map view with lat/lon grid

## What You'll Learn

- Async HTTP client patterns (httpx)
- API response modeling with Pydantic
- Disk caching strategies
- CLI design with subcommands
- Error handling and graceful degradation
- Multiple output formats (pretty + JSON)

## Time Estimate
2-3 hours for MVP. 4-6 hours with caching + favorites + tests.