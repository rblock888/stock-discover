"""Historical setup backtest — does each setup type actually work?

For every ticker we walk the daily history bar-by-bar, run the SAME detectors
(smad + book_signals) on the data available up to that bar, and when a setup with
a concrete trade plan fires we simulate it forward: did price hit the target
before the stop within the horizon? No look-ahead — entry is the signal bar's
close, outcomes use only later bars.

Aggregated per setup type: sample size, win-rate (target-before-stop), average R
realised, and expectancy. This turns "looks like a good setup" into a measured
number, today, without waiting for forward data to accrue.
"""

import time
import numpy as np

import price_history
import smad
import book_signals as bs

_cache = {"data": None, "as_of": 0.0, "running": False}
HORIZON = 20      # trading days to resolve a trade
STEP = 3          # sample cadence while scanning history (speed)
WARMUP = 200      # bars of lookback before the first candidate
MIN_BARS = WARMUP + HORIZON + 10


def _classify(sm, bk):
    """Price-only setup label + plan (mirrors conviction's technical priority)."""
    s = sm.get("state") if sm else None
    cstate = None  # coiled not recomputed here; smad/book carry the actionable setups
    rbs = bk.get("rbs") or {}
    dbl = bk.get("double_bottom") or {}
    rhs = bk.get("reverse_hns") or {}
    plan = bk.get("plan")
    if not plan:
        return None, None
    if s == "SPRING":
        return "Spring reclaim", plan
    if s == "DEMAND RETEST":
        return "Demand-zone retest", plan
    if s == "BOS IMPULSE":
        return "Breakout (structure)", plan
    if rhs.get("confirmed"):
        return "Reverse H&S", plan
    if dbl.get("confirmed"):
        return "Double bottom", plan
    if rbs.get("active"):
        return "Reclaimed-level (RBS)", plan
    return None, None


def _simulate(h, l, c, i, entry, stop, target):
    """Walk bars i+1..i+HORIZON; first touch wins. Stop assumed first on an
    inside-bar tie (conservative). Returns realised R."""
    risk = entry - stop
    if risk <= 0:
        return None
    end = min(i + HORIZON, len(c) - 1)
    for j in range(i + 1, end + 1):
        hit_stop = l[j] <= stop
        hit_tgt = h[j] >= target
        if hit_stop and hit_tgt:
            return (stop - entry) / risk          # tie → stop
        if hit_stop:
            return (stop - entry) / risk          # = -1R
        if hit_tgt:
            return (target - entry) / risk        # = +plan.rr
    return (c[end] - entry) / risk                # timeout: mark to close


def _backtest_ticker(ticker, hist):
    o = hist["Open"].to_numpy(float)
    h = hist["High"].to_numpy(float)
    l = hist["Low"].to_numpy(float)
    c = hist["Close"].to_numpy(float)
    n = len(c)
    trades = []
    i = WARMUP
    while i < n - HORIZON:
        sl = hist.iloc[:i + 1]
        try:
            sm = smad.compute(ticker, sl)
            bk = bs.compute(sl, zone=(sm or {}).get("demand_zone"))
        except Exception:
            i += STEP
            continue
        setup, plan = _classify(sm, bk)
        if setup and plan:
            r = _simulate(h, l, c, i, plan["entry"], plan["stop"], plan["target"])
            if r is not None:
                trades.append((setup, float(r)))
                i += HORIZON      # no overlapping trades
                continue
        i += STEP
    return trades


def _aggregate(all_trades):
    by = {}
    for setup, r in all_trades:
        by.setdefault(setup, []).append(r)
    out = []
    for setup, rs in by.items():
        arr = np.array(rs)
        out.append({
            "setup": setup,
            "n": len(rs),
            "win_rate": round(float(np.mean(arr > 0)) * 100, 1),
            "avg_r": round(float(np.mean(arr)), 2),
            "expectancy": round(float(np.mean(arr)), 2),
            "hit_target_pct": round(float(np.mean(arr >= 0.99)) * 100, 1),
            "hit_stop_pct": round(float(np.mean(arr <= -0.99)) * 100, 1),
        })
    out.sort(key=lambda x: (-x["expectancy"], -x["n"]))
    overall = [r for _, r in all_trades]
    summary = {
        "n": len(overall),
        "win_rate": round(float(np.mean(np.array(overall) > 0)) * 100, 1) if overall else 0.0,
        "avg_r": round(float(np.mean(overall)), 2) if overall else 0.0,
    }
    return {"by_setup": out, "summary": summary}


def run(tickers, period="2y"):
    """Backtest a list of tickers; returns aggregates keyed by setup type."""
    all_trades = []
    n_tickers = 0
    for t in tickers:
        hist = price_history.get_history(t, period=period)
        if hist is None or len(hist) < MIN_BARS:
            continue
        n_tickers += 1
        try:
            all_trades.extend(_backtest_ticker(t, hist))
        except Exception:
            continue
    res = _aggregate(all_trades)
    res["tickers_tested"] = n_tickers
    res["horizon_days"] = HORIZON
    return res


def refresh(tickers):
    if _cache["running"]:
        return
    _cache["running"] = True
    try:
        data = run(list(tickers)[:60])
        _cache["data"] = data
        _cache["as_of"] = time.time()
    finally:
        _cache["running"] = False


def get_cached():
    return {"data": _cache["data"], "as_of": _cache["as_of"]}
