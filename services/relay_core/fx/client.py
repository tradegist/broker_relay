"""HTTP client for exchangerate-api.com with per-process + persistent caches.

The public API (``FxClient.get_rate``) returns a rate in the convention
callers expect: *units of base per 1 unit of asset_ccy*, such that
``cost * rate == cost_in_base``. The upstream API returns the opposite
direction (``base → quote``), so every rate we cache and return is the
inverse of the raw API response.

Failures (HTTP errors, timeouts, unknown currency) raise
``FxLookupError``; callers decide whether to log, append to the errors
array, or proceed without an fxRate.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date as _date
from typing import Any

import httpx

from . import store

log = logging.getLogger(__name__)

# Free tier — latest rates only (no date path).
_OPEN_URL = "https://open.er-api.com/v6/latest/{base}"

# Paid tier — historical rates at daily granularity.
_PAID_HISTORICAL_URL = (
    "https://v6.exchangerate-api.com/v6/{key}/history/{base}/{year}/{month}/{day}"
)

_LATEST_TTL_SECONDS = 3600  # 1h
_HTTP_TIMEOUT_SECONDS = 2.0


class FxLookupError(RuntimeError):
    """A single FX rate could not be resolved."""


@dataclass
class _LatestEntry:
    rates: dict[str, float]
    fetched_at: float


@dataclass
class FxClient:
    """Fetch FX rates from exchangerate-api.com with caching.

    ``api_key`` enables historical lookups; without it only the keyless
    "latest" endpoint is available.

    Thread safety: the in-memory caches are guarded by a lock; the SQLite
    connection is opened per-call on the current thread and closed
    immediately afterwards (SQLite connections are not thread-safe).
    """

    api_key: str | None
    # None defers to the store's own default (no round-trip through a
    # constant the client doesn't own).
    db_path: str | None = None
    # Injected for tests; defaults to httpx.get for production use.
    http_get: Callable[..., httpx.Response] = field(
        default=httpx.get, repr=False,
    )
    _latest: dict[str, _LatestEntry] = field(default_factory=dict, init=False, repr=False)
    _historical_mem: dict[tuple[str, str, str], float] = field(
        default_factory=dict, init=False, repr=False,
    )
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    # ── Public API ─────────────────────────────────────────────────

    @property
    def has_api_key(self) -> bool:
        return self.api_key is not None

    def get_historical_rate(
        self, base: str, asset_ccy: str, trade_date: _date,
    ) -> float:
        """Return the rate for ``1 asset_ccy = X base`` on *trade_date*.

        Requires an API key. Uses memory + SQLite cache; only hits the
        network on a cache miss. Raises :class:`FxLookupError` when the
        API is unreachable, returns a non-2xx response, or lacks the
        requested currency.
        """
        api_key = self.api_key
        if api_key is None:
            raise FxLookupError("historical FX lookup requires FX_RATE_API_KEY")

        date_key = trade_date.isoformat()
        cache_key = (date_key, base, asset_ccy)
        with self._lock:
            cached = self._historical_mem.get(cache_key)
        if cached is not None:
            return cached

        # L2 (SQLite): one row per (date, base, ccy).  Look up ONLY the
        # currency the caller asked about — siblings (if persisted on a prior
        # run) get promoted to memory lazily, the first time they are asked.
        conn = store.init_fx_db(self.db_path)
        try:
            cached_db = store.lookup_rate(conn, date_key, base, asset_ccy)
        finally:
            conn.close()
        if cached_db is not None:
            with self._lock:
                # Warm L1 for the single key we just fetched from L2.
                self._historical_mem[cache_key] = cached_db
            return cached_db

        # L3 (HTTP): the upstream response contains rates for ~160
        # currencies at once.  Invert them all up-front so the rest of the
        # flow works in the caller-facing "asset → base" direction.
        rates = self._fetch_historical_rates(api_key, base, trade_date)
        inverted_rates = {ccy: 1.0 / rate for ccy, rate in rates.items() if rate > 0}

        # Warm L1 for EVERY currency the API returned (not just asset_ccy).
        # This is what makes sibling lookups in the same batch cheap:
        # e.g. for a poll cycle with trades in USD, CHF and GBP, only the
        # first trade hits L3; the next two find their rate already in L1.
        with self._lock:
            for ccy, inv in inverted_rates.items():
                self._historical_mem[(date_key, base, ccy)] = inv

        # Persist all currencies in a single transaction.
        conn = store.init_fx_db(self.db_path)
        try:
            store.store_rates(conn, date_key, base, inverted_rates)
        finally:
            conn.close()

        inverted = inverted_rates.get(asset_ccy.upper())
        if inverted is None:
            raise FxLookupError(
                f"FX rate {asset_ccy}→{base} unavailable ({date_key})"
            )
        return inverted

    def get_latest_rate(self, base: str, asset_ccy: str) -> float:
        """Return the most recent rate for ``1 asset_ccy = X base``.

        Uses the free keyless endpoint. In-memory cache with 1h TTL.
        """
        now = time.time()
        with self._lock:
            entry = self._latest.get(base)
            if entry is not None and (now - entry.fetched_at) < _LATEST_TTL_SECONDS:
                return _invert_for(entry.rates, asset_ccy, base, trade_date="latest")

        rates = self._fetch_latest_rates(base)
        with self._lock:
            self._latest[base] = _LatestEntry(rates=rates, fetched_at=now)
        return _invert_for(rates, asset_ccy, base, trade_date="latest")

    # ── Network ────────────────────────────────────────────────────

    def _fetch_historical_rates(
        self, api_key: str, base: str, trade_date: _date,
    ) -> dict[str, float]:
        url = _PAID_HISTORICAL_URL.format(
            key=api_key, base=base,
            year=trade_date.year,
            month=trade_date.month,
            day=trade_date.day,
        )
        try:
            resp = self.http_get(url, timeout=_HTTP_TIMEOUT_SECONDS)
        except httpx.HTTPError as exc:
            raise FxLookupError(
                f"FX historical fetch failed ({base} @ {trade_date.isoformat()}): {exc}"
            ) from exc
        if resp.status_code != 200:
            raise FxLookupError(
                f"FX historical fetch returned HTTP {resp.status_code} "
                f"({base} @ {trade_date.isoformat()})"
            )
        data = resp.json()
        return _extract_rates(data, source="historical")

    def _fetch_latest_rates(self, base: str) -> dict[str, float]:
        url = _OPEN_URL.format(base=base)
        try:
            resp = self.http_get(url, timeout=_HTTP_TIMEOUT_SECONDS)
        except httpx.HTTPError as exc:
            raise FxLookupError(
                f"FX latest fetch failed ({base}): {exc}"
            ) from exc
        if resp.status_code != 200:
            raise FxLookupError(
                f"FX latest fetch returned HTTP {resp.status_code} ({base})"
            )
        data = resp.json()
        return _extract_rates(data, source="latest")


# ── Helpers ──────────────────────────────────────────────────────────

def _extract_rates(data: Any, source: str) -> dict[str, float]:
    """Normalise rates dict from either endpoint into ``{ccy: rate}`` floats."""
    if not isinstance(data, dict):
        raise FxLookupError(f"FX {source} response is not a JSON object")
    result = data.get("result")
    # exchangerate-api.com returns {"result": "success"} on success,
    # {"result": "error", "error-type": "..."} on failure.
    if result == "error":
        err = data.get("error-type", "unknown")
        raise FxLookupError(f"FX {source} API error: {err}")
    # Both endpoints use "rates" (open) or "conversion_rates" (paid).
    rates = data.get("conversion_rates") or data.get("rates")
    if not isinstance(rates, dict):
        raise FxLookupError(
            f"FX {source} response missing 'rates'/'conversion_rates' object"
        )
    out: dict[str, float] = {}
    for k, v in rates.items():
        if isinstance(k, str) and isinstance(v, (int, float)) and v > 0:
            out[k.upper()] = float(v)
    if not out:
        raise FxLookupError(f"FX {source} response had no usable rates")
    return out


def _invert_for(
    base_to_quote: dict[str, float], asset_ccy: str, base: str, trade_date: str,
) -> float:
    """Convert ``base → quote`` into ``1 asset_ccy = X base``."""
    rate = base_to_quote.get(asset_ccy.upper())
    if rate is None or rate <= 0:
        raise FxLookupError(
            f"FX rate {asset_ccy}→{base} unavailable ({trade_date})"
        )
    return 1.0 / rate
