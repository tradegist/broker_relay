"""Persistent cache of historical FX rates, backed by SQLite.

Historical rates never change, so caching them across restarts saves both
API budget and latency. A single table ``fx_rates`` sits alongside the
existing ``metadata`` table in the meta database. Each connection is
thread-local (never shared across threads) per the project's SQLite rules.
"""

import logging
import sqlite3
from pathlib import Path

log = logging.getLogger(__name__)

# Default path — same meta volume the poller watermark already uses.
DEFAULT_FX_DB_PATH = "/data/meta/relay.db"


def init_fx_db(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Open the FX-rate SQLite DB and ensure the table exists."""
    path = Path(db_path) if db_path is not None else Path(DEFAULT_FX_DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False, timeout=5.0)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS fx_rates ("
        "  date TEXT NOT NULL,"
        "  base TEXT NOT NULL,"
        "  ccy TEXT NOT NULL,"
        "  rate REAL NOT NULL,"
        "  stored_at TEXT DEFAULT (datetime('now')),"
        "  PRIMARY KEY (date, base, ccy)"
        ")"
    )
    conn.commit()
    return conn


def lookup_rate(
    conn: sqlite3.Connection, date: str, base: str, ccy: str,
) -> float | None:
    """Return the cached historical rate for (date, base, ccy), or None."""
    row = conn.execute(
        "SELECT rate FROM fx_rates WHERE date = ? AND base = ? AND ccy = ?",
        (date, base, ccy),
    ).fetchone()
    return float(row[0]) if row else None


def store_rate(
    conn: sqlite3.Connection, date: str, base: str, ccy: str, rate: float,
) -> None:
    """Persist (or overwrite) a single historical rate."""
    conn.execute(
        "INSERT OR REPLACE INTO fx_rates (date, base, ccy, rate) VALUES (?, ?, ?, ?)",
        (date, base, ccy, rate),
    )
    conn.commit()


def store_rates(
    conn: sqlite3.Connection, date: str, base: str, rates: dict[str, float],
) -> None:
    """Persist (or overwrite) multiple rates for (date, base) in one transaction.

    A single ``executemany`` + one ``commit`` — much cheaper than calling
    :func:`store_rate` in a loop when the upstream API returns rates for
    dozens of currencies at once.
    """
    if not rates:
        return
    conn.executemany(
        "INSERT OR REPLACE INTO fx_rates (date, base, ccy, rate) VALUES (?, ?, ?, ?)",
        [(date, base, ccy, rate) for ccy, rate in rates.items()],
    )
    conn.commit()


def prune(conn: sqlite3.Connection, retention_days: int) -> int:
    """Delete cached rates older than *retention_days*. Returns rows removed."""
    cur = conn.execute(
        "DELETE FROM fx_rates WHERE stored_at < datetime('now', ?)",
        (f"-{retention_days} days",),
    )
    conn.commit()
    removed = cur.rowcount
    if removed:
        log.info("Pruned %d FX rate entries older than %d days", removed, retention_days)
    return removed
