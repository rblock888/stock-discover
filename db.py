"""SQLite database for persistence (scans, watchlist, alerts)."""

import sqlite3
import json
import os
from datetime import datetime
from contextlib import contextmanager

DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(__file__) or ".", "data.db"))


def init_db():
    """Create tables if they don't exist."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True) if os.path.dirname(DB_PATH) else None
    with get_conn() as conn:
        c = conn.cursor()
        # Snapshots of each scan's top picks for backtesting
        c.execute("""
            CREATE TABLE IF NOT EXISTS scan_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                scan_date TEXT NOT NULL,
                price REAL NOT NULL,
                composite_score REAL,
                ml_score REAL,
                early_score REAL,
                is_alert INTEGER DEFAULT 0,
                is_ai_pick INTEGER DEFAULT 0,
                segment TEXT,
                UNIQUE(ticker, scan_date)
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_ticker ON scan_snapshots(ticker)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_date ON scan_snapshots(scan_date)")

        # User watchlist
        c.execute("""
            CREATE TABLE IF NOT EXISTS watchlist (
                ticker TEXT PRIMARY KEY,
                added_date TEXT NOT NULL,
                entry_price REAL,
                target_price REAL,
                stop_loss REAL,
                notes TEXT,
                shares REAL DEFAULT 0
            )
        """)

        # Alert log to prevent duplicates
        c.execute("""
            CREATE TABLE IF NOT EXISTS alerts_sent (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                alert_type TEXT NOT NULL,
                sent_at TEXT NOT NULL,
                payload TEXT
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_alerts_ticker ON alerts_sent(ticker, alert_type)")

        # Daily market-regime snapshots (last write of the day wins)
        c.execute("""
            CREATE TABLE IF NOT EXISTS regime_snapshots (
                snap_date TEXT PRIMARY KEY,
                mood_score REAL,
                label TEXT,
                vix REAL,
                vix_pctile REAL,
                smallcap_score REAL,
                breadth_universe REAL,
                breadth_sectors REAL,
                created_at TEXT
            )
        """)

        conn.commit()


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


# ────────────────────────────────────────────
# Snapshots (for backtesting)
# ────────────────────────────────────────────

def save_snapshot(ranked_stocks: list, scan_date: str = None, ai_picks: list = None):
    """Save current ranked picks as a snapshot for later backtesting."""
    if not ranked_stocks:
        return
    scan_date = scan_date or datetime.now().isoformat()
    ai_set = set(ai_picks or [])

    with get_conn() as conn:
        c = conn.cursor()
        for stock in ranked_stocks[:40]:
            ticker = stock.get("ticker")
            if not ticker:
                continue
            price = stock.get("quote", {}).get("price", 0) if stock.get("quote") else 0
            try:
                c.execute("""
                    INSERT OR IGNORE INTO scan_snapshots
                    (ticker, scan_date, price, composite_score, ml_score, early_score, is_alert, is_ai_pick)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    ticker,
                    scan_date,
                    price,
                    stock.get("composite", 0),
                    stock.get("ml_score", 0),
                    stock.get("early_detection", {}).get("score", 0) if stock.get("early_detection") else 0,
                    1 if stock.get("multi_signal_alert") else 0,
                    1 if ticker in ai_set else 0,
                ))
            except Exception:
                continue
        conn.commit()


def get_snapshots(ticker: str = None, days_back: int = 90) -> list:
    """Get historical snapshots."""
    with get_conn() as conn:
        if ticker:
            rows = conn.execute(
                "SELECT * FROM scan_snapshots WHERE ticker = ? ORDER BY scan_date DESC LIMIT 100",
                (ticker,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM scan_snapshots ORDER BY scan_date DESC LIMIT 500"
            ).fetchall()
        return [dict(r) for r in rows]


def get_oldest_snapshot_per_ticker(min_days_old: int = 7) -> list:
    """For backtesting — get oldest snapshot per ticker that's at least N days old."""
    cutoff = datetime.now().isoformat()  # all snapshots before now
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT s.* FROM scan_snapshots s
            INNER JOIN (
                SELECT ticker, MIN(scan_date) as oldest
                FROM scan_snapshots
                GROUP BY ticker
            ) t ON s.ticker = t.ticker AND s.scan_date = t.oldest
            ORDER BY s.scan_date ASC
        """).fetchall()
        return [dict(r) for r in rows]


# ────────────────────────────────────────────
# Market regime snapshots
# ────────────────────────────────────────────

def save_regime_snapshot(snap: dict):
    """Upsert today's regime snapshot (last write of the day wins)."""
    snap_date = datetime.now().strftime("%Y-%m-%d")
    with get_conn() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO regime_snapshots
            (snap_date, mood_score, label, vix, vix_pctile, smallcap_score,
             breadth_universe, breadth_sectors, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            snap_date,
            snap.get("mood_score"),
            snap.get("label"),
            snap.get("vix"),
            snap.get("vix_pctile"),
            snap.get("smallcap_score"),
            snap.get("breadth_universe"),
            snap.get("breadth_sectors"),
            datetime.now().isoformat(),
        ))
        conn.commit()


def get_regime_strip(days: int = 10) -> list:
    """Last N daily regime snapshots, ascending by date."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM regime_snapshots ORDER BY snap_date DESC LIMIT ?",
            (days,)
        ).fetchall()
        return [dict(r) for r in reversed(rows)]


# ────────────────────────────────────────────
# Watchlist
# ────────────────────────────────────────────

def add_to_watchlist(ticker: str, entry_price: float = None, target_price: float = None,
                     stop_loss: float = None, notes: str = "", shares: float = 0) -> dict:
    with get_conn() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO watchlist
            (ticker, added_date, entry_price, target_price, stop_loss, notes, shares)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            ticker.upper(),
            datetime.now().isoformat(),
            entry_price,
            target_price,
            stop_loss,
            notes,
            shares,
        ))
        conn.commit()
    return get_watchlist_item(ticker)


def remove_from_watchlist(ticker: str) -> bool:
    with get_conn() as conn:
        cursor = conn.execute("DELETE FROM watchlist WHERE ticker = ?", (ticker.upper(),))
        conn.commit()
        return cursor.rowcount > 0


def get_watchlist() -> list:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM watchlist ORDER BY added_date DESC").fetchall()
        return [dict(r) for r in rows]


def get_watchlist_item(ticker: str) -> dict:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM watchlist WHERE ticker = ?", (ticker.upper(),)).fetchone()
        return dict(row) if row else None


def update_watchlist_item(ticker: str, **fields) -> dict:
    if not fields:
        return get_watchlist_item(ticker)
    cols = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [ticker.upper()]
    with get_conn() as conn:
        conn.execute(f"UPDATE watchlist SET {cols} WHERE ticker = ?", values)
        conn.commit()
    return get_watchlist_item(ticker)


# ────────────────────────────────────────────
# Alerts
# ────────────────────────────────────────────

def alert_already_sent(ticker: str, alert_type: str, within_hours: int = 24) -> bool:
    """Check if an alert was already sent for this ticker recently."""
    cutoff = datetime.now().timestamp() - (within_hours * 3600)
    cutoff_iso = datetime.fromtimestamp(cutoff).isoformat()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM alerts_sent WHERE ticker = ? AND alert_type = ? AND sent_at > ?",
            (ticker, alert_type, cutoff_iso)
        ).fetchone()
        return row is not None


def log_alert(ticker: str, alert_type: str, payload: dict = None):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO alerts_sent (ticker, alert_type, sent_at, payload) VALUES (?, ?, ?, ?)",
            (ticker, alert_type, datetime.now().isoformat(), json.dumps(payload or {}))
        )
        conn.commit()


def get_recent_alerts(limit: int = 50) -> list:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM alerts_sent ORDER BY sent_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
