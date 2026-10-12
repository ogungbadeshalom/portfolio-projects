"""The ``weather`` command-line interface (Click).

Entry point: :func:`main`. Use ``python -m weather`` or the installed
``weather`` console script.

Supported invocations::

    weather "Lagos"                            # current + forecast (pretty)
    weather "Lagos" --json                     # JSON output
    weather "Lagos" "Tokyo" "Berlin"           # multiple cities
    weather "Lagos" --days 7 --units imperial  # options
    weather "Lagos" --no-emoji                 # ASCII, pipe-friendly
    weather --favorites                        # list saved locations
    weather --add "Paris" / --remove "Paris"   # manage favorites
    weather --clear-cache                      # purge the cache
"""

from __future__ import annotations

import asyncio
from typing import Optional, Sequence

import click

from . import config
from .api import OpenMeteoClient, OpenMeteoError, forecast_units
from .cache import WeatherCache, ttl_for
from .config import DEFAULT_DAYS, DEFAULT_UNITS, MAX_DAYS
from .formatters import format_json, format_pretty


class _FatalError(click.ClickException):
    """Internal wrapper so friendly errors carry exit code 1."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.exit_code = 1


# --------------------------------------------------------------------------
# Options
# --------------------------------------------------------------------------


def _day_count(ctx: click.Context, param: click.Parameter, value: int) -> int:
    """Validate and clamp ``--days`` to the API's supported range."""
    if value < 1:
        raise click.BadParameter("--days must be at least 1", param_hint=param.name)
    return min(value, MAX_DAYS)


def _validate_units(value: str) -> str:
    if value not in ("metric", "imperial"):
        raise click.BadParameter("--units must be 'metric' or 'imperial'")
    return value


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.argument("cities", nargs=-1, required=False, type=click.STRING)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Print machine-readable JSON instead of the pretty table.",
)
@click.option(
    "--days",
    default=DEFAULT_DAYS,
    show_default=True,
    type=click.INT,
    callback=_day_count,
    help="Number of forecast days to request (max 16).",
)
@click.option(
    "--units",
    default=DEFAULT_UNITS,
    show_default=True,
    type=click.STRING,
    help="Temperature/wind unit system: 'metric' or 'imperial'.",
)
@click.option(
    "--no-emoji",
    is_flag=True,
    help="Use ASCII-safe output (no emoji) - good for piping to logs.",
)
@click.option(
    "--favorites",
    "list_favorites",
    is_flag=True,
    help="List saved favorite locations and exit.",
)
@click.option(
    "--add",
    "add_favorite",
    type=click.STRING,
    help="Add a city to the favorites file.",
)
@click.option(
    "--remove",
    "remove_favorite",
    type=click.STRING,
    help="Remove a city from the favorites file.",
)
@click.option(
    "--clear-cache",
    is_flag=True,
    help="Delete all cached weather responses.",
)
def main(
    cities: Sequence[str],
    as_json: bool,
    days: int,
    units: str,
    no_emoji: bool,
    list_favorites: bool,
    add_favorite: Optional[str],
    remove_favorite: Optional[str],
    clear_cache: bool,
) -> None:
    """Fetch current conditions and a {days}-day forecast for one or more cities."""
    units = _validate_units(units)
    try:
        asyncio.run(_run(
            cities=cities,
            as_json=as_json,
            days=days,
            units=units,
            no_emoji=no_emoji,
            list_favorites=list_favorites,
            add_favorite=add_favorite,
            remove_favorite=remove_favorite,
            clear_cache=clear_cache,
        ))
    except _FatalError as exc:
        raise exc
    except Exception as exc:  # guard against any unexpected runtime error
        raise _FatalError(f"Unexpected error: {exc}") from exc


# --------------------------------------------------------------------------
# Core async runner
# --------------------------------------------------------------------------


async def _run(
    *,
    cities: Sequence[str],
    as_json: bool,
    days: int,
    units: str,
    no_emoji: bool,
    list_favorites: bool,
    add_favorite: Optional[str],
    remove_favorite: Optional[str],
    clear_cache: bool,
) -> None:
    # Administrative sub-modes short-circuit before any network work.
    if clear_cache:
        removed = WeatherCache().clear()
        click.echo(f"Cleared {removed} cached entr{'y' if removed == 1 else 'ies'}.")
        return

    if add_favorite:
        _manage_favorites(op="add", city=add_favorite)
        return

    if remove_favorite:
        _manage_favorites(op="remove", city=remove_favorite)
        return

    if list_favorites:
        _print_favorites()
        return

    if not cities:
        # No action requested and no cities - show help and exit non-zero.
        raise _FatalError("Nothing to do. Pass at least one city, or use --favorites.")

    forecast_units(units)  # validate early, before any network call.

    client = OpenMeteoClient()
    cache = WeatherCache()
    try:
        results = await _fetch_all(client, cache, list(cities), days, units)
    finally:
        await client.aclose()

    for forecast in results:
        if as_json:
            click.echo(format_json(forecast))
        else:
            click.echo(format_pretty(forecast, no_emoji=no_emoji))
            click.echo("")


async def _fetch_all(
    client: OpenMeteoClient,
    cache: WeatherCache,
    cities: list[str],
    days: int,
    units: str,
) -> list:
    """Fetch a forecast per city, reusing a single HTTP client.

    Cities are resolved and fetched sequentially to keep the output ordered
    exactly as supplied and to be kind to the free API. (A production tool
    could gather these with ``asyncio.gather``.)
    """
    results = []
    for city in cities:
        results.append(await _fetch_one(client, cache, city, days, units))
    return results


async def _fetch_one(
    client: OpenMeteoClient,
    cache: WeatherCache,
    city: str,
    days: int,
    units: str,
):
    """Fetch (or serve from cache) a single city's forecast with fallback.

    Order of operations:
      1. Serve a *fresh* cached copy if one exists.
      2. Otherwise hit the network, storing the result in the cache.
      3. If the network fails, fall back to *any* cached copy (stale is
         better than nothing) and warn the user.
    """
    key = config.cache_key(city, days, units)

    fresh = cache.get(key, ttl_seconds=ttl_for("current"))
    if fresh is not None:
        return _forecast_from_payload(fresh)

    try:
        location = await client.geocode(city)
        forecast = await client.fetch_forecast(
            location, day_count=days, units=units
        )
        payload = forecast.model_dump(mode="json")
        # Forecast data is bigger/fresher-tolerant than current; store both
        # under the same key but read with the appropriate TTL.
        cache.set(key, payload, ttl_seconds=ttl_for("forecast"))
        return forecast
    except OpenMeteoError:
        # Network/service failure - degrade to whatever cache we have.
        stale = cache.get_stale(key)
        if stale is not None:
            click.echo(
                f"Warning: offline/error for {city!r}; showing cached data.",
                err=True,
            )
            return _forecast_from_payload(stale)
        raise


def _forecast_from_payload(payload: dict):
    """Deserialise a stored JSON payload back into a :class:`Forecast`."""
    from .models import CurrentWeather, DailyForecast, Forecast, Location

    return Forecast(
        location=Location.model_validate(payload["location"]),
        current=CurrentWeather.model_validate(payload["current"]),
        daily=[DailyForecast.model_validate(d) for d in payload["daily"]],
        units=payload.get("units", "metric"),
    )


# --------------------------------------------------------------------------
# Favorites helpers
# --------------------------------------------------------------------------


def _manage_favorites(*, op: str, city: str) -> None:
    """Add or remove a city from the favorites file with idempotency."""
    favorites = config.load_favorites()
    normalized = city.strip().title()
    if op == "add":
        if normalized in favorites:
            click.echo(f"{city!r} is already a favorite.")
            return
        favorites.append(normalized)
        config.save_favorites(favorites)
        click.echo(f"Added {city!r} to favorites.")
    else:  # remove
        if normalized not in favorites:
            click.echo(f"{city!r} is not a favorite.")
            return
        favorites.remove(normalized)
        config.save_favorites(favorites)
        click.echo(f"Removed {city!r} from favorites.")


def _print_favorites() -> None:
    """Render the favorites list (or a helpful hint when none exist)."""
    favorites = config.load_favorites()
    if not favorites:
        click.echo("No favorites saved. Add some with: weather --add \"Paris\"")
        return
    click.echo("Saved locations:")
    for i, city in enumerate(favorites, 1):
        click.echo(f"  {i}. {city}")
    click.echo("Fetch them:  weather " + " ".join(f'"{c}"' for c in favorites))


if __name__ == "__main__":
    main()