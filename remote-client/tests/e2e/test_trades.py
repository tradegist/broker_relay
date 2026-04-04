"""E2E tests — GET /ibkr/trades returns placed orders."""

import time

import httpx


def test_trades_requires_auth(anon_api: httpx.Client) -> None:
    resp = anon_api.get("/ibkr/trades")
    assert resp.status_code == 401


def test_market_order_appears_in_trades(api: httpx.Client) -> None:
    """Place a small MKT order, then verify it shows up in /ibkr/trades."""
    order_resp = api.post(
        "/ibkr/order",
        json={
            "contract": {"symbol": "AAPL"},
            "order": {
                "action": "BUY",
                "totalQuantity": 1,
                "orderType": "MKT",
            },
        },
    )
    assert order_resp.status_code == 200, order_resp.text
    order_data = order_resp.json()
    perm_id = order_data["permId"]

    # Poll /ibkr/trades until the order appears (max 10 s).
    deadline = time.monotonic() + 10
    found = False
    while time.monotonic() < deadline:
        trades_resp = api.get("/ibkr/trades")
        assert trades_resp.status_code == 200
        trades = trades_resp.json()["trades"]
        if any(t["permId"] == perm_id for t in trades):
            found = True
            break
        time.sleep(0.5)

    assert found, f"Trade with permId={perm_id} not found within 10 s"

    trade = next(t for t in trades if t["permId"] == perm_id)
    assert trade["action"] == "BUY"
    assert trade["symbol"] == "AAPL"
    assert trade["orderType"] == "MKT"
    assert trade["totalQuantity"] == 1.0
    assert trade["status"] in ("Filled", "PreSubmitted", "Submitted")
