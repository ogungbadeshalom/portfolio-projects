"""Shared pytest fixtures.

All network access is mocked with ``httpx.MockTransport`` so the suite runs
fully offline. Cache/config paths are redirected into ``tmp_path`` via
environment variables the code already honours.
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from weather.models import Location  # noqa: E402

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


# ---------------------------------------------------------------------------
# Sample payloads
# ---------------------------------------------------------------------------

LOCATION_JSON = {
    "id": 1,
    "name": "Lagos",
    "latitude": 6.5244,
    "longitude": 3.3792,
    "country": "Nigeria",
    "admin1": "Lagos",
    "timezone": "Africa/Lagos",
}


def forecast_payload(location: dict, *, days: int = 3) -> dict:
    """Build a minimal, valid Open-Meteo forecast JSON body."""
    dates = ["2026-09-12", "2026-09-13", "2026-09-14", "2026-09-15"]
    window = dates[:days]
    return {
        "latitude": location["latitude"],
        "longitude": location["longitude"],
        "timezone": location.get("timezone", "auto"),
        "current": {
            "time": "2026-09-12T12:00",
            "temperature_2m": 28.4,
            "relative_humidity_2m": 68,
            "apparent_temperature": 30.1,
            "is_day": 1,
            "precipitation": 0.0,
            "weather_code": 2,
            "wind_speed_10m": 12.3,
            "wind_direction_10m": 180,
            "wind_gusts_10m": 22.0,
        },
        "daily": {
            "time": window,
            "weather_code": [2, 61, 3] + [3] * 10,
            "temperature_2m_max": [30.0, 29.0, 28.0] + [28.0] * 10,
            "temperature_2m_min": [24.0, 23.0, 23.0] + [23.0] * 10,
            "precipitation_sum": [0.0, 2.5, 0.0] + [0.0] * 10,
            "precipitation_probability_max": [0, 70, 10] + [10] * 10,
            "wind_speed_10m_max": [18.0, 20.0, 12.0] + [12.0] * 10,
            "sunrise": ["2026-09-12T06:30"] * 13,
            "sunset": ["2026-09-12T18:45"] * 13,
        },
    }


def make_transport(*, location: dict, days: int = 3):
    """Return a MockTransport that answers geocoding + forecast requests."""
    from weather.api import OpenMeteoClient

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).startswith(GEOCODING_URL):
            return httpx.Response(200, json={"results": [location]})
        if str(request.url).startswith(FORECAST_URL):
            return httpx.Response(200, json=forecast_payload(location, days=days))
        return httpx.Response(404, text="not found")

    return httpx.MockTransport(handler)


def make_client(location: dict = LOCATION_JSON, days: int = 3) -> OpenMeteoClient:
    """Build an ``OpenMeteoClient`` wired to the mocked transport."""
    from weather.api import OpenMeteoClient

    transport = make_transport(location=location, days=days)
    return OpenMeteoClient(transport=transport)


def make_location(**overrides) -> Location:
    """Build a :class:`Location` test fixture."""
    data = dict(LOCATION_JSON)
    data.update(overrides)
    return Location.model_validate(data)


@pytest.fixture
def sample_location() -> Location:
    """A resolved Lagos :class:`Location`."""
    return make_location()


@pytest.fixture
def offline_transport() -> httpx.MockTransport:
    """A transport that raises on *any* request (simulates no network)."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused (mocked)")

    return httpx.MockTransport(handler)


@pytest.fixture
def isolated_fs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point cache + config dirs into a throwaway temp folder.

    Yields ``(cache_dir, config_dir)`` paths.
    """
    cache = tmp_path / "cache"
    config_root = tmp_path / "config"
    monkeypatch.setenv("WEATHER_CACHE_DIR", str(cache))
    monkeypatch.setenv("WEATHER_CONFIG_DIR", str(config_root))
    return cache, config_root