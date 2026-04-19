"""Sanitize a raw IBKR Flex XML dump into a committable test fixture.

Usage:
    python services/relays/ibkr/fixtures/sanitize.py INPUT.xml OUTPUT.xml

Replaces identifying attribute values (account, order, execution, transaction
IDs) with synthetic values.  Market data (symbol, conid, ISIN, CUSIP, FIGI,
exchange) is public and kept as-is.  Prices/quantities/P&L are kept to
preserve realistic arithmetic in tests.

Two classes of sanitization:

* **Static** attrs (``accountId``, ``acctAlias``, ``model``, origin/related
  IDs) get a single constant that is identical across every row — these are
  account-level facts that don't vary between fills.

* **Per-row** attrs (``tradeID``, ``ibExecID``/``execID``,
  ``ibOrderID``/``orderID``, ``transactionID``, ``brokerageOrderID``,
  ``exchOrderId``, ``extExecID``) get a 1-indexed counter substituted into
  a template, so the 1st row gets ``{n}=1``, the 2nd ``{n}=2``, etc.  This
  matters because the parser dedups on execId — without per-row uniqueness,
  a multi-trade dump would collapse to a single fill.

Regex-based on ``attr="value"`` pairs so attribute order and whitespace in
the source document are preserved byte-for-byte apart from the redacted
values — ideal for reviewing diffs when the fixture is refreshed.

Idempotent: re-running on an already-sanitized file produces identical
output (row 1 always gets ``{n}=1``, row 2 always gets ``{n}=2``, etc.).
"""

import re
import sys
from collections.abc import Callable
from itertools import count
from pathlib import Path
from re import Match

# Account-level — identical value across all rows.
_STATIC: dict[str, str] = {
    "accountId": "UXXXXXXX",
    "acctAlias": "",
    "model": "",
    "traderID": "",
    # Relational / origin IDs (empty on paper; redact defensively for prod).
    "relatedTradeID": "",
    "relatedTransactionID": "",
    "origTradeID": "",
    "origOrderID": "0",
    "origTransactionID": "0",
}

# Per-row — ``{n}`` is a 1-indexed occurrence counter.  Each match of
# ``attr="..."`` in the document gets the next counter value, keeping row
# IDs unique so the parser's execId-based dedup doesn't collapse them.
_PER_ROW: dict[str, str] = {
    # Shared by AF and TC
    "tradeID": "111111111{n}",
    "transactionID": "2222222222{n}",
    "brokerageOrderID": "002e.00018d9{n}.01.01",
    "exchOrderId": "002e.0001.0000{n}",
    "extExecID": "AAAAA{n}",
    # Activity Flex attribute names
    "ibOrderID": "33333333{n}",
    "ibExecID": "00018d97.0000000{n}.01.01",
    # Trade Confirmation attribute names (aliased to ibOrderID/ibExecID
    # by the parser — use the same template so sanitized AF and TC
    # fixtures produce identical execIds at equal row indices).
    "orderID": "33333333{n}",
    "execID": "00018d97.0000000{n}.01.01",
}


def _counting_replacer(attr: str, template: str) -> Callable[[Match[str]], str]:
    """Return an ``re.sub`` callback that expands ``{n}`` per occurrence."""
    counter = count(1)
    def replace(_match: Match[str]) -> str:
        return f'{attr}="{template.format(n=next(counter))}"'
    return replace


def sanitize(xml_text: str) -> str:
    """Return *xml_text* with sensitive attribute values replaced.

    Uses ``\\b`` word boundaries so that ``tradeID`` does not match
    ``origTradeID`` (and similar prefix/suffix overlaps).
    """
    out = xml_text
    for attr, value in _STATIC.items():
        pattern = rf'\b{re.escape(attr)}="[^"]*"'
        out = re.sub(pattern, f'{attr}="{value}"', out)
    for attr, template in _PER_ROW.items():
        pattern = rf'\b{re.escape(attr)}="[^"]*"'
        out = re.sub(pattern, _counting_replacer(attr, template), out)
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
