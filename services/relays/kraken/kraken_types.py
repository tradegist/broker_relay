"""TypedDicts for raw Kraken API structures.

These mirror the official Kraken API documentation and are used to type
external data at the system boundary. Once validated and mapped into
Pydantic models (Fill, Trade), internal code uses those models instead.

References:
- WS v2 executions: https://docs.kraken.com/api/docs/websocket-v2/executions
- REST TradesHistory: https://docs.kraken.com/api/docs/rest-api/get-trade-history
"""

from typing import TypedDict

# ---------------------------------------------------------------------------
# WebSocket v2 — executions channel
# ---------------------------------------------------------------------------


class KrakenWsFee(TypedDict):
    """Single fee entry in a WS v2 execution event."""

    asset: str
    qty: float


class KrakenWsExecution(TypedDict, total=False):
    """WS v2 execution event (exec_type == 'trade').

    Only fields relevant to trade events are included.
    ``total=False`` because many fields are conditional on exec_type.
    """

    exec_type: str
    exec_id: str
    order_id: str
    symbol: str
    side: str
    order_type: str
    last_price: float
    last_qty: float
    cost: float
    fees: list[KrakenWsFee]
    timestamp: str
    order_status: str
    order_qty: float
    cum_qty: float
    cum_cost: float
    avg_price: float
    fee_usd_equiv: float
    liquidity_ind: str
    trade_id: int
    margin: bool


class KrakenWsMessage(TypedDict, total=False):
    """Top-level WS v2 message envelope."""

    channel: str
    type: str
    data: list[KrakenWsExecution]


# ---------------------------------------------------------------------------
# REST — /0/private/TradesHistory
# ---------------------------------------------------------------------------


class KrakenRestTrade(TypedDict, total=False):
    """Single trade entry from the REST TradesHistory endpoint.

    All value fields are strings in the REST response (prices,
    volumes, fees) — the parser converts them to float.
    """

    ordertxid: str
    postxid: str
    pair: str
    time: float
    type: str
    ordertype: str
    price: str
    cost: str
    fee: str
    vol: str
    margin: str
    leverage: str
    misc: str
    ledgers: list[str]
    trade_id: int
    maker: bool
