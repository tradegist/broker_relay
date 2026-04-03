import json

from cli import load_env, relay_api, die


def run(args):
    load_env()

    qty = args.quantity
    symbol = args.symbol
    order_type = args.order_type.upper()

    if order_type == "LMT" and args.limit_price is None:
        die("lmtPrice required for LMT orders")

    action = "SELL" if qty < 0 else "BUY"
    abs_qty = abs(qty)
    currency = args.currency or "USD"
    exchange = args.exchange or "SMART"

    payload = {
        "contract": {
            "symbol": symbol,
            "exchange": exchange,
            "currency": currency,
        },
        "order": {
            "action": action,
            "totalQuantity": abs_qty,
            "orderType": order_type,
        },
    }

    if order_type == "LMT":
        payload["order"]["lmtPrice"] = args.limit_price

    price_str = f" @ ${args.limit_price}" if args.limit_price else ""

    print(f"Placing order: {action} {abs_qty} {symbol} {order_type}"
          f"{price_str} ({currency}/{exchange})")

    data = relay_api("/ibkr/order", data=payload)
    print(json.dumps(data, indent=4))
