"""Shared Pydantic models — single source of truth for webhook payload types.

Fill  = individual execution from IBKR Flex XML (all known fields).
Trade = one or more fills aggregated by orderId.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict

Source = Literal["flex", "execDetailsEvent", "commissionReportEvent"]


class BuySell(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class Fill(BaseModel):
    """Individual execution / fill from IBKR Flex XML."""

    model_config = ConfigDict(extra="forbid")

    # ── Source ────────────────────────────────────────────────────────────
    source: Source

    # ── Account ──────────────────────────────────────────────────────────
    accountId: str = ""
    acctAlias: str = ""
    model: str = ""

    # ── Currency ─────────────────────────────────────────────────────────
    currency: str = ""
    fxRateToBase: float = 0.0

    # ── Security identification ──────────────────────────────────────────
    assetCategory: str = ""
    subCategory: str = ""
    symbol: str = ""
    description: str = ""
    conid: str = ""
    securityID: str = ""
    securityIDType: str = ""
    cusip: str = ""
    isin: str = ""
    figi: str = ""
    listingExchange: str = ""
    multiplier: str = ""

    # ── Underlying (derivatives) ─────────────────────────────────────────
    underlyingConid: str = ""
    underlyingSymbol: str = ""
    underlyingSecurityID: str = ""
    underlyingListingExchange: str = ""

    # ── Issuer ───────────────────────────────────────────────────────────
    issuer: str = ""
    issuerCountryCode: str = ""

    # ── Options / derivatives ────────────────────────────────────────────
    strike: str = ""
    expiry: str = ""
    putCall: str = ""

    # ── Trade IDs ────────────────────────────────────────────────────────
    tradeID: str = ""
    transactionId: str = ""       # AF: transactionID
    ibExecId: str = ""            # AF: ibExecID, TC: execID
    brokerageOrderID: str = ""
    exchOrderId: str = ""
    extExecID: str = ""

    # ── Order ────────────────────────────────────────────────────────────
    orderId: str = ""             # AF: ibOrderID, TC: orderID
    orderTime: str = ""
    orderType: str = ""
    orderReference: str = ""

    # ── Trade details ────────────────────────────────────────────────────
    transactionType: str = ""
    exchange: str = ""
    buySell: BuySell
    quantity: float = 0.0
    price: float = 0.0            # AF: tradePrice, TC: price

    # ── Financial ────────────────────────────────────────────────────────
    taxes: float = 0.0
    commission: float = 0.0       # AF: ibCommission, TC: commission
    commissionCurrency: str = ""  # AF: ibCommissionCurrency, TC: commissionCurrency
    cost: float = 0.0
    fifoPnlRealized: float = 0.0
    tradeMoney: float = 0.0
    proceeds: float = 0.0
    netCash: float = 0.0
    closePrice: float = 0.0
    mtmPnl: float = 0.0
    accruedInt: float = 0.0

    # ── Dates ────────────────────────────────────────────────────────────
    dateTime: str = ""
    tradeDate: str = ""
    reportDate: str = ""
    settleDateTarget: str = ""

    # ── Position ─────────────────────────────────────────────────────────
    openCloseIndicator: str = ""
    notes: str = ""

    # ── Original trade (corrections) ─────────────────────────────────────
    origTradePrice: str = ""
    origTradeDate: str = ""
    origTradeID: str = ""
    origOrderID: str = ""
    origTransactionID: str = ""

    # ── Clearing / related ───────────────────────────────────────────────
    clearingFirmID: str = ""
    relatedTradeID: str = ""
    relatedTransactionID: str = ""
    rtn: str = ""
    volatilityOrderLink: str = ""

    # ── Timing ───────────────────────────────────────────────────────────
    openDateTime: str = ""
    holdingPeriodDateTime: str = ""
    whenRealized: str = ""
    whenReopened: str = ""

    # ── Metadata ─────────────────────────────────────────────────────────
    levelOfDetail: str = ""
    changeInPrice: str = ""
    changeInQuantity: str = ""
    traderID: str = ""
    isAPIOrder: str = ""
    principalAdjustFactor: str = ""
    initialInvestment: str = ""
    positionActionID: str = ""
    serialNumber: str = ""
    deliveryType: str = ""
    commodityType: str = ""
    fineness: str = ""
    weight: str = ""


class Trade(Fill):
    """Aggregated trade — one or more fills grouped by orderId.

    Numeric fields (quantity, price, commission, taxes, …) are aggregated.
    String fields use the last fill's value.
    ``price`` is the quantity-weighted average across fills.
    """

    execIds: list[str]
    fillCount: int


def _dedup_id(fill: Fill) -> str:
    """Return the best available unique ID for dedup (ibExecId preferred)."""
    return fill.ibExecId or fill.transactionId or fill.tradeID


def aggregate_fills(fills: list[Fill]) -> list[Trade]:
    """Group fills by ``orderId`` and compute aggregated Trade objects.

    * ``quantity`` — sum of all fills.
    * ``price`` — quantity-weighted average.
    * Financial fields (commission, taxes, …) — summed.
    * ``dateTime`` — last fill's value (lexicographic max).
    * String fields — last fill's value.
    * ``execIds`` — ``transactionId`` (or best dedup ID) per fill.
    * ``fillCount`` — number of fills in the group.
    """
    groups: dict[str, list[Fill]] = {}
    for fill in fills:
        if not fill.orderId:
            continue
        groups.setdefault(fill.orderId, []).append(fill)

    trades: list[Trade] = []
    for _order_id, order_fills in groups.items():
        # Weighted average price
        abs_total = sum(abs(f.quantity) for f in order_fills)
        avg_price = (
            sum(abs(f.quantity) * f.price for f in order_fills) / abs_total
            if abs_total else 0.0
        )

        # Sum financial fields
        total_quantity = sum(f.quantity for f in order_fills)
        total_commission = sum(f.commission for f in order_fills)
        total_taxes = sum(f.taxes for f in order_fills)
        total_cost = sum(f.cost for f in order_fills)
        total_trade_money = sum(f.tradeMoney for f in order_fills)
        total_proceeds = sum(f.proceeds for f in order_fills)
        total_net_cash = sum(f.netCash for f in order_fills)
        total_fifo = sum(f.fifoPnlRealized for f in order_fills)
        total_mtm = sum(f.mtmPnl for f in order_fills)
        total_accrued = sum(f.accruedInt for f in order_fills)

        last = order_fills[-1]
        last_dt = max(f.dateTime for f in order_fills) if order_fills else ""

        # Fields that are explicitly overridden below — exclude from the
        # generic dict comprehension to avoid "multiple values" TypeError.
        _OVERRIDE_FIELDS = {
            "quantity", "price", "commission", "taxes", "cost",
            "tradeMoney", "proceeds", "netCash", "fifoPnlRealized",
            "mtmPnl", "accruedInt", "dateTime", "tradeDate",
        }

        # Build Trade from last fill's values, overriding aggregated fields.
        # Explicit kwargs preserve type safety (model_dump() returns
        # dict[str, Any] which defeats mypy checking).
        trades.append(Trade(
            **{
                field: getattr(last, field)
                for field in Fill.model_fields
                if field not in _OVERRIDE_FIELDS
            },
            quantity=total_quantity,
            price=round(avg_price, 8),
            commission=round(total_commission, 4),
            taxes=round(total_taxes, 4),
            cost=round(total_cost, 4),
            tradeMoney=round(total_trade_money, 4),
            proceeds=round(total_proceeds, 4),
            netCash=round(total_net_cash, 4),
            fifoPnlRealized=round(total_fifo, 4),
            mtmPnl=round(total_mtm, 4),
            accruedInt=round(total_accrued, 4),
            dateTime=last_dt,
            tradeDate=max(f.tradeDate for f in order_fills),
            execIds=[_dedup_id(f) for f in order_fills],
            fillCount=len(order_fills),
        ))

    return trades


# ── POST /ibkr/poller/run ────────────────────────────────────────────

class WebhookPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trades: list[Trade]
    errors: list[str]


class RunPollResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trades: list[Trade]


# ── GET /health ──────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str


# ── Schema export (used by schema_gen.py → make types) ──────────────

SCHEMA_MODELS: list[type[BaseModel]] = [
    WebhookPayload,
    RunPollResponse,
    HealthResponse,
]
