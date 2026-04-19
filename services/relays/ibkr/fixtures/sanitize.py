"""Sanitize a raw IBKR Flex XML dump into a committable test fixture.

Usage:
    python services/relays/ibkr/fixtures/sanitize.py INPUT.xml OUTPUT.xml

Replaces identifying attribute values (account, order, execution, transaction
IDs) with synthetic constants that match the conventions used in existing
test fixtures (see test_flex_parser.py).  Market data (symbol, conid, ISIN,
CUSIP, FIGI, exchange) is public and kept as-is.  Prices/quantities/P&L are
kept to preserve realistic arithmetic in tests.

The sanitizer is regex-based on ``attr="value"`` pairs so it preserves
the source document's attribute order and whitespace byte-for-byte
apart from the redacted values — ideal for reviewing diffs when the
fixture is refreshed.
"""

import re
import sys
from pathlib import Path

_SANITIZE: dict[str, str] = {
    # Account identifiers
    "accountId": "UXXXXXXX",
    "acctAlias": "",
    "model": "",
    # Trade / order / execution / transaction IDs (shared by AF and TC)
    "tradeID": "1111111111",
    "transactionID": "22222222222",
    "brokerageOrderID": "002e.00018d97.01.01",
    "exchOrderId": "002e.0001.00001",
    "extExecID": "AAAAAA",
    "traderID": "",
    # Activity Flex attribute names
    "ibOrderID": "333333333",
    "ibExecID": "00018d97.00000001.01.01",
    # Trade Confirmation attribute names (same synthetic values — the
    # parser aliases these to ibOrderID/ibExecID, so consistency matters)
    "orderID": "333333333",
    "execID": "00018d97.00000001.01.01",
    # Relational / origin IDs (empty on paper, may carry data in prod)
    "relatedTradeID": "",
    "relatedTransactionID": "",
    "origTradeID": "",
    "origOrderID": "0",
    "origTransactionID": "0",
}


def sanitize(xml_text: str) -> str:
    """Return *xml_text* with sensitive attribute values replaced.

    Uses ``\\b`` word boundaries so that ``tradeID`` does not match
    ``origTradeID`` etc.
    """
    out = xml_text
    for attr, value in _SANITIZE.items():
        pattern = re.compile(rf'\b{re.escape(attr)}="[^"]*"')
        out = pattern.sub(f'{attr}="{value}"', out)
    return out


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit(f"Usage: {sys.argv[0]} INPUT.xml OUTPUT.xml")

    src = Path(sys.argv[1])
    dst = Path(sys.argv[2])
    if not src.exists():
        sys.exit(f"Input file not found: {src}")

    dst.write_text(sanitize(src.read_text()))
    print(f"Wrote sanitized fixture to {dst}")


if __name__ == "__main__":
    main()
