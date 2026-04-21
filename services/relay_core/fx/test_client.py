"""Tests for FxClient — HTTP fetch + in-memory/persistent cache."""

import tempfile
import unittest
from datetime import date
from pathlib import Path
from typing import Any
from unittest import mock

import httpx

from relay_core.fx import store
from relay_core.fx.client import FxClient, FxLookupError


def _ok(data: dict[str, Any]) -> httpx.Response:
    return httpx.Response(
        status_code=200, json=data,
        request=httpx.Request("GET", "https://example/"),
    )


def _err(status: int) -> httpx.Response:
    return httpx.Response(
        status_code=status, json={"result": "error", "error-type": "bad"},
        request=httpx.Request("GET", "https://example/"),
    )


class TestRateInversion(unittest.TestCase):
    """The API returns base→quote; the client inverts to asset→base."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self._tmp.name) / "meta.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_usd_in_eur_is_inverted(self) -> None:
        """API returns base=EUR, USD=1.19 (1 EUR = 1.19 USD).

        Client should return 1/1.19 ≈ 0.840 (1 USD ≈ 0.840 EUR).
        """
        mock_get = mock.Mock(return_value=_ok({
            "result": "success",
            "conversion_rates": {"USD": 1.19, "EUR": 1.0},
        }))
        client = FxClient(api_key="k", db_path=self.db_path, http_get=mock_get)
        rate = client.get_historical_rate("EUR", "USD", date(2026, 4, 19))
        self.assertAlmostEqual(rate, 1.0 / 1.19, places=6)

    def test_same_currency_roundtrip(self) -> None:
        mock_get = mock.Mock(return_value=_ok({
            "result": "success",
            "conversion_rates": {"EUR": 1.0, "USD": 1.1},
        }))
        client = FxClient(api_key="k", db_path=self.db_path, http_get=mock_get)
        rate = client.get_historical_rate("EUR", "EUR", date(2026, 4, 19))
        self.assertAlmostEqual(rate, 1.0, places=6)


class TestHistoricalCache(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self._tmp.name) / "meta.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_second_call_hits_memory_cache(self) -> None:
        mock_get = mock.Mock(return_value=_ok({
            "result": "success",
            "conversion_rates": {"USD": 1.2},
        }))
        client = FxClient(api_key="k", db_path=self.db_path, http_get=mock_get)
        r1 = client.get_historical_rate("EUR", "USD", date(2026, 4, 19))
        r2 = client.get_historical_rate("EUR", "USD", date(2026, 4, 19))
        assert r1 == r2
        assert mock_get.call_count == 1

    def test_new_client_hits_sqlite_cache(self) -> None:
        mock_get = mock.Mock(return_value=_ok({
            "result": "success",
            "conversion_rates": {"USD": 1.2},
        }))
        c1 = FxClient(api_key="k", db_path=self.db_path, http_get=mock_get)
        c1.get_historical_rate("EUR", "USD", date(2026, 4, 19))

        # Fresh client — should hit SQLite, not HTTP.
        mock_get2 = mock.Mock(side_effect=AssertionError("should not be called"))
        c2 = FxClient(api_key="k", db_path=self.db_path, http_get=mock_get2)
        rate = c2.get_historical_rate("EUR", "USD", date(2026, 4, 19))
        self.assertAlmostEqual(rate, 1.0 / 1.2, places=6)

    def test_sibling_ccy_also_cached(self) -> None:
        """Fetching one ccy should cache the whole conversion_rates payload."""
        mock_get = mock.Mock(return_value=_ok({
            "result": "success",
            "conversion_rates": {"USD": 1.2, "CHF": 0.95},
        }))
        c1 = FxClient(api_key="k", db_path=self.db_path, http_get=mock_get)
        c1.get_historical_rate("EUR", "USD", date(2026, 4, 19))

        conn = store.init_fx_db(self.db_path)
        try:
            chf = store.lookup_rate(conn, "2026-04-19", "EUR", "CHF")
        finally:
            conn.close()
        assert chf is not None
        self.assertAlmostEqual(chf, 1.0 / 0.95, places=6)

    def test_sibling_ccy_hits_memory_not_db(self) -> None:
        """After one fetch, a sibling ccy lookup must hit memory — no DB open."""
        mock_get = mock.Mock(return_value=_ok({
            "result": "success",
            "conversion_rates": {"USD": 1.2, "CHF": 0.95, "GBP": 0.85},
        }))
        client = FxClient(api_key="k", db_path=self.db_path, http_get=mock_get)
        client.get_historical_rate("EUR", "USD", date(2026, 4, 19))

        # Break the DB path — if sibling lookups still touched the DB we'd
        # see an OperationalError. Memory hit = no DB access = still succeeds.
        client.db_path = "/nonexistent/does-not-exist/bad.db"
        chf = client.get_historical_rate("EUR", "CHF", date(2026, 4, 19))
        gbp = client.get_historical_rate("EUR", "GBP", date(2026, 4, 19))
        self.assertAlmostEqual(chf, 1.0 / 0.95, places=6)
        self.assertAlmostEqual(gbp, 1.0 / 0.85, places=6)
        assert mock_get.call_count == 1


class TestFailures(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self._tmp.name) / "meta.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_historical_without_key_raises(self) -> None:
        client = FxClient(api_key=None, db_path=self.db_path, http_get=mock.Mock())
        with self.assertRaises(FxLookupError):
            client.get_historical_rate("EUR", "USD", date(2026, 4, 19))

    def test_http_error_raises_fx_error(self) -> None:
        mock_get = mock.Mock(side_effect=httpx.ConnectError("nope"))
        client = FxClient(api_key="k", db_path=self.db_path, http_get=mock_get)
        with self.assertRaises(FxLookupError):
            client.get_historical_rate("EUR", "USD", date(2026, 4, 19))

    def test_non_200_raises(self) -> None:
        mock_get = mock.Mock(return_value=_err(503))
        client = FxClient(api_key="k", db_path=self.db_path, http_get=mock_get)
        with self.assertRaises(FxLookupError):
            client.get_historical_rate("EUR", "USD", date(2026, 4, 19))

    def test_api_error_result_raises(self) -> None:
        mock_get = mock.Mock(return_value=_ok({
            "result": "error", "error-type": "unsupported-code",
        }))
        client = FxClient(api_key="k", db_path=self.db_path, http_get=mock_get)
        with self.assertRaises(FxLookupError):
            client.get_historical_rate("EUR", "USD", date(2026, 4, 19))

    def test_missing_currency_raises(self) -> None:
        mock_get = mock.Mock(return_value=_ok({
            "result": "success",
            "conversion_rates": {"USD": 1.2},
        }))
        client = FxClient(api_key="k", db_path=self.db_path, http_get=mock_get)
        with self.assertRaises(FxLookupError):
            client.get_historical_rate("EUR", "XYZ", date(2026, 4, 19))


class TestLatest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self._tmp.name) / "meta.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_latest_uses_rates_key(self) -> None:
        """The keyless endpoint uses 'rates' instead of 'conversion_rates'."""
        mock_get = mock.Mock(return_value=_ok({
            "result": "success",
            "rates": {"USD": 1.19},
        }))
        client = FxClient(api_key=None, db_path=self.db_path, http_get=mock_get)
        rate = client.get_latest_rate("EUR", "USD")
        self.assertAlmostEqual(rate, 1.0 / 1.19, places=6)

    def test_latest_is_cached(self) -> None:
        mock_get = mock.Mock(return_value=_ok({
            "result": "success",
            "rates": {"USD": 1.19, "CHF": 0.95},
        }))
        client = FxClient(api_key=None, db_path=self.db_path, http_get=mock_get)
        client.get_latest_rate("EUR", "USD")
        client.get_latest_rate("EUR", "CHF")
        assert mock_get.call_count == 1
