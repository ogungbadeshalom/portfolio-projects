"""Async client for the free Open-Meteo API.

The client speaks to two endpoints:

* ``geocoding-api.open-meteo.com`` - resolves a city name to lat/lon.
* ``api.open-meteo.com``          - returns current + daily forecast data.

No API key is required. All network access goes through a single shared
:class:`httpx.AsyncClient` instance. Pass an ``httpx.MockTransport`` when
writing tests so nothing touches the network.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import httpx

from .config import (
    FORECAST_URL,
    GEOCODING_URL,
    HTTP_USER_AGENT,
    REQUEST_TIMEOUT_SECONDS,
)
from .models import CurrentWeather, DailyForecast, Forecast, Location

# Open-Meteo WMO weather code -> human description (used by formatters).
WMO_DESCRIPTIONS: dict[int, str] = {
    0: "Clear sky",
    1: "Mostly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Rime fog",
    51: "Light drizzle",
    53: "Drizzle",
    55: "Heavy drizzle",
    56: "Freezing drizzle",
    57: "Heavy freezing drizzle",
    61: "Light rain",
    63: "Rain",
    65: "Heavy rain",
    66: "Freezing rain",
    67: "Heavy freezing rain",
    71: "Light snow",
    73: "Snow",
    75: "Heavy snow",
    77: "Snow grains",
    80: "Light rain showers",
    81: "Rain showers",
    82: "Heavy rain showers",
    85: "Snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with hail",
    99: "Thunderstorm with heavy hail",
}

# Open-Meteo unit temperature keys (depends on ``temperature_unit`` param).
_UNIT_TEMPERATURE = {"metric": "celsius", "imperial": "fahrenheit"}
_UNIT_WIND = {"metric": "kmh", "imperial": "mph"}
_UNIT_PRECIPITATION = {"metric": "mm", "imperial": "inch"}


class OpenMeteoError(RuntimeError):
    """Raised for any problem talking to the Open-Meteo API.

    The CLI catches this at the top level, prints a friendly message, and
    exits with status 1 - never a raw traceback.
    """


class CityNotFoundError(OpenMeteoError):
    """Raised when a city name cannot be geocoded to a location."""


class NoDataError(OpenMeteoError):
    """Raised when the forecast endpoint returns no usable data."""


@dataclass
class ForecastUnits:
    """The unit flags Open-Meteo expects for a given unit system."""

    temperature: str
    wind: str
    precipitation: str
    speed: str


def forecast_units(units: str) -> ForecastUnits:
    """Map ``"metric"`` / ``"imperial"`` to Open-Meteo query parameter values."""
    try:
        return ForecastUnits(
            temperature=_UNIT_TEMPERATURE[units],
            wind=_UNIT_WIND[units],
            precipitation=_UNIT_PRECIPITATION[units],
            speed=_UNIT_WIND[units],
        )
    except KeyError:
        raise ValueError(
            f"Unknown units {units!r}; expected 'metric' or 'imperial'"
        ) from None


def describe_wmo(code: Optional[int]) -> str:
    """Return the human-readable description for a WMO weather code."""
    if code is None:
        return "Unknown"
    return WMO_DESCRIPTIONS.get(code, f"Code {code}")


class OpenMeteoClient:
    """Async handler for geocoding and forecast lookups.

    Parameters
    ----------
    transport:
        An optional ``httpx.AsyncBaseTransport`` (e.g. ``httpx.MockTransport``)
        injected for tests. When ``None`` a real network transport is used.
    """

    def __init__(self, transport: Optional[httpx.AsyncBaseTransport] = None) -> None:
        self._client = httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(REQUEST_TIMEOUT_SECONDS),
            headers={"User-Agent": HTTP_USER_AGENT},
        )

    async def aclose(self) -> None:
        """Close the underlying HTTP client (idempotent)."""
        await self._client.aclose()

    async def __aenter__(self) -> "OpenMeteoClient":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.aclose()

    async def geocode(self, city: str, *, limit: int = 1) -> Location:
        """Resolve a city name to a :class:`Location`.

        Raises :class:`CityNotFoundError` when nothing matches.
        """
        try:
            resp = await self._client.get(
                GEOCODING_URL,
                params={
                    "name": city,
                    "count": limit,
                    "language": "en",
                    "format": "json",
                },
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as exc:
            raise CityNotFoundError(
                f"Could not reach the geocoding service while searching for "
                f"{city!r}: {exc}"
            ) from exc
        except ValueError as exc:  # invalid JSON body
            raise CityNotFoundError(
                f"Geocoding service returned an unreadable response for "
                f"{city!r}."
            ) from exc

        results = data.get("results") or []
        if not results:
            raise CityNotFoundError(
                f"No matching place found for {city!r}. Check the spelling or "
                f"try a larger region/country."
            )
        try:
            return Location.model_validate(results[0])
        except Exception as exc:  # pydantic.ValidationError and friends
            raise CityNotFoundError(
                f"Could not parse the location data returned for {city!r}."
            ) from exc

    async def fetch_forecast(
        self,
        location: Location,
        *,
        day_count: int,
        units: str = "metric",
    ) -> Forecast:
        """Fetch current + daily forecast for a location.

        Parameters
        ----------
        location:
            A geocoded :class:`Location`.
        day_count:
            Number of daily timesteps to request (1..16).
        units:
            ``"metric"`` or ``"imperial"``.
        """
        u = forecast_units(units)
        try:
            resp = await self._client.get(
                FORECAST_URL,
                params={
                    "latitude": location.latitude,
                    "longitude": location.longitude,
                    "current": "temperature_2m,relative_humidity_2m,apparent_"
                               "temperature,is_day,precipitation,weather_code,"
                               "wind_speed_10m,wind_direction_10m,wind_gusts_10m",
                    "daily": "weather_code,temperature_2m_max,temperature_2m_min,"
                             "precipitation_sum,precipitation_probability_max,"
                             "wind_speed_10m_max,sunrise,sunset",
                    "forecast_days": day_count,
                    "temperature_unit": u.temperature,
                    "wind_speed_unit": u.wind,
                    "precipitation_unit": u.precipitation,
                    "timezone": location.timezone,
                },
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as exc:
            raise OpenMeteoError(
                f"Could not fetch forecast data for {location.name}: {exc}"
            ) from exc
        except ValueError as exc:
            raise OpenMeteoError(
                f"Forecast service returned an unreadable response for "
                f"{location.name}."
            ) from exc

        return self._parse_forecast(data, location=location, units=units)

    # ------------------------------------------------------------------ #
    # Parsing helpers (extracted for unit-testability).                   #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _parse_forecast(data: dict, *, location: Location, units: str) -> Forecast:
        """Build a :class:`Forecast` from a raw Open-Meteo JSON payload."""
        current_raw = data.get("current")
        daily_raw = data.get("daily") or {}
        if not current_raw:
            raise NoDataError(f"No current conditions returned for {location.name}.")

        # Expand the aligned daily arrays into per-day rows.
        dates = _get_list(daily_raw, "time")
        daily: list[DailyForecast] = []
        if dates:
            columns = {
                "weather_code": "weather_code",
                "temperature_2m_max": "temp_max",
                "temperature_2m_min": "temp_min",
                "precipitation_sum": "precipitation_sum",
                "precipitation_probability_max": "precipitation_probability_max",
                "wind_speed_10m_max": "wind_speed_max",
                "sunrise": "sunrise",
                "sunset": "sunset",
            }
            for i, date in enumerate(dates):
                row: dict = {"date": date}
                for raw_key, model_key in columns.items():
                    values = _get_list(daily_raw, raw_key)
                    if i < len(values):
                        row[model_key] = values[i]
                daily.append(DailyForecast.model_validate(row))

        # Map the Open-Meteo ``current`` keys onto the model's field names.
        current_map = {
            "time": "time",
            "temperature_2m": "temperature",
            "apparent_temperature": "feels_like",
            "relative_humidity_2m": "relative_humidity",
            "wind_speed_10m": "wind_speed",
            "wind_gusts_10m": "wind_gust",
            "wind_direction_10m": "wind_direction",
            "is_day": "is_day",
            "precipitation": "precipitation",
            "weather_code": "weather_code",
        }
        current_raw_mapped = {
            model_key: current_raw.get(raw_key)
            for raw_key, model_key in current_map.items()
        }
        current = CurrentWeather.model_validate(current_raw_mapped)
        return Forecast(
            location=location,
            current=current,
            daily=daily,
            units=units,
        )


def _get_list(mapping: dict, key: str) -> list:
    """Return ``mapping[key]`` when it is a list, else an empty list."""
    value = mapping.get(key)
    return value if isinstance(value, list) else []