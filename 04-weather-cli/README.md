# Weather CLI

A command-line weather lookup tool: current conditions plus a multi-day
forecast for any city, with pretty and JSON output, disk caching, favorites,
and graceful offline fallback.

Built on the **free [Open-Meteo API](https://open-meteo.com/)** — **no API key
required**.

## Features

- Current conditions + up to 16-day forecast for one or many cities.
- Rich pretty-table output, or `--json` for machine-readable output.
- `--no-emoji` ASCII mode for piping into logs and scripts.
- Metric or imperial units (`--units`).
- Disk cache at `~/.cache/weather/` with TTL (30 min current, 1 h forecast).
- Falls back to cached data when the network is unavailable.
- Favorites file at `~/.config/weather/favorites.json`.
- Async HTTP under the hood (a single shared `httpx.AsyncClient`).

## Requirements

- Python 3.10+
- Dependencies: `httpx`, `click`, `rich`, `pydantic` (>=2)

## Install

```bash
cd weather-cli
python -m pip install -e .
```

Or, without installing the CLI entry point, run directly:

```bash
python -m pip install -r requirements.txt
python -m weather "Lagos"
```

For development (test tooling):

```bash
python -m pip install -r requirements.txt -r requirements-dev.txt
```

## Usage

```bash
weather "Lagos"                            # current + forecast, pretty table
weather "Lagos" --json                     # JSON output
weather "Lagos" --days 7 --units imperial  # options
weather "London" --no-emoji                # ASCII-only, pipe-friendly
weather "Tokyo" "Berlin" "NYC"             # multiple cities
weather --favorites                        # list saved locations
weather --add "Paris"                      # add a favorite
weather --remove "Paris"                   # remove a favorite
weather --clear-cache                      # purge the cache
```

`--json` supports multiple cities too; each forecast is printed as one JSON
document on stdout, separated by a newline.

### Exit codes

- `0` on success.
- `1` on any failure (network error, unknown city, bad arguments) — a
  friendly message is printed, never a raw stack trace.

## How caching works

Each lookup is keyed by `city:day-count:units`. A fresh cache hit is served
immediately; otherwise the API is queried and the result stored. If the
network fails, any cached copy (even a stale one) is shown with a warning,
falling back to an error only when nothing is cached.

Override cache/config locations with the environment variables
`WEATHER_CACHE_DIR` and `WEATHER_CONFIG_DIR` (mainly useful in tests).

## Project layout

```
weather/
├── weather/
│   ├── __init__.py     # package metadata
│   ├── __main__.py     # python -m weather entry
│   ├── cli.py          # Click command line interface
│   ├── api.py          # async Open-Meteo client
│   ├── models.py       # Pydantic models (Location, CurrentWeather, ...)
│   ├── cache.py        # JSON disk cache with TTL
│   ├── formatters.py   # pretty-table + JSON formatters
│   └── config.py       # defaults, paths, favorites helpers
├── tests/              # pytest suite (HTTP mocked, no network)
├── pyproject.toml
└── requirements*.txt
```

## Tests

```bash
pytest tests/ -v
```

The test suite mocks HTTP with `httpx.MockTransport`, so it runs entirely
offline and never calls the live API.

## Notes & limitations

- Needs internet access to `api.open-meteo.com` and
  `geocoding-api.open-meteo.com` to fetch live data.
- Cities are resolved by name via Open-Meteo's geocoder; very common names
  may resolve to a specific city (append a region/country for disambiguation).
- Forecast data from Open-Meteo is limited to 16 days.