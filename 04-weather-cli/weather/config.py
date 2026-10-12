"""Configuration constants and paths for the Weather CLI.

Centralised defaults, cache/favorites file locations, and small path
helpers. Kept import-light so any module can import it without pulling
in heavy dependencies.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_UNITS = "metric"
DEFAULT_DAYS = 3
MAX_DAYS = 16  # Open-Meteo forecast API supports up to 16 days.

# TTLs (seconds). Current conditions refresh far more often than forecasts.
TTL_CURRENT_SECONDS = 30 * 60      # 30 minutes
TTL_FORECAST_SECONDS = 60 * 60     # 1 hour

# ---------------------------------------------------------------------------
# Open-Meteo endpoints (free, no API key).
# ---------------------------------------------------------------------------

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

REQUEST_TIMEOUT_SECONDS = 15.0
HTTP_USER_AGENT = "weather-cli/0.1.0 (portfolio project)"


def cache_dir() -> Path:
    """Return the directory used for cached responses.

    Defaults to ``~/.cache/weather`` and is overridable via the
    ``WEATHER_CACHE_DIR`` environment variable (used in tests).
    """
    env = _env("WEATHER_CACHE_DIR")
    d = Path(env) if env else Path.home() / ".cache" / "weather"
    d.mkdir(parents=True, exist_ok=True)
    return d


def config_dir() -> Path:
    """Return the directory used for user configuration (favorites).

    Defaults to ``~/.config/weather`` and is overridable via the
    ``WEATHER_CONFIG_DIR`` environment variable.
    """
    env = _env("WEATHER_CONFIG_DIR")
    d = Path(env) if env else Path.home() / ".config" / "weather"
    d.mkdir(parents=True, exist_ok=True)
    return d


def favorites_file() -> Path:
    """Return the path to the JSON favorites file."""
    return config_dir() / "favorites.json"


def cache_key(city: str, day_count: int, units: str) -> str:
    """Build the canonical cache key for a request.

    Key format: ``"{city}:{day_count}:{units}"`` with the city lowercased
    and whitespace collapsed so ``"New York"`` and ``"new york"`` collide.
    """
    slug = " ".join(city.split()).lower()
    return f"{slug}:{day_count}:{units}"


def load_favorites() -> list[str]:
    """Load the favorites list from disk.

    Returns an empty list when the file is missing or corrupt. Never raises.
    """
    path = favorites_file()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if isinstance(data, list):
        return [str(item).strip() for item in data if str(item).strip()]
    # Tolerate a dict form {"favorites": [...]}.
    if isinstance(data, dict) and isinstance(data.get("favorites"), list):
        return [str(item).strip() for item in data["favorites"] if str(item).strip()]
    return []


def save_favorites(favorites: list[str]) -> None:
    """Persist the favorites list to disk atomically."""
    path = favorites_file()
    payload = {"favorites": favorites}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)


def _env(name: str) -> str | None:
    """Read an environment variable without importing os at module level.

    Importing :mod:`os` is cheap, but keeping this helper keeps ``config.py``
    trivially importable in any context.
    """
    import os

    return os.environ.get(name)


# Convenience: expose ``main`` for Click-friendly entry points without a
# circular import. The CLI module is imported lazily on demand.
def _cli_main() -> None:
    """Thin shim that delegates to the Click CLI (used by ``__main__``)."""
    from weather.cli import main as cli_main

    sys.exit(cli_main())


if __name__ == "__main__":
    _cli_main()