"""Tests for FX config getters."""

import os
import unittest
from unittest import mock

from relay_core.fx.config import (
    get_fx_api_key,
    get_fx_base_currency,
    get_fx_cache_retention_days,
    get_fx_enabled,
)


class TestGetFxEnabled(unittest.TestCase):
    def test_unset_is_false(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            assert get_fx_enabled() is False

    def test_true_values(self) -> None:
        for val in ("true", "1", "yes", "TRUE", "Yes"):
            with mock.patch.dict(os.environ, {"FX_RATES_ENABLED": val}):
                assert get_fx_enabled() is True, val

    def test_false_values(self) -> None:
        for val in ("false", "0", "no", "FALSE"):
            with mock.patch.dict(os.environ, {"FX_RATES_ENABLED": val}):
                assert get_fx_enabled() is False, val

    def test_invalid_value_raises(self) -> None:
        with mock.patch.dict(os.environ, {"FX_RATES_ENABLED": "maybe"}), self.assertRaises(SystemExit):
            get_fx_enabled()


class TestGetFxBaseCurrency(unittest.TestCase):
    def test_missing_raises(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True), self.assertRaises(SystemExit):
            get_fx_base_currency()

    def test_valid_iso_4217(self) -> None:
        with mock.patch.dict(os.environ, {"FX_RATES_BASE_CURRENCY": "EUR"}):
            assert get_fx_base_currency() == "EUR"

    def test_lowercase_is_normalised(self) -> None:
        with mock.patch.dict(os.environ, {"FX_RATES_BASE_CURRENCY": "usd"}):
            assert get_fx_base_currency() == "USD"

    def test_invalid_length_raises(self) -> None:
        with mock.patch.dict(os.environ, {"FX_RATES_BASE_CURRENCY": "EURO"}), self.assertRaises(SystemExit):
            get_fx_base_currency()

    def test_non_alpha_raises(self) -> None:
        with mock.patch.dict(os.environ, {"FX_RATES_BASE_CURRENCY": "E1R"}), self.assertRaises(SystemExit):
            get_fx_base_currency()


class TestGetFxApiKey(unittest.TestCase):
    def test_missing_is_none(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            assert get_fx_api_key() is None

    def test_whitespace_is_none(self) -> None:
        with mock.patch.dict(os.environ, {"FX_RATE_API_KEY": "   "}):
            assert get_fx_api_key() is None

    def test_present(self) -> None:
        with mock.patch.dict(os.environ, {"FX_RATE_API_KEY": "abc"}):
            assert get_fx_api_key() == "abc"


class TestGetFxCacheRetentionDays(unittest.TestCase):
    def test_default(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            assert get_fx_cache_retention_days() == 730

    def test_custom(self) -> None:
        with mock.patch.dict(os.environ, {"FX_CACHE_RETENTION_DAYS": "30"}):
            assert get_fx_cache_retention_days() == 30

    def test_zero_raises(self) -> None:
        with mock.patch.dict(os.environ, {"FX_CACHE_RETENTION_DAYS": "0"}), self.assertRaises(SystemExit):
            get_fx_cache_retention_days()

    def test_negative_raises(self) -> None:
        with mock.patch.dict(os.environ, {"FX_CACHE_RETENTION_DAYS": "-1"}), self.assertRaises(SystemExit):
            get_fx_cache_retention_days()

    def test_non_integer_raises(self) -> None:
        with mock.patch.dict(os.environ, {"FX_CACHE_RETENTION_DAYS": "many"}), self.assertRaises(SystemExit):
            get_fx_cache_retention_days()
