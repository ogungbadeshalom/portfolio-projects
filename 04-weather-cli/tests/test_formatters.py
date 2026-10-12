"""Tests for the output formatters (pretty + JSON)."""

from __future__ import annotations

import json

from conftest import make_location, make_client

from weather.formatters import format_json, format_pretty
from weather.models import CurrentWeather, DailyForecast, Forecast


def _forecast() -> Forecast:
    loc = make_location(name="Lagos")
    cur = CurrentWeather(
        time="2026-09-12T12:00",
        temperature=28.4,
        feels_like=30.1,
        relative_humidity=68,
        wind_speed=12.3,
        weather_code=2,
    )
    daily = [
        DailyForecast(
            date="2026-09-12", weather_code=2, temp_max=30.0, temp_min=24.0,
            precipitation_sum=0.0, wind_speed_max=18.0,
        ),
        DailyForecast(
            date="2026-09-13", weather_code=61, temp_max=29.0, temp_min=23.0,
            precipitation_sum=2.5, wind_speed_max=20.0,
        ),
    ]
    return Forecast(location=loc, current=cur, daily=daily, units="metric")


class TestFormatJson:
    def test_valid_json_shape(self) -> None:
        fc = _forecast()
        parsed = json.loads(format_json(fc))
        assert parsed["units"] == "metric"
        assert parsed["location"]["name"] == "Lagos"
        assert parsed["current"]["temperature"] == 28.4
        assert len(parsed["daily"]) == 2


class TestFormatPretty:
    def test_includes_location_and_daily(self) -> None:
        out = format_pretty(_forecast())
        assert "Lagos" in out
        assert "2026-09-12" in out
        assert "2026-09-13" in out

    def test_emoji_fallback_when_disabled(self) -> None:
        out = format_pretty(_forecast(), no_emoji=True)
        # With emoji off we should see the description text, not the emoji.
        assert "Partly cloudy" in out


class TestRoundTrip:
    def test_forecast_constructed_from_client(self) -> None:
        loc = make_location()
        async def run() -> Forecast:
            async with make_client(days=2) as client:
                return await client.fetch_forecast(loc, day_count=2)

        import asyncio

        fc = asyncio.run(run())
        # A Forecast serialised to JSON then back parses cleanly.
        data = json.loads(format_json(fc))
        assert data["current"]["temperature"] == 28.4
        assert len(data["daily"]) == 2