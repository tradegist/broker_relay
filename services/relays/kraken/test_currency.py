"""Tests for Kraken pair → ISO-4217 currency resolution."""

import unittest

from relays.kraken.currency import resolve_fx_currency


class TestSlashForm(unittest.TestCase):
    """WS v2 pairs use ``BASE/QUOTE``."""

    def test_btc_usd(self) -> None:
        assert resolve_fx_currency("BTC/USD") == "USD"

    def test_eth_eur(self) -> None:
        assert resolve_fx_currency("ETH/EUR") == "EUR"

    def test_sol_usdt_maps_to_usd(self) -> None:
        assert resolve_fx_currency("SOL/USDT") == "USD"

    def test_sol_usdc_maps_to_usd(self) -> None:
        assert resolve_fx_currency("SOL/USDC") == "USD"

    def test_dai_maps_to_usd(self) -> None:
        assert resolve_fx_currency("ETH/DAI") == "USD"

    def test_eurt_maps_to_eur(self) -> None:
        assert resolve_fx_currency("BTC/EURT") == "EUR"

    def test_crypto_crypto_returns_none(self) -> None:
        assert resolve_fx_currency("ETH/BTC") is None

    def test_unknown_quote_returns_none(self) -> None:
        assert resolve_fx_currency("ETH/MADEUP") is None

    def test_lowercase_ok(self) -> None:
        assert resolve_fx_currency("btc/usd") == "USD"


class TestConcatenatedForm(unittest.TestCase):
    """REST pairs are concatenated, sometimes with Kraken's X/Z prefixes."""

    def test_solusdt_longer_suffix_wins(self) -> None:
        """SOLUSDT must split into (SOL, USDT), not (SOLUSD, T)."""
        assert resolve_fx_currency("SOLUSDT") == "USD"

    def test_xbtusd(self) -> None:
        assert resolve_fx_currency("XBTUSD") == "USD"

    def test_zusd_alias(self) -> None:
        assert resolve_fx_currency("XXBTZUSD") == "USD"

    def test_zeur_alias(self) -> None:
        assert resolve_fx_currency("XXBTZEUR") == "EUR"

    def test_ethusdc(self) -> None:
        assert resolve_fx_currency("ETHUSDC") == "USD"

    def test_crypto_crypto_returns_none(self) -> None:
        assert resolve_fx_currency("XBTETH") is None

    def test_empty_returns_none(self) -> None:
        assert resolve_fx_currency("") is None
