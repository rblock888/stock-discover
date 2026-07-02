"""Intraday 5-minute breakout watcher — alert-only, instrumented, killable.

Daily bars deliver a BREAKING trigger up to a day late. For a small hot list
(≤12 coiled/basing names sitting just under a real pivot, plus watchlist
names), one batched 5-minute download per cycle fires an alert the moment a
COMPLETED 5m bar closes through the pivot on real relative volume.

Honesty rails (pre-registered):
  • Alert-only forever until its own scorecard is positive — the nearest
    measured cousin (BOS-impulse breakout) has ~0R tradeable expectancy, so
    faster delivery of this trigger is UNPROVEN value; latency is simply the
    one lever that directly serves "catch it before it flies".
  • Every alert logs {price, pivot, rvol_prorated, coiled_score} so
    evaluation.intraday_scorecard() can measure 5/10/20d excess returns from
    the alert price. KILL: n>=30 alerts with 10d avg excess <= 0 → disable.
  • No trigger before 10:00 ET (linear volume proration misfires structurally
    in the U-shaped open). Close > pivot*1.002, not a wick. Dedupe 48h against
    both daily-scan 'breakout' and 'intraday_breakout'. Two consecutive batch
    errors → back off to 15-minute cycles for the rest of the session.
"""

import logging
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import db

logger = logging.getLogger("discovery")

ET = ZoneInfo("America/New_York")
HOTLIST_CAP = 12
PIVOT_BREAK = 1.002        # completed-bar close must clear pivot by 0.2%
RVOL_MIN = 1.5             # cumulative session volume vs prorated 20d average
EARLIEST_MINUTE = 10 * 60  # 10:00 ET

_state = {"hotlist": [], "backoff": False, "err_streak": 0, "session_day": None}


def build_hotlist(ranked_stocks: list, watchlist: list = None) -> list:
    """[{ticker, pivot_price, avg_vol20, coiled_score}] — rebuilt each scan.

    Coiled/basing names ≥90% of the pivot whose last DAILY CLOSE is still
    below it (pivot_prox uses hi50, which includes recent days — without the
    close<pivot guard the watcher fires instantly at open on stale pivots).
    Watchlist tickers with a valid pivot above the close get priority.
    """
    out, seen = [], set()

    def _add(s, priority):
        t = s.get("ticker")
        c = s.get("coiled") or {}
        q = s.get("quote") or {}
        pivot = c.get("pivot_price")
        close = q.get("price")
        if not t or t in seen or not pivot or not close:
            return
        if close >= pivot:            # already through — the daily scan owns it
            return
        out.append({"ticker": t, "pivot_price": float(pivot),
                    "avg_vol20": float(q.get("avg_volume") or 0),
                    "coiled_score": c.get("coiled_score", 0), "priority": priority})
        seen.add(t)

    wl = {w["ticker"] for w in (watchlist or [])}
    for s in ranked_stocks:
        if s.get("ticker") in wl:
            _add(s, 0)
    for s in ranked_stocks:
        c = s.get("coiled") or {}
        if c.get("state") in ("COILED", "BASING") and (c.get("pivot_prox") or 0) >= 0.90:
            _add(s, 1)

    out.sort(key=lambda x: (x["priority"], -(x["coiled_score"] or 0)))
    return out[:HOTLIST_CAP]


def set_hotlist(hotlist: list):
    _state["hotlist"] = hotlist or []
    today = datetime.now(ET).date().isoformat()
    if _state["session_day"] != today:      # new session resets the backoff
        _state.update({"session_day": today, "backoff": False, "err_streak": 0})


def in_window(now=None) -> bool:
    now = (now or datetime.now(ET)).astimezone(ET)
    if now.weekday() >= 5:
        return False
    minutes = now.hour * 60 + now.minute
    return 9 * 60 + 30 <= minutes < 16 * 60


def cycle_seconds() -> int:
    return 15 * 60 if _state["backoff"] else 5 * 60


def check_triggers(bars_by_ticker: dict = None, now=None) -> list:
    """One watcher pass. Returns fired-alert dicts (alert sending is the
    caller's job — this stays testable). bars_by_ticker injects data in tests;
    live it batch-downloads 5m bars for the hot list."""
    now = (now or datetime.now(ET)).astimezone(ET)
    hot = _state["hotlist"]
    if not hot or not in_window(now):
        return []
    if now.hour * 60 + now.minute < EARLIEST_MINUTE:
        return []

    if bars_by_ticker is None:
        try:
            import yfinance as yf
            tickers = [h["ticker"] for h in hot]
            raw = yf.download(tickers, period="1d", interval="5m",
                              group_by="ticker", threads=False, progress=False)
            bars_by_ticker = {}
            for t in tickers:
                try:
                    df = raw[t] if len(tickers) > 1 else raw
                    df = df.dropna(how="all")
                    if df is not None and not df.empty:
                        bars_by_ticker[t] = df
                except Exception:
                    continue
            _state["err_streak"] = 0
        except Exception as e:
            _state["err_streak"] += 1
            if _state["err_streak"] >= 2 and not _state["backoff"]:
                _state["backoff"] = True
                logger.warning(f"intraday watcher: 2 batch errors — 15-min backoff ({e})")
            return []

    fired = []
    minutes_open = max(1, (now.hour * 60 + now.minute) - (9 * 60 + 30))
    for h in hot:
        t = h["ticker"]
        df = bars_by_ticker.get(t)
        if df is None or len(df) < 2:
            continue
        done = df.iloc[:-1]        # last row is the in-progress bar — ignore it
        if done.empty:
            continue
        last_close = float(done["Close"].iloc[-1])
        if last_close <= h["pivot_price"] * PIVOT_BREAK:
            continue
        # relative volume: cumulative session volume vs the prorated 20d average
        cum_vol = float(done["Volume"].sum())
        prorated = h["avg_vol20"] * minutes_open / 390.0 if h["avg_vol20"] else 0.0
        rvol = cum_vol / prorated if prorated > 0 else 0.0
        if rvol < RVOL_MIN:
            continue
        if db.alert_already_sent(t, "breakout", within_hours=48):
            continue
        if db.alert_already_sent(t, "intraday_breakout", within_hours=48):
            continue
        fired.append({"ticker": t, "price": round(last_close, 4),
                      "pivot_price": h["pivot_price"],
                      "rvol_prorated": round(rvol, 2),
                      "coiled_score": h["coiled_score"]})
    return fired
