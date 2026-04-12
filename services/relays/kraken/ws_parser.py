"""Parse Kraken WebSocket v2 execution messages into Fill models."""

from __future__ import annotations

from shared import BuySell, Fill, OrderType

from .kraken_types import KrakenWsExecution, KrakenWsMessage

# Kraken order type strings -> normalized OrderType.
_ORDER_TYPE_MAP: dict[str, OrderType] = {
    "market": "market",
    "limit": "limit",
    "stop-loss": "stop",
    "stop-loss-limit": "stop_limit",
    "trailing-stop": "trailing_stop",
    "trailing-stop-limit": "trailing_stop",
}


def normalize_order_type(raw: str) -> OrderType | None:
    """Map a Kraken order type string to the normalized OrderType literal."""
    return _ORDER_TYPE_MAP.get(raw)


def parse_executions(msg: KrakenWsMessage) -> tuple[list[Fill], list[str]]:
    """Parse a WS v2 executions channel message.

    Returns (fills, errors) where fills are successfully parsed execution
    events with exec_type == 'trade', and errors are human-readable parse
    error strings (never raises).
    """
    fills: list[Fill] = []
    errors: list[str] = []

    channel = msg.get("channel")
    if channel != "executions":
        return fills, errors

    data = msg.get("data")
    if not isinstance(data, list):
        errors.append(f"executions message missing 'data' list: {list(msg.keys())}")
        return fills, errors

    for item in data:
        if not isinstance(item, dict):
            errors.append(f"executions data item is not a dict: {type(item).__name__}")
            continue

        exec_type = item.get("exec_type")
        if exec_type != "trade":
            continue

        try:
            fill = _parse_fill(item)
            fills.append(fill)
        except Exception as exc:
            exec_id = item.get("exec_id", "unknown")
            errors.append(f"Failed to parse fill exec_id={exec_id}: {exc}")

    return fills, errors


def _parse_fill(item: KrakenWsExecution) -> Fill:
    """Convert a single WS execution message to a Fill model."""
    # Sum fees from the fees array
    total_fee = 0.0
    fees = item.get("fees")
    if isinstance(fees, list):
        for fee_entry in fees:
            if isinstance(fee_entry, dict):
                total_fee += float(fee_entry.get("qty", 0.0))

    side_raw = item.get("side", "")
    if side_raw == "buy":
        side = BuySell.BUY
    elif side_raw == "sell":
        side = BuySell.SELL
    else:
        raise ValueError(f"Invalid execution side: {side_raw!r}")

    order_type = normalize_order_type(str(item.get("order_type", "")))

    return Fill(
        execId=str(item["exec_id"]),
        orderId=str(item["order_id"]),
        symbol=str(item.get("symbol", "")),
        assetClass="crypto",
        side=side,
        orderType=order_type,
        price=float(item.get("last_price", 0.0)),
        volume=float(item.get("last_qty", 0.0)),
        cost=float(item.get("cost", 0.0)),
        fee=abs(total_fee),
        timestamp=str(item.get("timestamp", "")),
        source="ws_execution",
        raw=dict(item),
    )
