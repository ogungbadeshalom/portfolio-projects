"""Pydantic models that wrap the Open-Meteo JSON payloads.

Three core models mirror the shapes returned by the geocoding and forecast
endpoints:

* :class:`Location`      - a resolved city (lat/lon + timezone).
* :class:`CurrentWeather` - the current instantaneous conditions.
* :class:`DailyForecast`  - a daily average with min/max temps + precip.

Instances are JSON-serialisable so they can be stored in the disk cache and
handed to the formatters unchanged.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class Location(BaseModel):
    """A geocoded location returned by the Open-Meteo geocoding API."""

    name: str
    latitude: float
    longitude: float
    country: Optional[str] = None
    admin1: Optional[str] = None  # e.g. state / province
    timezone: str = "auto"
    # The ``id`` returned by Open-Meteo; optional and not always meaningful.
    openmeteo_id: Optional[int] = Field(default=None, alias="id", repr=False)

    model_config = {"populate_by_name": True}


class CurrentWeather(BaseModel):
    """Actual current weather at a location."""

    time: str
    temperature: float
    feels_like: Optional[float] = None
    relative_humidity: Optional[int] = None
    wind_speed: Optional[float] = None
    wind_gust: Optional[float] = None
    wind_direction: Optional[int] = None
    is_day: Optional[int] = None          # 1 = day, 0 = night
    precipitation: Optional[float] = None
    weather_code: Optional[int] = None

    @property
    def is_daytime(self) -> bool:
        """True when ``is_day`` signals daylight (1), else False."""
        return self.is_day == 1


class DailyForecast(BaseModel):
    """Summary weather for a single calendar day."""

    date: str
    weather_code: Optional[int] = None
    temp_max: Optional[float] = None
    temp_min: Optional[float] = None
    precipitation_sum: Optional[float] = None
    precipitation_probability_max: Optional[int] = None
    wind_speed_max: Optional[float] = None
    sunrise: Optional[str] = None
    sunset: Optional[str] = None


class Forecast(BaseModel):
    """Top-level response tying a location to its weather data.

    This is what the formatters consume and what the cache stores.
    """

    location: Location
    current: CurrentWeather
    daily: list[DailyForecast]
    units: str = "metric"  # "metric" or "imperial"