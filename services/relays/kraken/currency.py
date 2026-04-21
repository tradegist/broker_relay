"""Resolve the asset currency of a Kraken trade pair.

Kraken pairs take several forms:

* WS v2: slash-separated, e.g. ``BTC/USD``, ``ETH/EUR``, ``SOL/USDT``.
* REST: concatenated, sometimes with Kraken's proprietary ``X``/``Z``
  prefixes, e.g. ``XBTUSD``, ``XXBTZUSD``, ``SOLUSDT``.

This module maps whatever quote-side token Kraken uses to the ISO-4217
fiat currency that the FX enrichment layer can look up. Stablecoins that
track a fiat 1:1 are normalised to that fiat (``USDT``/``USDC`` → ``USD``,
``EURT``/``EURC`` → ``EUR``). When the quote is crypto (e.g. ``ETH/BTC``
or unknown), ``None`` is returned — the FX layer will skip enrichment.
"""

# ─── Fiat codes Kraken may use as a quote currency ────────────────
# ISO-4217 codes we pass through untouched.
_FIATS: frozenset[str] = frozenset({
    "USD", "EUR", "CHF", "JPY", "GBP", "CNY", "CNH", "CAD", "AUD",
    "NZD", "SGD", "HKD", "KRW",
})

# Kraken's proprietary prefixed codes → ISO-4217.
_KRAKEN_FIAT_ALIASES: dict[str, str] = {
    "ZUSD": "USD",
    "ZEUR": "EUR",
    "ZCHF": "CHF",
    "ZJPY": "JPY",
    "ZGBP": "GBP",
    "ZCAD": "CAD",
    "ZAUD": "AUD",
}

# Stablecoin symbol → ISO-4217 fiat it tracks 1:1.
_STABLECOINS: dict[str, str] = {
    # USD-pegged
    "USDT": "USD",
    "USDC": "USD",
    "DAI": "USD",
    "PYUSD": "USD",
    "TUSD": "USD",
    "USDP": "USD",
    "FDUSD": "USD",
    # EUR-pegged
    "EURT": "EUR",
    "EURC": "EUR",
    "EURR": "EUR",
    # GBP-pegged
    "GBPT": "GBP",
}

# Precomputed suffix table for _split_concatenated: every known fiat,
# stablecoin, and Kraken alias, ordered longest-first so e.g. "USDT"
# beats "USD" when matching "SOLUSDT". Built once at import time.
_QUOTE_SUFFIXES: tuple[str, ...] = tuple(
    sorted(
        set(_KRAKEN_FIAT_ALIASES) | set(_STABLECOINS) | set(_FIATS),
        key=len, reverse=True,
    )
)


def _normalise_token(token: str) -> str | None:
    """Return the ISO-4217 fiat for *token*, or None if it is not a fiat/stablecoin."""
    t = token.strip().upper()
    if not t:
        return None
    if t in _FIATS:
        return t
    if t in _KRAKEN_FIAT_ALIASES:
        return _KRAKEN_FIAT_ALIASES[t]
    if t in _STABLECOINS:
        return _STABLECOINS[t]
    return None


def _split_concatenated(pair: str) -> tuple[str, str] | None:
    """Split a concatenated Kraken pair like ``XBTUSD`` or ``SOLUSDT`` into (base, quote).

    Tries the longest matching known quote token first (via the
    module-level :data:`_QUOTE_SUFFIXES`) so ``SOLUSDT`` splits into
    (``SOL``, ``USDT``) rather than (``SOLUSD``, ``T``).
    """
    p = pair.strip().upper()
    if not p:
        return None
    for quote in _QUOTE_SUFFIXES:
        if len(p) > len(quote) and p.endswith(quote):
            return p[: -len(quote)], quote
    return None


def resolve_fx_currency(pair: str) -> str | None:
    """Return the ISO-4217 fiat currency of *pair*'s quote side, or None.

    Returns ``None`` for:
    * Empty or unparseable pairs.
    * Crypto/crypto pairs (e.g. ``ETH/BTC``, ``XBTETH``) — the FX layer
      skips these rather than chaining through a reference fiat.
    """
    if not pair:
        return None

    # WS v2 form: "BASE/QUOTE"
    if "/" in pair:
        _, _, quote = pair.partition("/")
        return _normalise_token(quote)

    # REST form: "BASEQUOTE" (concatenated, sometimes X/Z prefixed)
    split = _split_concatenated(pair)
    if split is None:
        return None
    _base, quote = split
    return _normalise_token(quote)
