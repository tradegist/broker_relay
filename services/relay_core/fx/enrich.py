"""Attach FX rates to aggregated trades.

Pure orchestration — all HTTP/SQLite work is delegated to ``FxClient``.
One trade in → one trade out, optionally with ``fxRate``, ``fxRateBase``,
and ``fxRateSource`` populated. Failures produce entries in *errors* but
never abort the batch: a trade that cannot be enriched simply ships
with ``fxRate=None``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from datetime import date as _date

from shared import Trade

from .client import FxClient, FxLookupError

log = logging.getLogger(__name__)


def enrich_trades_with_fx(
    trades: list[Trade],
    *,
    base_currency: str,
    client: FxClient,
    errors: list[str],
    today_provider: Callable[[], _date] | None = None,
) -> list[Trade]:
    """Return a new list of trades with FX fields populated where possible.

    *today_provider* is injectable for tests; defaults to today in UTC.
    """
    today_fn = today_provider or _utc_today
    today = today_fn()

    out: list[Trade] = []
    for trade in trades:
        enriched = _enrich_one(
            trade, base_currency=base_currency, client=client,
            today=today, errors=errors,
        )
        out.append(enriched)
    return out


def _enrich_one(
    trade: Trade, *, base_currency: str, client: FxClient,
    today: _date, errors: list[str],
) -> Trade:
    ccy = trade.currency
    if not ccy:
        # No asset currency available — skip silently. Per the design, we
        # already logged a parse-time skip when this was surprising; at
        # this layer it's expected (e.g. crypto-crypto pairs).
        return trade

    # Same-currency short-circuit — no network call.
    if ccy == base_currency:
        return trade.model_copy(update={
            "fxRate": 1.0,
            "fxRateBase": base_currency,
            "fxRateSource": "historical",
        })

    trade_date = _parse_trade_date(trade.timestamp)

    # Historical path — requires an API key.
    if client.has_api_key and trade_date is not None:
        try:
            rate = client.get_historical_rate(base_currency, ccy, trade_date)
        except FxLookupError as exc:
            msg = f"Trade {trade.orderId}: FX historical fetch failed: {exc}"
            log.warning(msg)
            errors.append(msg)
            return trade
        return trade.model_copy(update={
            "fxRate": round(rate, 8),
            "fxRateBase": base_currency,
            "fxRateSource": "historical",
        })

    # Keyless path — only safe for today. Log + error when the trade is older.
    if trade_date is not None and trade_date < today:
        msg = (
            f"Trade {trade.orderId}: historical FX unavailable "
            f"(trade date {trade_date.isoformat()} < today {today.isoformat()}; "
            "set FX_RATE_API_KEY to enable historical lookups) — fxRate omitted"
        )
        log.warning(msg)
        errors.append(msg)
        return trade

    try:
        rate = client.get_latest_rate(base_currency, ccy)
    except FxLookupError as exc:
        msg = f"Trade {trade.orderId}: FX latest fetch failed: {exc}"
        log.warning(msg)
        errors.append(msg)
        return trade
    return trade.model_copy(update={
        "fxRate": round(rate, 8),
        "fxRateBase": base_currency,
        "fxRateSource": "latest",
    })


def _parse_trade_date(ts: str) -> _date | None:
    """Extract the UTC date from a canonical ``YYYY-MM-DDTHH:MM:SS`` timestamp.

    Every Fill reaching this layer has been normalised by the relay
    adapter via :func:`shared.normalize_timestamp` — no broker-specific
    formats need to be handled here. Returns None only when *ts* is
    empty or somehow not in the canonical form (which would indicate a
    bug upstream).
    """
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts).date()
    except ValueError:
        return None


def _utc_today() -> _date:
    return datetime.now(tz=UTC).date()
