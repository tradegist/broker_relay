"""Typed env getters for the FX-rate enrichment layer.

Each getter validates fail-fast and raises ``SystemExit`` with a
descriptive message on invalid input — callers never need to re-check.
"""

import os
import re

# ISO-4217 codes are 3 uppercase letters.
_ISO_4217_RE = re.compile(r"^[A-Z]{3}$")

# Default retention for the persistent FX-rate cache.
_DEFAULT_CACHE_RETENTION_DAYS = "730"


def get_fx_enabled() -> bool:
    """Return True when FX enrichment is enabled (``FX_RATES_ENABLED``)."""
    val = os.environ.get("FX_RATES_ENABLED", "").strip().lower()
    if not val:
        return False
    if val in ("1", "true", "yes"):
        return True
    if val in ("0", "false", "no"):
        return False
    raise SystemExit(
        f"Invalid FX_RATES_ENABLED={val!r} — must be true/false/yes/no/1/0"
    )


def get_fx_base_currency() -> str:
    """Return the ISO-4217 base currency (``FX_RATES_BASE_CURRENCY``).

    Only called when ``get_fx_enabled()`` is True. Raises ``SystemExit``
    when unset or not a valid 3-letter code.
    """
    raw = os.environ.get("FX_RATES_BASE_CURRENCY", "").strip().upper()
    if not raw:
        raise SystemExit(
            "FX_RATES_BASE_CURRENCY must be set when FX_RATES_ENABLED=true"
            " (ISO-4217 code, e.g. EUR)"
        )
    if not _ISO_4217_RE.match(raw):
        raise SystemExit(
            f"Invalid FX_RATES_BASE_CURRENCY={raw!r} —"
            " must be a 3-letter ISO-4217 code (e.g. EUR, USD, CHF)"
        )
    return raw


def get_fx_api_key() -> str | None:
    """Return the exchangerate-api.com key, or None when not configured."""
    raw = os.environ.get("FX_RATE_API_KEY", "").strip()
    return raw or None


def get_fx_cache_retention_days() -> int:
    """Return the historical-rate retention window (``FX_CACHE_RETENTION_DAYS``).

    Defaults to 730 (2 years). Must be a positive integer.
    """
    raw = os.environ.get(
        "FX_CACHE_RETENTION_DAYS", _DEFAULT_CACHE_RETENTION_DAYS,
    ).strip()
    try:
        val = int(raw)
    except ValueError:
        raise SystemExit(
            f"Invalid FX_CACHE_RETENTION_DAYS={raw!r} — must be a positive integer"
        ) from None
    if val <= 0:
        raise SystemExit(
            f"Invalid FX_CACHE_RETENTION_DAYS={val} — must be > 0"
        )
    return val
