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
        # Migration: regime-tilt + per-bucket-score columns (ignore if present).
        # bucket_scores (JSON) starts the data clock for evidence-based weighting —
        # the per-bucket scores were previously dropped, making it impossible to
        # measure which buckets actually predict.
        existing = {r[1] for r in c.execute("PRAGMA table_info(scan_snapshots)").fetchall()}
        for col, decl in (("tilt_factor", "REAL"), ("regime_label", "TEXT"),
                          ("rank_score", "REAL"), ("bucket_scores", "TEXT"),
                          ("coiled_score", "REAL"), ("smad_score", "REAL"), ("smad_state", "TEXT"),
                          ("setup_grade", "TEXT"), ("setup_score", "REAL"), ("setup_type", "TEXT"),
                          ("setup_plan", "TEXT")):
            if col not in existing:
                c.execute(f"ALTER TABLE scan_snapshots ADD COLUMN {col} {decl}")
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

        # Realized forward returns per snapshot (the closed loop for calibration)
        c.execute("""
            CREATE TABLE IF NOT EXISTS snapshot_returns (
                ticker TEXT NOT NULL,
                snap_day TEXT NOT NULL,
                horizon INTEGER NOT NULL,
                entry_price REAL,
                exit_price REAL,
                fwd_return REAL,
                spy_return REAL,
                excess_return REAL,
                composite_score REAL,
                ml_score REAL,
                computed_at TEXT,
                UNIQUE(ticker, snap_day, horizon)
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_sret_horizon ON snapshot_returns(horizon)")

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

        # Paper-trade ledger v1: every grade-A/B plan gets a simulated position
        # at REAL 30-min-granularity quotes — the only measurement of "the plan
        # makes money" that includes discovery bias, vetoes, and entry
        # feasibility. Rows are never edited by management-variant experiments.
        c.execute("""
            CREATE TABLE IF NOT EXISTS paper_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                setup_type TEXT,
                grade TEXT,
                regime_at_open TEXT,
                plan_entry REAL,
                fill_price REAL,
                stop REAL,
                target REAL,
                shares INTEGER,
                opened_at TEXT,
                status TEXT NOT NULL,      -- pending | open | closed | missed
                exit_price REAL,
                exit_reason TEXT,          -- stop | target | time
                closed_at TEXT,
                r_realised REAL,
                mfe_r REAL,
                mae_r REAL,
                first_seen TEXT,
                last_quote REAL,
                notes TEXT
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_paper_ticker ON paper_trades(ticker)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_paper_status ON paper_trades(status)")

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

def save_snapshot(ranked_stocks: list, scan_date: str = None, ai_picks: list = None,
                  regime_label: str = None):
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
            tilt = (stock.get("tilt") or {}).get("factor")
            # Per-bucket raw scores (JSON) — the inputs to evidence-based weighting.
            # Enriched (2026-07-02) with catalyst sub-component raws (cat_*) and the
            # news-attention count, so evaluation can measure WHICH sub-signal
            # carries catalyst's IC and whether attention peaks mark tops.
            bd = stock.get("breakdown") or {}
            bucket_scores = None
            if bd:
                bs = {b: (bd.get(b) or {}).get("raw") for b in
                      ("fundamentals", "momentum", "catalyst", "insider", "sentiment")}
                cm = (bd.get("catalyst") or {}).get("metrics") or {}
                bs["cat_earnings_days"] = cm.get("earnings_days")
                bs["cat_target_upside"] = cm.get("target_upside")
                bs["cat_rec_score"] = cm.get("rec_score")
                bs["cat_n_analysts"] = cm.get("n_analysts")
                bs["cat_src"] = cm.get("src")
                sent_comp = (bd.get("sentiment") or {}).get("components") or {}
                bs["attention"] = sent_comp.get("attention")
                bucket_scores = json.dumps(bs)
            coiled = (stock.get("coiled") or {}).get("coiled_score")
            smad_obj = stock.get("smad") or {}
            verdict = stock.get("setup") or {}   # conviction.assess() output
            plan = verdict.get("plan")
            setup_plan = None
            if plan:
                try:
                    setup_plan = json.dumps({k: plan.get(k) for k in
                                             ("entry", "stop", "target", "rr", "risk_pct", "entry_type")})[:500]
                except Exception:
                    setup_plan = None
            try:
                c.execute("""
                    INSERT OR IGNORE INTO scan_snapshots
                    (ticker, scan_date, price, composite_score, ml_score, early_score,
                     is_alert, is_ai_pick, tilt_factor, regime_label, rank_score, bucket_scores,
                     coiled_score, smad_score, smad_state, setup_grade, setup_score, setup_type,
                     setup_plan)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    ticker,
                    scan_date,
                    price,
                    stock.get("composite", 0),
                    stock.get("ml_score", 0),
                    stock.get("early_detection", {}).get("score", 0) if stock.get("early_detection") else 0,
                    1 if stock.get("multi_signal_alert") else 0,
                    1 if ticker in ai_set else 0,
                    tilt,
                    regime_label,
                    stock.get("rank_score"),
                    bucket_scores,
                    coiled,
                    smad_obj.get("smad_score"),
                    smad_obj.get("state"),
                    verdict.get("grade"),
                    verdict.get("score"),
                    verdict.get("setup"),
                    setup_plan,
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


def get_all_snapshots() -> list:
    """Every snapshot ever recorded (no LIMIT) — for forward-return evaluation."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT ticker, scan_date, price, composite_score, ml_score, early_score, "
            "is_alert, is_ai_pick FROM scan_snapshots ORDER BY scan_date ASC"
        ).fetchall()
        return [dict(r) for r in rows]


def get_snapshot_features() -> list:
    """Per-snapshot scoring features for evidence/A-B/grade analysis (joins to returns)."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT ticker, scan_date, composite_score, tilt_factor, rank_score, bucket_scores, "
            "coiled_score, setup_grade, setup_score, setup_type, setup_plan, regime_label "
            "FROM scan_snapshots ORDER BY scan_date ASC"
        ).fetchall()
        return [dict(r) for r in rows]


def save_snapshot_returns(rows: list):
    """Bulk-upsert realized forward returns keyed by (ticker, snap_day, horizon)."""
    if not rows:
        return
    with get_conn() as conn:
        conn.executemany("""
            INSERT OR REPLACE INTO snapshot_returns
            (ticker, snap_day, horizon, entry_price, exit_price, fwd_return,
             spy_return, excess_return, composite_score, ml_score, computed_at)
            VALUES (:ticker, :snap_day, :horizon, :entry_price, :exit_price, :fwd_return,
                    :spy_return, :excess_return, :composite_score, :ml_score, :computed_at)
        """, rows)
        conn.commit()


def get_snapshot_returns(horizon: int = None) -> list:
    """Resolved forward returns, optionally filtered to one horizon."""
    with get_conn() as conn:
        if horizon is not None:
            rows = conn.execute(
                "SELECT * FROM snapshot_returns WHERE horizon = ? ORDER BY snap_day ASC",
                (horizon,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM snapshot_returns ORDER BY snap_day ASC").fetchall()
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


# ────────────────────────────────────────────
# Paper-trade ledger

_PAPER_COLS = {"ticker", "setup_type", "grade", "regime_at_open", "plan_entry",
               "fill_price", "stop", "target", "shares", "opened_at", "status",
               "exit_price", "exit_reason", "closed_at", "r_realised", "mfe_r",
               "mae_r", "first_seen", "last_quote", "notes"}


def paper_insert(row: dict) -> int:
    cols = [k for k in row if k in _PAPER_COLS]
    with get_conn() as conn:
        cur = conn.execute(
            f"INSERT INTO paper_trades ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
            [row[k] for k in cols],
        )
        conn.commit()
        return int(cur.lastrowid)


def paper_update(trade_id: int, **fields):
    sets = {k: v for k, v in fields.items() if k in _PAPER_COLS}
    if not sets:
        return
    with get_conn() as conn:
        conn.execute(
            f"UPDATE paper_trades SET {', '.join(f'{k}=?' for k in sets)} WHERE id=?",
            [*sets.values(), trade_id],
        )
        conn.commit()


def get_paper_trades(status: str = None, ticker: str = None) -> list:
    q = "SELECT * FROM paper_trades"
    conds, args = [], []
    if status:
        conds.append("status=?"); args.append(status)
    if ticker:
        conds.append("ticker=?"); args.append(ticker)
    if conds:
        q += " WHERE " + " AND ".join(conds)
    q += " ORDER BY id ASC"
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(q, args).fetchall()]
