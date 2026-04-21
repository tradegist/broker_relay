"""FX-rate enrichment for outbound trades.

Engines call :func:`enrich_if_enabled` after aggregation and before
notifying. When FX is disabled, the function is a no-op that returns
the input trades unchanged.
"""

import logging
import threading

from shared import Trade

from .client import FxClient
from .config import (
    get_fx_api_key,
    get_fx_base_currency,
    get_fx_cache_retention_days,
    get_fx_enabled,
)
from .enrich import enrich_trades_with_fx
from .store import init_fx_db
from .store import prune as prune_fx_cache

log = logging.getLogger(__name__)


# Resolved once per process at first use.
_CONFIG_LOCK = threading.Lock()
_CONFIG: "_FxConfig | None" = None
_WARNED_KEYLESS = False


class _FxConfig:
    """Process-wide FX config + lazily-constructed client."""

    __slots__ = ("base", "client", "enabled")

    def __init__(self) -> None:
        self.enabled = get_fx_enabled()
        if not self.enabled:
            self.base = ""
            self.client: FxClient | None = None
            return
        self.base = get_fx_base_currency()
        api_key = get_fx_api_key()
        self.client = FxClient(api_key=api_key)
        _maybe_prune_cache()
        _maybe_warn_keyless(api_key)


def _get_config() -> _FxConfig:
    global _CONFIG
    if _CONFIG is not None:
        return _CONFIG
    with _CONFIG_LOCK:
        if _CONFIG is None:
            _CONFIG = _FxConfig()
    return _CONFIG


def _maybe_prune_cache() -> None:
    """Prune expired historical cache entries once per startup."""
    try:
        retention = get_fx_cache_retention_days()
        conn = init_fx_db()
        try:
            prune_fx_cache(conn, retention)
        finally:
            conn.close()
    except Exception:
        log.exception("Failed to prune FX cache")


def _maybe_warn_keyless(api_key: str | None) -> None:
    global _WARNED_KEYLESS
    if api_key is None and not _WARNED_KEYLESS:
        log.warning(
            "FX_RATES_ENABLED=true but FX_RATE_API_KEY is not set — "
            "only today's trades will be enriched (keyless endpoint has no history)"
        )
        _WARNED_KEYLESS = True


def enrich_if_enabled(
    trades: list[Trade], errors: list[str],
) -> list[Trade]:
    """Enrich *trades* with FX rates in place of the caller.

    * No-op when ``FX_RATES_ENABLED`` is false.
    * Appends human-readable errors to *errors* for trades that could
      not be enriched (unknown currency, upstream failure, keyless +
      historical, etc.).
    """
    cfg = _get_config()
    if not cfg.enabled or cfg.client is None:
        return trades
    return enrich_trades_with_fx(
        trades, base_currency=cfg.base, client=cfg.client, errors=errors,
    )


def _reset_for_tests() -> None:
    """Reset cached config — tests only."""
    global _CONFIG, _WARNED_KEYLESS
    with _CONFIG_LOCK:
        _CONFIG = None
        _WARNED_KEYLESS = False
