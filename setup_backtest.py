"""Historical setup backtest — does each setup type work TRADEABLY?

For every ticker we walk the daily history bar-by-bar, run the SAME detectors
(smad + book_signals) on the data available up to that bar, and when a setup
with a concrete trade plan fires we simulate it forward with REALISTIC fills:

  • 'now' plans fill at the NEXT bar's open (you can't buy yesterday's close);
    skipped if the open gapped through the stop or drifted >3% from the plan.
  • 'pullback' plans fill only if price actually returns to the limit within
    5 bars (the old simulator booked phantom instant fills at a limit BELOW the
    close — those trades never existed).
  • Exits are gap-aware: an open through the stop exits AT THE OPEN (real gap
    slippage), not at the stop price. Fill-bar target touches don't count
    (intrabar ordering is unknowable — conservative).
  • SLIPPAGE per side is charged on the tradeable leg.

Both legs are reported permanently: avg_r_exact (old idealized semantics, for
continuity) and avg_r_tradeable (what a real order plausibly got). Ranking,
grading, and the conviction demotion loop key off TRADEABLE numbers.

Caveat: next-open is the CONSERVATIVE bound — the live scanner runs every 30
minutes and can enter between the signal close and the next open. Real results
should land between the exact and tradeable legs.

Aggregation adds Wilson 95% CIs on win-rate and a lower-bound expectancy
(avg_r - 1.96*std/sqrt(n)); setups sort by that lower bound so a 5-of-6 sample
can't sort as "best" on a raw 83% win-rate again.
"""

import time
import numpy as np

import db
import price_history
import smad
import book_signals as bs

_cache = {"data": None, "as_of": 0.0, "running": False, "demotion_state": {}}
HORIZON = 20        # trading days to resolve a trade
STEP = 3            # sample cadence while scanning history (speed)
WARMUP = 200        # bars of lookback before the first candidate
MIN_BARS = 250      # skip tickers with less history than this
SLIPPAGE = 0.003    # per side — ASSUMED (microcap spreads); charged on tradeable leg
GAP_DRIFT_MAX = 0.03    # 'now' fills skipped if next open drifted >3% off plan entry
PULLBACK_WINDOW = 5     # bars a pullback limit stays working
STOP_GRID = [0.4, 0.75, 1.0, 1.25, 1.5]   # ATR stop-pad multipliers for the sweep

# conviction demotion-cap hysteresis (on shrunk tradeable expectancy)
AR_SHRINK_N = 30
CAP_BELOW = 0.03
RELEASE_ABOVE = 0.07
MIN_N_CAP = 50


def _classify(sm, bk):
    """Price-only setup label (mirrors conviction's technical priority)."""
    s = sm.get("state") if sm else None
    rbs = bk.get("rbs") or {}
    dbl = bk.get("double_bottom") or {}
    rhs = bk.get("reverse_hns") or {}
    if not bk.get("plan"):
        return None
    if s == "SPRING":
        return "Spring reclaim"
    if s == "DEMAND RETEST":
        return "Demand-zone retest"
    if s == "BOS IMPULSE":
        return "Breakout (structure)"
    if rhs.get("confirmed"):
        return "Reverse H&S"
    if dbl.get("confirmed"):
        return "Double bottom"
    if rbs.get("active"):
        return "Reclaimed-level (RBS)"
    return None


def _exact_r(h, l, c, i, entry, stop, target):
    """Old idealized semantics: fill AT the plan entry on the signal bar, first
    touch wins, tie → stop, timeout at close. Kept for continuity/audit."""
    risk = entry - stop
    if risk <= 0:
        return None
    end = min(i + HORIZON, len(c) - 1)
    for j in range(i + 1, end + 1):
        hit_stop = l[j] <= stop
        hit_tgt = h[j] >= target
        if hit_stop:
            return (stop - entry) / risk
        if hit_tgt:
            return (target - entry) / risk
    return (c[end] - entry) / risk


def _walk_exit(o, h, l, c, j0, end, fill, stop, target):
    """Gap-aware exit walk from the bar AFTER the fill bar. Returns
    (exit_price, exit_bar, reason). Gap checks FIRST (an open through the stop
    exits at the open — real slippage; an open through the target exits at the
    open), then intrabar touches with tie → stop; timeout at the last close."""
    for j in range(j0 + 1, end + 1):
        if o[j] <= stop:
            return float(o[j]), j, "stop"
        if o[j] >= target:
            return float(o[j]), j, "target"
        hit_stop = l[j] <= stop
        hit_tgt = h[j] >= target
        if hit_stop:
            return float(stop), j, "stop"
        if hit_tgt:
            return float(target), j, "target"
    return float(c[end]), end, "time"


def _simulate(o, h, l, c, i, entry, stop, target, entry_type="now", atr=None):
    """Simulate one plan with realistic fills. Returns a dict:
      r_exact          idealized leg (None if invalid plan)
      r                tradeable leg after slippage (None if no trade)
      outcome          'target' | 'stop' | 'time' | 'skipped_gap' | 'unfilled'
      fill, exit_price, bars_held
      mfe_r / mae_r    max favorable/adverse excursion through the exit bar (R)
      mfe_atr_full     no-stop counterfactual peak over the full horizon (ATR units)
      bars_to_peak
    """
    risk_plan = entry - stop
    if risk_plan <= 0:
        return None
    end = min(i + HORIZON, len(c) - 1)
    if i + 1 > end:
        return None
    out = {"r_exact": _exact_r(h, l, c, i, entry, stop, target)}

    # ── fill ──
    fill = None
    j0 = None
    if entry_type == "pullback":
        # a limit below the market: fills only if price actually comes back
        for j in range(i + 1, min(i + PULLBACK_WINDOW, end) + 1):
            if o[j] <= entry:
                fill, j0 = float(o[j]), j        # gapped through the limit → better fill
                break
            if l[j] <= entry:
                fill, j0 = float(entry), j       # touched the limit intrabar
                break
        if fill is None:
            out.update({"r": None, "outcome": "unfilled"})
            return out
    else:
        nxt = float(o[i + 1])
        if nxt <= stop or abs(nxt / entry - 1) > GAP_DRIFT_MAX:
            out.update({"r": None, "outcome": "skipped_gap"})
            return out
        fill, j0 = nxt, i + 1

    if fill <= stop:
        out.update({"r": None, "outcome": "skipped_gap"})
        return out

    # ── exit: on the fill bar only the stop can trigger (intrabar ordering is
    # unknowable — never award a same-bar target) ──
    if l[j0] <= stop and j0 > i:
        exit_price, exit_bar, reason = float(stop), j0, "stop"
        if o[j0] <= stop and entry_type == "pullback":
            exit_price = float(min(stop, o[j0]))
    elif j0 >= end:
        exit_price, exit_bar, reason = float(c[end]), end, "time"
    else:
        exit_price, exit_bar, reason = _walk_exit(o, h, l, c, j0, end, fill, stop, target)

    # slippage: pay up on entry, give up on exit
    fill_s = fill * (1 + SLIPPAGE)
    exit_s = exit_price * (1 - SLIPPAGE)
    risk = fill_s - stop
    if risk <= 0:
        out.update({"r": None, "outcome": "skipped_gap"})
        return out
    r = (exit_s - fill_s) / risk

    # excursions through the exit bar (what a manager could have seen/used)
    seg_h = h[j0:exit_bar + 1]
    seg_l = l[j0:exit_bar + 1]
    mfe_r = float((np.max(seg_h) - fill_s) / risk) if len(seg_h) else 0.0
    mae_r = float((np.min(seg_l) - fill_s) / risk) if len(seg_l) else 0.0
    # no-stop counterfactual peak in ATR units (avoids circularity with the stop)
    full_h = h[j0:end + 1]
    mfe_atr = float((np.max(full_h) - fill_s) / atr) if (atr and len(full_h)) else None
    peak_off = int(np.argmax(full_h)) if len(full_h) else 0

    out.update({
        "r": float(r), "outcome": reason, "fill": fill, "exit_price": exit_price,
        "bars_held": int(exit_bar - j0), "mfe_r": round(mfe_r, 2), "mae_r": round(mae_r, 2),
        "mfe_atr_full": round(mfe_atr, 2) if mfe_atr is not None else None,
        "bars_to_peak": peak_off,
    })
    return out


def _variant_r(o, h, l, c, j0, end, fill, stop, target, mode, d=5):
    """Management-variant R on the SAME entry: 'time' exits at c[j0+d] if no bar
    reached fill+0.5R by then; 'be' moves the stop to entry after the first bar
    that tags fill+1R. Same gap-first exit rules; slippage charged identically."""
    fill_s = fill * (1 + SLIPPAGE)
    risk = fill_s - stop
    if risk <= 0:
        return None
    live_stop = stop
    be_armed = False
    for j in range(j0 + 1, end + 1):
        if mode == "time" and j - j0 >= d:
            seg = h[j0:j + 1]
            if np.max(seg) < fill_s + 0.5 * risk:
                return ((c[j] * (1 - SLIPPAGE)) - fill_s) / risk
        if o[j] <= live_stop:
            return ((o[j] * (1 - SLIPPAGE)) - fill_s) / risk
        if o[j] >= target:
            return ((o[j] * (1 - SLIPPAGE)) - fill_s) / risk
        if l[j] <= live_stop:
            return ((live_stop * (1 - SLIPPAGE)) - fill_s) / risk
        if h[j] >= target:
            return ((target * (1 - SLIPPAGE)) - fill_s) / risk
        if mode == "be" and not be_armed and h[j] >= fill_s + risk:
            live_stop = fill_s   # break-even from the NEXT bar
            be_armed = True
    return ((c[end] * (1 - SLIPPAGE)) - fill_s) / risk


def _atr14(h, l, c, i):
    if i < 15:
        return None
    hh, ll, cc = h[i - 14:i + 1], l[i - 14:i + 1], c[i - 14:i + 1]
    prev = np.concatenate(([cc[0]], cc[:-1]))
    tr = np.maximum(hh - ll, np.maximum(np.abs(hh - prev), np.abs(ll - prev)))
    return float(np.mean(tr))


def _backtest_ticker(ticker, hist, stop_mults=None):
    """Walk one ticker's history. Returns a list of trade dicts (one per fired
    plan), each carrying setup, the simulated legs, and (when stop_mults is
    given) the per-arm tradeable R for the stop-width sweep."""
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
            bk = bs.compute(sl, zone=(sm or {}).get("demand_zone"), stop_mults=stop_mults)
        except Exception:
            i += STEP
            continue
        setup = _classify(sm, bk)
        plan = bk.get("plan")
        if setup and plan:
            atr = _atr14(h, l, c, i)
            sim = _simulate(o, h, l, c, i, plan["entry"], plan["stop"], plan["target"],
                            entry_type=plan.get("entry_type", "now"), atr=atr)
            if sim is not None:
                trade = {"setup": setup, "ticker": ticker, **sim}
                # sweep arms: same detector signal, per-arm plan
                if stop_mults and bk.get("plans_by_mult"):
                    arms = {}
                    for m, p in bk["plans_by_mult"].items():
                        if not p:
                            arms[m] = None
                            continue
                        s2 = _simulate(o, h, l, c, i, p["entry"], p["stop"], p["target"],
                                       entry_type=p.get("entry_type", "now"), atr=atr)
                        arms[m] = s2.get("r") if s2 else None
                    trade["arms"] = arms
                # management variants on the base tradeable entry ('now' fills
                # only — their fill bar is deterministic at i+1)
                if (sim.get("r") is not None and sim.get("fill")
                        and plan.get("entry_type", "now") == "now"):
                    end = min(i + HORIZON, n - 1)
                    for mode, dd in (("time", 3), ("time", 5), ("time", 8), ("be", 0)):
                        key = f"r_{mode}{dd if mode == 'time' else ''}"
                        trade[key] = _variant_r(o, h, l, c, i + 1, end,
                                                sim["fill"], plan["stop"], plan["target"],
                                                mode, d=dd)
                trades.append(trade)
                i += HORIZON      # no overlapping trades
                continue
        i += STEP
    return trades


def _wilson(p, n, z=1.96):
    """Wilson 95% interval for a proportion."""
    if n == 0:
        return None, None
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return round(float(center - half) * 100, 1), round(float(center + half) * 100, 1)


def _aggregate(all_trades):
    by = {}
    for t in all_trades:
        by.setdefault(t["setup"], []).append(t)
    prev_capped = dict(_cache.get("demotion_state") or {})
    new_capped = {}
    out = []
    for setup, ts in by.items():
        filled = [t for t in ts if t.get("r") is not None]
        exact = [t["r_exact"] for t in ts if t.get("r_exact") is not None]
        rs = np.array([t["r"] for t in filled], dtype=float)
        n = len(rs)
        n_attempt = len(ts)
        n_unfilled = sum(1 for t in ts if t.get("outcome") == "unfilled")
        n_skipped = sum(1 for t in ts if t.get("outcome") == "skipped_gap")
        win = float(np.mean(rs > 0)) if n else 0.0
        w_lo, w_hi = _wilson(win, n)
        avg_t = float(np.mean(rs)) if n else 0.0
        sd_t = float(np.std(rs)) if n > 1 else 0.0
        exp_lb = avg_t - 1.96 * sd_t / np.sqrt(n) if n > 1 else (avg_t if n else 0.0)
        ar_shrunk = avg_t * n / (n + AR_SHRINK_N)
        # demotion-cap hysteresis: cap when shrunk expectancy < CAP_BELOW,
        # release only above RELEASE_ABOVE — no flapping on boundary noise
        was = bool(prev_capped.get(setup))
        capped = was
        if n >= MIN_N_CAP:
            if not was and ar_shrunk < CAP_BELOW:
                capped = True
            elif was and ar_shrunk > RELEASE_ABOVE:
                capped = False
        new_capped[setup] = capped
        out.append({
            "setup": setup,
            "n": n, "n_attempted": n_attempt,
            "n_unfilled": n_unfilled, "n_skipped_gap": n_skipped,
            "fill_rate": round(n / n_attempt * 100, 1) if n_attempt else 0.0,
            "win_rate": round(win * 100, 1),
            "win_ci": [w_lo, w_hi],
            "avg_r": round(avg_t, 2),                # TRADEABLE — drives grading
            "avg_r_exact": round(float(np.mean(exact)), 2) if exact else None,
            "expectancy_lb": round(float(exp_lb), 2),
            "ar_shrunk": round(float(ar_shrunk), 2),
            "capped": capped,
            "hit_target_pct": round(float(np.mean([t["outcome"] == "target" for t in filled])) * 100, 1) if n else 0.0,
            "hit_stop_pct": round(float(np.mean([t["outcome"] == "stop" for t in filled])) * 100, 1) if n else 0.0,
            "avg_mfe_r": round(float(np.mean([t["mfe_r"] for t in filled])), 2) if n else None,
            "avg_mae_r": round(float(np.mean([t["mae_r"] for t in filled])), 2) if n else None,
        })
    # sort by LOWER-BOUND expectancy — a 5-of-6 sample can't sort as "best"
    out.sort(key=lambda x: (-x["expectancy_lb"], -x["n"]))
    _cache["demotion_state"] = new_capped

    filled_all = [t["r"] for t in all_trades if t.get("r") is not None]
    exact_all = [t["r_exact"] for t in all_trades if t.get("r_exact") is not None]
    summary = {
        "n": len(filled_all),
        "n_attempted": len(all_trades),
        "win_rate": round(float(np.mean(np.array(filled_all) > 0)) * 100, 1) if filled_all else 0.0,
        "avg_r": round(float(np.mean(filled_all)), 2) if filled_all else 0.0,
        "avg_r_exact": round(float(np.mean(exact_all)), 2) if exact_all else 0.0,
        "slippage_per_side": SLIPPAGE,
    }
    # pooled management-variant A/B on identical 'now' entries
    variants = {}
    for key in ("r_time3", "r_time5", "r_time8", "r_be"):
        vs = [t[key] for t in all_trades if t.get(key) is not None and t.get("r") is not None]
        base = [t["r"] for t in all_trades if t.get(key) is not None and t.get("r") is not None]
        if len(vs) >= 20:
            variants[key[2:]] = {
                "n": len(vs),
                "avg_r": round(float(np.mean(vs)), 2),
                "base_avg_r": round(float(np.mean(base)), 2),
                "delta": round(float(np.mean(vs)) - float(np.mean(base)), 2),
            }
    return {"by_setup": out, "summary": summary, "variants": variants}


def run(tickers, period="2y", stop_mults=None):
    """Backtest a list of tickers; returns aggregates keyed by setup type."""
    all_trades = []
    n_tickers = 0
    for t in tickers:
        hist = price_history.get_history(t, period=period)
        if hist is None or len(hist) < MIN_BARS:
            continue
        n_tickers += 1
        try:
            all_trades.extend(_backtest_ticker(t, hist, stop_mults=stop_mults))
        except Exception:
            continue
    res = _aggregate(all_trades)
    res["tickers_tested"] = n_tickers
    res["horizon_days"] = HORIZON
    if stop_mults:
        res["stop_sweep"] = _sweep_table(all_trades, stop_mults)
    return res


def _sweep_table(all_trades, stop_mults):
    """Per stop-multiplier arm: pooled + per-setup tradeable expectancy over the
    IDENTICAL signal set. Adoption rules (enforced by the reader, documented
    here): global-multiplier-first; a per-setup override only at n>=50 AND
    >=0.15R better than the global choice; adopt a new global only if it beats
    the 0.4 baseline by >= 1 SE; setups with n<30 stay frozen at 0.4."""
    table = {}
    for m in stop_mults:
        rs = [t["arms"].get(m) for t in all_trades if t.get("arms") and t["arms"].get(m) is not None]
        arr = np.array(rs, dtype=float)
        n = len(arr)
        if n == 0:
            table[str(m)] = None
            continue
        per_setup = {}
        for t in all_trades:
            if t.get("arms") and t["arms"].get(m) is not None:
                per_setup.setdefault(t["setup"], []).append(t["arms"][m])
        table[str(m)] = {
            "n": n,
            "avg_r": round(float(arr.mean()), 3),
            "se": round(float(arr.std() / np.sqrt(n)), 3) if n > 1 else None,
            "win_rate": round(float((arr > 0).mean()) * 100, 1),
            "by_setup": {s: {"n": len(v), "avg_r": round(float(np.mean(v)), 2)}
                         for s, v in per_setup.items()},
        }
    return table


def _universe():
    """Every distinct ticker ever snapshotted, union current ranked — capped at
    300, deterministic order (alphabetical) so successive runs are comparable."""
    try:
        with db.get_conn() as conn:
            rows = conn.execute("SELECT DISTINCT ticker FROM scan_snapshots").fetchall()
        snap = {r[0] for r in rows if r[0]}
    except Exception:
        snap = set()
    return sorted(snap)[:300]


def refresh(tickers):
    if _cache["running"]:
        return
    _cache["running"] = True
    try:
        uni = sorted(set(list(tickers)) | set(_universe()))[:300]
        data = run(uni)
        _cache["data"] = data
        _cache["as_of"] = time.time()
    finally:
        _cache["running"] = False


def get_cached():
    return {"data": _cache["data"], "as_of": _cache["as_of"]}
