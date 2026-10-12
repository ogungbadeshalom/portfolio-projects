"""Currency formatting helpers.

All money in the codebase is expressed in **integer cents** (base units) and is
never a float.  This module turns integer cents into human-readable currency
strings.

It uses ``babel`` when it is importable (proper symbols + decimal places) and
otherwise falls back to a small pure-stdlib formatter that produces the same,
predictable output.
"""

from __future__ import annotations

import logging
from typing import Dict, Tuple

logger = logging.getLogger(__name__)

try:  # pragma: no cover - exercised only when babel is present
    from babel.numbers import (
        get_currency_name,
        get_currency_symbol,
        format_currency as _babel_format_currency,
    )
except Exception:  # pragma: no cover - babel is optional
    _babel_format_currency = None  # type: ignore[assignment]

# ISO-4217 currency -> (symbol, decimal places)
_CURRENCY_INFO: Dict[str, Tuple[str, int]] = {
    "USD": ("$", 2),
    "EUR": ("€", 2),
    "GBP": ("£", 2),
    "NGN": ("₦", 2),
    "JPY": ("¥", 0),
}


def decimal_places(currency: str) -> int:
    """Number of decimal places the given currency uses (default 2)."""
    return _CURRENCY_INFO.get(currency.upper(), (None, 2))[1]


def supports(currency: str) -> bool:
    """True when the currency has a known minor unit (avoids a float divide)."""
    return currency.upper() in _CURRENCY_INFO


def format_cents(amount_cents: int, currency: str) -> str:
    """Format an integer amount in cents as a human currency string.

    Examples::

        format_cents(12345, "USD")  -> "$123.45"
        format_cents(12345, "EUR")  -> "€123.45"
        format_cents(500, "NGN")    -> "₦5.00"
        format_cents(12345, "JPY")  -> "¥123"   (0 decimal places)

    :raises TypeError: if amount_cents is not an integer
    """
    if not isinstance(amount_cents, int):
        # Guard against accidental float mileage leaking into money math.
        raise TypeError(
            "amount_cents must be an integer (cents), got %r" % type(amount_cents)
        )
    currency = currency.upper()

    if _babel_format_currency is not None:
        try:
            return _babel_format_currency(amount_cents / 100.0, currency)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("babel failed to format %s: %s", currency, exc)

    symbol, places = _CURRENCY_INFO.get(currency, (currency + " ", 2))
    sign = "-" if amount_cents < 0 else ""
    integer_part = abs(amount_cents) // 100
    fractional = abs(amount_cents) % 100
    if places == 0:
        # Round fractional part away to closest whole unit (0.5 rounds up).
        return "%s%s%d" % (sign, symbol, integer_part + (1 if fractional >= 50 else 0))
    return "%s%s%d.%02d" % (sign, symbol, integer_part, fractional)


def currency_symbol(currency: str) -> str:
    """Return just the symbol for a currency (for headers / invoice UI)."""
    currency = currency.upper()
    if _babel_format_currency is not None:
        try:
            return get_currency_symbol(currency, locale="en_US")
        except Exception:  # pragma: no cover - defensive
            pass
    return _CURRENCY_INFO.get(currency, (currency, 2))[0]