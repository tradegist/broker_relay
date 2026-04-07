"""IBKR Flex XML parser — extracts fills and aggregates into trades."""

import logging
import xml.etree.ElementTree as ET
from typing import Any

from models_poller import Fill, _dedup_id

log = logging.getLogger("flex_parser")

# ── XML attribute → canonical Fill field name ────────────────────────────
# Only attributes whose XML name differs from the canonical model field.
# Attributes with the same name (e.g. "symbol", "currency") map directly.
_ATTR_ALIASES: dict[str, str] = {
    # Activity Flex <Trade>
    "ibCommission": "commission",
    "ibCommissionCurrency": "commissionCurrency",
    "ibOrderID": "orderId",
    "tradePrice": "price",
    "ibExecID": "ibExecId",
    "transactionID": "transactionId",
    # Trade Confirmation <TradeConfirm> / <TradeConfirmation>
    "orderID": "orderId",
    "execID": "ibExecId",
    "tax": "taxes",
    "settleDate": "settleDateTarget",
    "amount": "tradeMoney",
}

# Fill fields that are parsed as float (needed for aggregation).
_FLOAT_FIELDS: frozenset[str] = frozenset({
    "fxRateToBase", "quantity", "price", "taxes", "commission",
    "cost", "fifoPnlRealized", "tradeMoney", "proceeds", "netCash",
    "closePrice", "mtmPnl", "accruedInt",
})

# All known canonical field names on Fill.
_KNOWN_FIELDS: frozenset[str] = frozenset(Fill.model_fields.keys())

# XML tags that represent individual fills.
_FILL_TAGS: tuple[str, ...] = ("TradeConfirmation", "TradeConfirm", "Trade")


# ── Helpers ──────────────────────────────────────────────────────────────

def _parse_float(value: str, field: str, errors: list[str]) -> float:
    """Safely parse a string to float, appending to *errors* on failure."""
    if not value:
        return 0.0
    try:
        return float(value)
    except (ValueError, TypeError):
        errors.append(f"Bad float for '{field}': {value!r}")
        return 0.0


# ── Parse ────────────────────────────────────────────────────────────────

def parse_fills(xml_text: str) -> tuple[list[Fill], list[str]]:
    """Parse Flex XML into individual Fill objects.

    Returns ``(fills, errors)`` where *errors* contains warnings about
    unknown attributes and any per-row parse problems.  Parsing never
    raises — broken rows are skipped and reported in *errors*.
    """
    fills: list[Fill] = []
    errors: list[str] = []

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        errors.append(f"Failed to parse Flex XML: {exc}")
        return fills, errors

    seen: set[str] = set()
    reported_unknown: set[str] = set()

    for tag in _FILL_TAGS:
        for el in root.iter(tag):
            row_errors: list[str] = []

            # Map XML attributes → canonical names
            raw: dict[str, Any] = {}
            for attr_name, attr_value in el.attrib.items():
                canonical = _ATTR_ALIASES.get(attr_name, attr_name)
                if canonical in _KNOWN_FIELDS:
                    raw[canonical] = attr_value
                elif attr_name not in reported_unknown:
                    reported_unknown.add(attr_name)

            # Parse float fields
            kwargs: dict[str, Any] = {}
            for field_name, value in raw.items():
                if field_name in _FLOAT_FIELDS:
                    kwargs[field_name] = _parse_float(value, field_name, row_errors)
                else:
                    kwargs[field_name] = value

            # Dedup within this XML document
            try:
                fill = Fill(**kwargs, source="flex")
            except Exception as exc:
                errors.append(f"Failed to create Fill from <{tag}>: {exc}")
                continue

            did = _dedup_id(fill)
            if not did or did in seen:
                continue
            seen.add(did)

            if row_errors:
                errors.extend(row_errors)

            fills.append(fill)

    if reported_unknown:
        errors.insert(
            0, f"Unknown XML attributes (ignored): {', '.join(sorted(reported_unknown))}"
        )

    return fills, errors
