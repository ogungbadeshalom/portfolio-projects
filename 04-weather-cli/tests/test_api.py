"""Tests for the Open-Meteo API client (network fully mocked)."""

from __future__ import annotations

import pytest

from conftest import (
    LOCATION_JSON,
    forecast_payload,
    make_client,
    make_location,
)

from weather.api import (
    CityNotFoundError,
    NoDataError,
    OpenMeteoError,
    describe_wmo,
    forecast_units,
)
from weather.models import Forecast, Location


class TestForecastUnits:
    def test_metric(self) -> None:
        u = forecast_units("metric")
        assert u.temperature == "celsius"
        assert u.wind == "kmh"
        assert u.precipitation == "mm"

    def test_imperial(self) -> None:
        u = forecast_units("imperial")
        assert u.temperature == "fahrenheit"
        assert u.wind == "mph"
        assert u.precipitation == "inch"

    def test_unknown_raises(self) -> None:
        with pytest.raises(ValueError):
            forecast_units("kelvin")


class TestDescribeWmo:
    def test_known_code(self) -> None:
        assert describe_wmo(2) == "Partly cloudy"

    def test_unknown_code(self) -> None:
        assert describe_wmo(999) == "Code 999"

    def test_none(self) -> None:
        assert describe_wmo(None) == "Unknown"


class TestGeocode:
    @pytest.mark.asyncio
    async def test_returns_location(self) -> None:
        async with make_client() as client:
            loc = await client.geocode("Lagos")
        assert isinstance(loc, Location)
        assert loc.name == "Lagos"
        assert loc.latitude == pytest.approx(6.5244)

    @pytest.mark.asyncio
    async def test_city_not_found_raises(self) -> None:
        from weather.api import OpenMeteoClient

        async with OpenMeteoClient(transport=_empty_results_transport()) as client:
            with pytest.raises(CityNotFoundError):
                await client.geocode("Nowhereville")


def _empty_results_transport():
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        if "geocoding" in str(request.url):
            return httpx.Response(200, json={"results": []})
        return httpx.Response(404, text="not found")

    return httpx.MockTransport(handler)


class TestFetchForecast:
    @pytest.mark.asyncio
    async def test_returns_forecast(self) -> None:
        loc = make_location()
        async with make_client(days=3) as client:
            fc = await client.fetch_forecast(loc, day_count=3)
        assert isinstance(fc, Forecast)
        assert fc.location.name == "Lagos"
        assert fc.current.temperature == 28.4
        assert len(fc.daily) == 3

    @pytest.mark.asyncio
    async def test_daily_rows_have_fields(self) -> None:
        loc = make_location()
        async with make_client(days=3) as client:
            fc = await client.fetch_forecast(loc, day_count=3)
        day = fc.daily[0]
        assert day.date == "2026-09-12"
        assert day.temp_max == 30.0
        assert day.temp_min == 24.0

    @pytest.mark.asyncio
    async def test_no_current_raises_no_data(self) -> None:
        import httpx

        from weather.api import OpenMeteoClient

        def handler(request: httpx.Request) -> httpx.Response:
            payload = forecast_payload(LOCATION_JSON, days=1)
            payload.pop("current")
            return httpx.Response(200, json=payload)

        transport = httpx.MockTransport(handler)
        async with OpenMeteoClient(transport=transport) as client:
            with pytest.raises(NoDataError):
                await client.fetch_forecast(make_location(), day_count=1)

    @pytest.mark.asyncio
    async def test_network_error_raises_open_meteo_error(self) -> None:
        import httpx

        from weather.api import OpenMeteoClient

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("boom")

        transport = httpx.MockTransport(handler)
        async with OpenMeteoClient(transport=transport) as client:
            with pytest.raises(OpenMeteoError):
                await client.fetch_forecast(make_location(), day_count=1)