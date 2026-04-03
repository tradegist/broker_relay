"""Pydantic models for the remote-client REST API (order placement)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ── Strict union types aligned with ib_async ─────────────────────────

Action = Literal["BUY", "SELL"]

OrderType = Literal["MKT", "LMT"]

SecType = Literal[
    "STK", "OPT", "FUT", "IND", "FOP", "CASH",
    "CFD", "BAG", "WAR", "BOND", "CMDTY", "NEWS",
    "FUND", "CRYPTO", "EVENT",
]

TimeInForce = Literal["DAY", "GTC", "IOC", "GTD", "OPG", "FOK", "DTC"]


# ── Request models ───────────────────────────────────────────────────

class ContractRequest(BaseModel):
    """Contract fields for identifying the instrument (mirrors ib_async.Contract)."""

    model_config = ConfigDict(extra="forbid")

    symbol: str
    secType: SecType = "STK"
    exchange: str = "SMART"
    currency: str = "USD"
    primaryExchange: str = ""


class OrderRequest(BaseModel):
    """Order fields for specifying the trade (mirrors ib_async.Order)."""

    model_config = ConfigDict(extra="forbid")

    action: Action
    totalQuantity: float = Field(gt=0)
    orderType: OrderType
    lmtPrice: float | None = None
    tif: TimeInForce = "DAY"
    outsideRth: bool = False


class PlaceOrderRequest(BaseModel):
    """Top-level request body for POST /ibkr/order."""

    model_config = ConfigDict(extra="forbid")

    contract: ContractRequest
    order: OrderRequest


# ── Response models ──────────────────────────────────────────────────

class OrderResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    orderId: int
    action: Action
    symbol: str
    totalQuantity: float
    orderType: OrderType
    lmtPrice: float | None = None
