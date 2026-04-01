"""IBKR Flex Poller — polls Trade Confirmation Flex Queries and fires webhooks."""

import hashlib
import hmac
import json
import logging
import os
import sqlite3
import sys
import time
import xml.etree.ElementTree as ET

import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("poller")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
FLEX_TOKEN = os.environ.get("IBKR_FLEX_TOKEN", "")
FLEX_QUERY_ID = os.environ.get("IBKR_FLEX_QUERY_ID", "")
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL_SECONDS", "600"))
TARGET_WEBHOOK_URL = os.environ.get("TARGET_WEBHOOK_URL", "")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")
DB_PATH = os.environ.get("DB_PATH", "/data/poller.db")

FLEX_BASE = "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService"
USER_AGENT = "ibkr-relay/1.0"


# ---------------------------------------------------------------------------
# SQLite — deduplication of processed fills
# ---------------------------------------------------------------------------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS processed_fills (
            exec_id TEXT PRIMARY KEY,
            processed_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    return conn


def get_processed_ids(conn, exec_ids):
    """Return the subset of exec_ids already in the DB."""
    if not exec_ids:
        return set()
    placeholders = ",".join("?" for _ in exec_ids)
    rows = conn.execute(
        f"SELECT exec_id FROM processed_fills WHERE exec_id IN ({placeholders})",
        list(exec_ids),
    ).fetchall()
    return {r[0] for r in rows}


def mark_processed(conn, exec_ids):
    conn.executemany(
        "INSERT OR IGNORE INTO processed_fills (exec_id) VALUES (?)",
        [(eid,) for eid in exec_ids],
    )
    conn.commit()


def prune_old(conn, days=30):
    conn.execute(
        "DELETE FROM processed_fills WHERE processed_at < datetime('now', ?)",
        (f"-{days} days",),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Webhook delivery
# ---------------------------------------------------------------------------
def send_webhook(payload: dict) -> None:
    body = json.dumps(payload, default=str, indent=2)

    if not TARGET_WEBHOOK_URL:
        log.info("Webhook payload (dry-run):\n%s", body)
        return

    signature = hmac.new(
        WEBHOOK_SECRET.encode(), body.encode(), hashlib.sha256
    ).hexdigest()

    try:
        resp = httpx.post(
            TARGET_WEBHOOK_URL,
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Signature-256": f"sha256={signature}",
            },
            timeout=10.0,
        )
        log.info("Webhook sent — status %d", resp.status_code)
    except httpx.HTTPError as exc:
        log.error("Webhook delivery failed: %s", exc)


# ---------------------------------------------------------------------------
# Flex Web Service
# ---------------------------------------------------------------------------
def fetch_flex_report():
    """Two-step Flex Web Service: SendRequest -> GetStatement."""
    headers = {"User-Agent": USER_AGENT}

    # Step 1: request report generation
    resp = httpx.get(
        f"{FLEX_BASE}/SendRequest",
        params={"t": FLEX_TOKEN, "q": FLEX_QUERY_ID, "v": "3"},
        headers=headers,
        timeout=30.0,
    )
    resp.raise_for_status()

    root = ET.fromstring(resp.text)
    if root.findtext("Status") != "Success":
        code = root.findtext("ErrorCode", "?")
        msg = root.findtext("ErrorMessage", "Unknown error")
        log.error("SendRequest failed: [%s] %s", code, msg)
        return None

    ref_code = root.findtext("ReferenceCode")
    log.debug("SendRequest OK — ref=%s, waiting for report...", ref_code)

    # Step 2: poll for the generated report
    for wait in (5, 10, 15, 30):
        time.sleep(wait)
        resp = httpx.get(
            f"{FLEX_BASE}/GetStatement",
            params={"t": FLEX_TOKEN, "q": ref_code, "v": "3"},
            headers=headers,
            timeout=60.0,
        )
        resp.raise_for_status()

        # Error responses are wrapped in <FlexStatementResponse>
        if resp.text.strip().startswith("<FlexStatementResponse"):
            err_root = ET.fromstring(resp.text)
            err_code = err_root.findtext("ErrorCode", "")
            if err_code == "1019":  # generation in progress
                log.debug("Report still generating, retrying...")
                continue
            msg = err_root.findtext("ErrorMessage", "Unknown error")
            log.error("GetStatement failed: [%s] %s", err_code, msg)
            return None

        return resp.text

    log.error("Report generation timed out after retries")
    return None


def parse_trades(xml_text):
    """Parse Flex Query XML for trade records."""
    root = ET.fromstring(xml_text)
    trades = []
    seen = set()

    # Trade Confirmation queries use <TradeConfirmation>,
    # Activity queries use <Trade> and <Order>. We only want <Trade> entries
    # (individual fills), not <Order> (aggregated). Skip <Order> because it
    # has no transactionID and duplicates the fill data.
    for tag in ("TradeConfirmation", "Trade"):
        for el in root.iter(tag):
            exec_id = el.get("transactionID", "") or el.get("ibExecID", "")
            if not exec_id or exec_id in seen:
                continue
            seen.add(exec_id)

            try:
                qty = float(el.get("quantity", 0))
            except (ValueError, TypeError):
                qty = 0.0
            try:
                price = float(el.get("tradePrice", 0) or el.get("price", 0))
            except (ValueError, TypeError):
                price = 0.0
            try:
                commission = float(el.get("ibCommission", 0) or el.get("commission", 0))
            except (ValueError, TypeError):
                commission = 0.0

            trades.append({
                "event": "fill",
                "symbol": el.get("symbol", ""),
                "underlyingSymbol": el.get("underlyingSymbol", ""),
                "secType": el.get("assetCategory", ""),
                "exchange": el.get("listingExchange", "") or el.get("exchange", ""),
                "op": el.get("buySell", ""),
                "quantity": qty,
                "price": price,
                "tradeDate": el.get("tradeDate", ""),
                "tradeTime": el.get("dateTime", ""),
                "orderTime": el.get("orderTime", ""),
                "orderId": el.get("ibOrderID", "") or el.get("orderID", ""),
                "execId": exec_id,
                "account": el.get("accountId", ""),
                "commission": commission,
                "commissionCurrency": el.get("ibCommissionCurrency", ""),
                "currency": el.get("currency", ""),
                "orderType": el.get("orderType", ""),
            })

    return trades


def _ibkr_dt_to_iso(dt_str):
    """Convert IBKR datetime 'YYYYMMDD;HHmmss' to ISO 'YYYY-MM-DDTHH:MM:SS'."""
    try:
        d, t = dt_str.split(";")
        return f"{d[:4]}-{d[4:6]}-{d[6:8]}T{t[:2]}:{t[2:4]}:{t[4:6]}"
    except (ValueError, IndexError):
        return dt_str


def _ibkr_date_to_iso(d):
    """Convert IBKR date 'YYYYMMDD' to ISO 'YYYY-MM-DD'."""
    if len(d) == 8 and d.isdigit():
        return f"{d[:4]}-{d[4:6]}-{d[6:8]}"
    return d


def aggregate_by_order(trades):
    """Group individual fills by orderId, compute weighted avg price."""
    groups = {}
    for t in trades:
        oid = t["orderId"]
        if not oid:
            continue
        groups.setdefault(oid, []).append(t)

    results = []
    for order_id, fills in groups.items():
        total_qty = sum(f["quantity"] for f in fills)
        abs_total = sum(abs(f["quantity"]) for f in fills)
        avg_price = (
            sum(abs(f["quantity"]) * f["price"] for f in fills) / abs_total
            if abs_total else 0.0
        )
        total_commission = sum(f["commission"] for f in fills)

        first = fills[0]
        results.append({
            "event": "fill",
            "symbol": first["symbol"],
            "underlyingSymbol": first["underlyingSymbol"],
            "secType": first["secType"],
            "exchange": first["exchange"],
            "op": first["op"],
            "quantity": total_qty,
            "avgPrice": round(avg_price, 8),
            "tradeDate": _ibkr_date_to_iso(max(f["tradeDate"] for f in fills)),
            "lastFillTime": _ibkr_dt_to_iso(max(f["tradeTime"] for f in fills)),
            "orderTime": _ibkr_dt_to_iso(first["orderTime"]),
            "orderId": order_id,
            "execIds": [f["execId"] for f in fills],
            "account": first["account"],
            "commission": round(total_commission, 4),
            "commissionCurrency": first["commissionCurrency"],
            "currency": first["currency"],
            "orderType": first["orderType"],
            "fillCount": len(fills),
        })

    return results


# ---------------------------------------------------------------------------
# Poll cycle
# ---------------------------------------------------------------------------
def poll_once(conn=None):
    """Run a single poll. Returns number of new webhook calls sent."""
    close_conn = conn is None
    if close_conn:
        conn = init_db()

    try:
        log.info("Polling Flex Web Service...")
        xml_text = fetch_flex_report()
        if xml_text is None:
            return 0

        all_trades = parse_trades(xml_text)
        log.info("Parsed %d individual fill(s) from Flex report", len(all_trades))

        # Always show a sample of the first aggregated order for debugging
        all_orders = aggregate_by_order(all_trades)
        if all_orders:
            log.info("Sample order (first):\n%s", json.dumps(all_orders[0], default=str, indent=2))

        # Filter out already-processed fills
        all_exec_ids = {t["execId"] for t in all_trades}
        already_seen = get_processed_ids(conn, all_exec_ids)
        new_trades = [t for t in all_trades if t["execId"] not in already_seen]
        log.info("%d new fill(s) after dedup", len(new_trades))

        if not new_trades:
            log.info("No new fills")
            return 0

        # Aggregate only the NEW fills by order
        orders = aggregate_by_order(new_trades)
        log.info("Aggregated into %d order(s)", len(orders))

        for order in orders:
            log.info(
                "New fill: %s %s %s @ avgPrice %s (qty %s, %d fill(s))",
                order["op"], order["symbol"], order["orderId"],
                order["avgPrice"], order["quantity"], order["fillCount"],
            )
            send_webhook(order)
            mark_processed(conn, order["execIds"])

        log.info("Sent %d webhook(s)", len(orders))
        return len(orders)
    finally:
        if close_conn:
            conn.close()


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------
def main_loop():
    """Continuous polling loop."""
    if not FLEX_TOKEN or not FLEX_QUERY_ID:
        log.error("IBKR_FLEX_TOKEN and IBKR_FLEX_QUERY_ID must be set")
        raise SystemExit(1)

    log.info("IBKR Flex Poller starting (poll every %ds)", POLL_INTERVAL)
    if not TARGET_WEBHOOK_URL:
        log.info("No TARGET_WEBHOOK_URL — running in dry-run mode")

    conn = init_db()
    prune_old(conn)

    while True:
        try:
            poll_once(conn)
        except Exception:
            log.exception("Poll cycle failed")

        log.debug("Next poll in %ds", POLL_INTERVAL)
        time.sleep(POLL_INTERVAL)


def main_once():
    """Single on-demand poll, then exit."""
    if not FLEX_TOKEN or not FLEX_QUERY_ID:
        log.error("IBKR_FLEX_TOKEN and IBKR_FLEX_QUERY_ID must be set")
        raise SystemExit(1)

    conn = init_db()
    n = poll_once(conn)
    conn.close()
    print(f"Done — {n} new fill(s) processed")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--once":
        main_once()
    else:
        main_loop()
