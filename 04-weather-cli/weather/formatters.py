"""Output formatters: pretty Rich tables and JSON.

Two formatters are provided:

* :func:`format_pretty` - a human-friendly Rich table (gracefully degrades to
  plain terminal text if the optional ``rich`` dependency is unavailable).
* :func:`format_json`   - a stable, machine-readable JSON serialisation.

Both consume a :class:`~weather.models.Forecast` and respect the ``units``
carried on it when labelling temperatures.
"""

from __future__ import annotations

import json
from typing import Optional

from .api import describe_wmo
from .models import Forecast

# Unit labels used when annotating rendered values.
_UNIT_LABELS = {
    "forecast": {"metric": "°C", "imperial": "°F"},
    "wind": {"metric": "km/h", "imperial": "mph"},
    "precip": {"metric": "mm", "imperial": "in"},
}

# WMO code -> emoji icon. Used when emoji output is enabled.
_WMO_EMOJI: dict[int, str] = {
    0: "☀️",
    1: "🌤️",
    2: "⛅",
    3: "☁️",
    45: "🌫️",
    48: "🌫️",
    51: "🌦️",
    53: "🌦️",
    55: "🌧️",
    56: "🌧️",
    57: "🌧️",
    61: "🌧️",
    63: "🌧️",
    65: "🌧️",
    66: "🌧️",
    67: "🌧️",
    71: "🌨️",
    73: "🌨️",
    75: "❄️",
    77: "❄️",
    80: "🌦️",
    81: "🌧️",
    82: "⛈️",
    85: "🌨️",
    86: "❄️",
    95: "⛈️",
    96: "⛈️",
    99: "⛈️",
}


def _emoji_or(code: Optional[int], no_emoji: bool) -> str:
    """Return an emoji icon for a WMO code (or ASCII fallback)."""
    icon = _WMO_EMOJI.get(code, "🌡️")
    if no_emoji:
        description = describe_wmo(code)
        return f"[{description}]"
    return icon


def format_json(forecast: Forecast) -> str:
    """Return a compact JSON string for a :class:`Forecast`.

    The output follows a stable shape::

        {
          "location": {...},
          "current": {...},
          "daily": [...],
          "units": "metric"
        }
    """
    return json.dumps(
        forecast.model_dump(mode="json"),
        indent=2,
        ensure_ascii=False,
        sort_keys=False,
    )


def format_pretty(forecast: Forecast, *, no_emoji: bool = False) -> str:
    """Render a :class:`Forecast` as a pretty, multi-line string.

    Uses Rich tables when ``rich`` is installed, otherwise falls back to a
    plain, aligned plain-text layout (handy for thin terminals or piping).
    """
    try:
        from rich.console import Console
        from rich.table import Table
    except ImportError:
        return _plain_format(forecast, no_emoji=no_emoji)

    # Top-level caption: "Lagos, Nigeria  ·  Cloudy, 28°C".
    title = f"{_location_label(forecast.location)}  ·  {_summary_line(forecast, no_emoji)}"

    if not forecast.daily:
        # Current conditions only - a simple tree of key/value lines is nicer
        # than a one-row table.
        console = Console()
        with console.capture() as capture:
            console.print(title, style="bold")
            console.print(_current_lines(forecast))
        return capture.get().rstrip()

    table = Table(title=title, show_header=True, header_style="bold magenta")
    table.add_column("Date")
    table.add_column("Weather", min_width=16)
    table.add_column("Temp", justify="right")
    table.add_column("Precip", justify="right")
    table.add_column("Wind", justify="right")

    degree = _unit_labels(forecast.units)["degree"]
    for day in forecast.daily:
        temp_low = _fmt_float(day.temp_min)
        temp_high = _fmt_float(day.temp_max)
        precip = _fmt_float(day.precipitation_sum)
        wind = _fmt_float(day.wind_speed_max)
        table.add_row(
            day.date,
            f"{_emoji_or(day.weather_code, no_emoji)} {describe_wmo(day.weather_code)}",
            f"{temp_low} / {temp_high} {degree}",
            f"{precip} " + _unit_labels(forecast.units)["precip"],
            f"{wind} " + _unit_labels(forecast.units)["wind"] if wind else "-",
        )

    console = Console()
    with console.capture() as capture:
        console.print(table)
        console.print("")
        console.print("\n".join(_current_lines(forecast)))
    return capture.get().rstrip()


# ---------------------------------------------------------------------- #
# Shared helpers                                                          #
# ---------------------------------------------------------------------- #


def _location_label(location) -> str:
    parts = [location.name]
    if location.admin1:
        parts.append(str(location.admin1))
    if location.country:
        parts.append(str(location.country))
    return ", ".join(parts)


def _unit_labels(units: str) -> dict:
    degree = _UNIT_LABELS["forecast"].get(units, "°")
    return {
        "degree": degree,
        "wind": _UNIT_LABELS["wind"].get(units, "km/h"),
        "precip": _UNIT_LABELS["precip"].get(units, "mm"),
    }


def _fmt_float(value) -> str:
    """Format a number tightly (strip trailing ``.0``)."""
    if value is None:
        return "-"
    return f"{value:g}" if float(value).is_integer() else f"{value:.1f}"


def _summary_line(forecast: Forecast, no_emoji: bool) -> str:
    cur = forecast.current
    weather = f"{_emoji_or(cur.weather_code, no_emoji)} "
    temp = f"{_fmt_float(cur.temperature)}{_unit_labels(forecast.units)['degree']}"
    desc = describe_wmo(cur.weather_code)
    return f"{weather}{desc}, {temp}"


def _current_lines(forecast: Forecast) -> list[str]:
    """Render the current conditions as ``label: value`` lines."""
    cur = forecast.current
    labels = _unit_labels(forecast.units)
    degree = labels["degree"]
    lines: list[str] = []
    lines.append(f"Now:        {_fmt_float(cur.temperature)}{degree}")
    if cur.feels_like is not None:
        lines.append(f"Feels like: {_fmt_float(cur.feels_like)}{degree}")
    if cur.relative_humidity is not None:
        lines.append(f"Humidity:   {cur.relative_humidity}%")
    if cur.wind_speed is not None:
        lines.append(f"Wind:       {_fmt_float(cur.wind_speed)} {labels['wind']}")
    if cur.precipitation is not None:
        lines.append(
            f"Rain:       {_fmt_float(cur.precipitation)} {labels['precip']}"
        )
    return lines


def _plain_format(forecast: Forecast, *, no_emoji: bool) -> str:
    """Fallback plain-text renderer used when ``rich`` is not installed."""
    lines: list[str] = []
    lines.append(_location_label(forecast.location))
    lines.append(_summary_line(forecast, no_emoji))
    lines.extend(_current_lines(forecast))
    if forecast.daily:
        degree = _unit_labels(forecast.units)["degree"]
        lines.append("")
        lines.append("Forecast:")
        for day in forecast.daily:
            desc = describe_wmo(day.weather_code)
            low = _fmt_float(day.temp_min)
            high = _fmt_float(day.temp_max)
            lines.append(
                f"  {day.date}: {_emoji_or(day.weather_code, no_emoji)} {desc}  "
                f"{low}/{high}{degree}"
            )
    return "\n".join(lines)