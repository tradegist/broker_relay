"""Tests for the persistent FX rate store."""

import tempfile
import unittest
from pathlib import Path

from relay_core.fx import store


class TestFxStore(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "meta.db"
        self.conn = store.init_fx_db(self.path)

    def tearDown(self) -> None:
        self.conn.close()
        self._tmp.cleanup()

    def test_lookup_miss_is_none(self) -> None:
        assert store.lookup_rate(self.conn, "2026-04-19", "EUR", "USD") is None

    def test_store_and_lookup(self) -> None:
        store.store_rate(self.conn, "2026-04-19", "EUR", "USD", 0.835)
        assert store.lookup_rate(self.conn, "2026-04-19", "EUR", "USD") == 0.835

    def test_store_overwrite(self) -> None:
        store.store_rate(self.conn, "2026-04-19", "EUR", "USD", 0.830)
        store.store_rate(self.conn, "2026-04-19", "EUR", "USD", 0.835)
        assert store.lookup_rate(self.conn, "2026-04-19", "EUR", "USD") == 0.835

    def test_prune_removes_old(self) -> None:
        store.store_rate(self.conn, "2026-04-19", "EUR", "USD", 0.835)
        # Force stored_at to be ancient.
        self.conn.execute(
            "UPDATE fx_rates SET stored_at = datetime('now', '-1000 days')"
        )
        self.conn.commit()
        removed = store.prune(self.conn, retention_days=730)
        assert removed == 1
        assert store.lookup_rate(self.conn, "2026-04-19", "EUR", "USD") is None

    def test_prune_keeps_recent(self) -> None:
        store.store_rate(self.conn, "2026-04-19", "EUR", "USD", 0.835)
        removed = store.prune(self.conn, retention_days=730)
        assert removed == 0
        assert store.lookup_rate(self.conn, "2026-04-19", "EUR", "USD") == 0.835

    def test_store_rates_batch(self) -> None:
        store.store_rates(
            self.conn, "2026-04-19", "EUR",
            {"USD": 0.835, "CHF": 1.05, "GBP": 1.19},
        )
        assert store.lookup_rate(self.conn, "2026-04-19", "EUR", "USD") == 0.835
        assert store.lookup_rate(self.conn, "2026-04-19", "EUR", "CHF") == 1.05
        assert store.lookup_rate(self.conn, "2026-04-19", "EUR", "GBP") == 1.19

    def test_store_rates_empty_is_noop(self) -> None:
        store.store_rates(self.conn, "2026-04-19", "EUR", {})
        row = self.conn.execute("SELECT COUNT(*) FROM fx_rates").fetchone()
        assert row[0] == 0

    def test_store_rates_overwrites(self) -> None:
        store.store_rate(self.conn, "2026-04-19", "EUR", "USD", 0.830)
        store.store_rates(self.conn, "2026-04-19", "EUR", {"USD": 0.835})
        assert store.lookup_rate(self.conn, "2026-04-19", "EUR", "USD") == 0.835
