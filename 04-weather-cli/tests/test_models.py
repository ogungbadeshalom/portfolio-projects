"""Tests for the weather Pydantic models."""

from __future__ import annotations

import pytest

from conftest import make_location

from weather.models import CurrentWeather, DailyForecast, Forecast, Location


class TestLocation:
    def test_required_fields(self) -> None:
        loc = make_location(name="Abuja")
        assert loc.name == "Abuja"
        assert isinstance(loc.latitude, float)

    def test_timezone_default(self) -> None:
        loc = Location(name="X", latitude=1.0, longitude=2.0)
        assert loc.timezone == "auto"

    def test_openmeteo_id_alias(self) -> None:
        loc = Location.model_validate(
            {"name": "X", "latitude": 1.0, "longitude": 2.0, "id": 99}
        )
        assert loc.openmeteo_id == 99


class TestCurrentWeather:
    def test_is_daytime(self) -> None:
        assert CurrentWeather(time="t", temperature=1.0, is_day=1).is_daytime is True
        assert CurrentWeather(time="t", temperature=1.0, is_day=0).is_daytime is False

    def test_optional_fields_default_none(self) -> None:
        cw = CurrentWeather(time="t", temperature=1.0)
        assert cw.feels_like is None
        assert cw.weather_code is None


class TestDailyForecast:
    def test_full_row(self) -> None:
        day = DailyForecast(
            date="2026-09-12",
            temp_max=30.0,
            temp_min=24.0,
            weather_code=2,
        )
        assert day.date == "2026-09-12"
        assert day.temp_max == 30.0


class TestForecast:
    def test_round_trip(self) -> None:
        loc = make_location()
        cur = CurrentWeather(time="t", temperature=28.4)
        daily = [
            DailyForecast(date="2026-09-12", temp_max=30.0, temp_min=24.0),
        ]
        fc = Forecast(location=loc, current=cur, daily=daily, units="metric")
        assert fc.units == "metric"
        assert fc.daily[0].temp_max == 30.0