"""Forward-return evaluation + score calibration — the closed loop.

Turns accumulated scan_snapshots into MEASURED outcomes so the heuristic
scores can finally be checked against reality:

  • realized N-day forward returns (SPY-relative) for every past pick,
    computed from real historical closes — works retroactively, no waiting
  • per-signal Information Coefficient (does the score rank winners?)
  • score-decile scorecard (hit-rate, avg return, top-minus-bottom spread)
  • isotonic calibration map (raw score → measured P(win)) — replaces the
    fabricated probabilities in ml_breakout

Pure numpy (no scipy/sklearn). yfinance accessed only through price_history.
"""

import json
import logging
import math
from datetime import datetime

import numpy as np

import db
import config
import price_history

logger = logging.getLogger("discovery")

HORIZONS = [5, 10, 20, 60]      # trading days
WIN_THRESHOLD = 0.10            # legacy 20d bar (kept for back-compat in tests)
# A "+10% in 5 days" bar is a lottery ticket, not a win-rate — scale the bar
# with horizon: 0.10 * sqrt(h/20), rounded to the nearest percent.
WIN_THRESHOLDS = {5: 0.05, 10: 0.07, 20: 0.10, 60: 0.17}


def win_threshold(horizon: int) -> float:
    return WIN_THRESHOLDS.get(horizon, round(0.10 * math.sqrt(horizon / 20.0), 2))
SIGNALS = ["composite_score", "ml_score", "early_score"]
BUCKETS = ["fundamentals", "momentum", "catalyst", "insider", "sentiment"]

# Minimum sample before a measured result is trusted (vs "accruing")
MIN_N_EVIDENCE = 120
MIN_N_TILT = 80
MIN_N_GRADE = 120                # 5-way categorical split, same power bar as evidence_weights
MIN_N_GRADE_PER_BUCKET = 10      # below this a grade's own row is flagged low_n, not hidden

# AVOID worst -> A best. "—" (no setup detected) is excluded from this ladder —
# it's a different population ("nothing to grade"), not a neutral midpoint.
GRADE_ORDER = ["AVOID", "WATCH", "C", "B", "A"]
GRADE_ORDINAL = {"AVOID": 0, "WATCH": 1, "C": 2, "B": 3, "A": 4}

_cache = {"scorecard": None, "calibration": {}, "last_run": None, "coverage": None}


# ── Daily-grain reduction ─────────────────────────────────────────────────────

def _daily_grain(snapshots: list) -> dict:
    """Collapse intraday snapshots → one row per (ticker, calendar day).

    Keeps the LAST snapshot of each day (closest to the close the scores saw).
    Returns {ticker: {day: row}}.
    """
    out: dict = {}
    for s in snapshots:
        ticker = s.get("ticker")
        sd = s.get("scan_date")
        if not ticker or not sd:
            continue
        day = sd[:10]
        out.setdefault(ticker, {})[day] = s  # later scan_date overwrites earlier
    return out


# ── Forward-return computation ────────────────────────────────────────────────

def _close_series(hist):
    """(numpy dates as YYYY-MM-DD strings, numpy closes) ascending, NaN-free."""
    if hist is None or len(hist) == 0:
        return None, None
    closes = hist["Close"].to_numpy(dtype=float)
    days = np.array([d.strftime("%Y-%m-%d") for d in hist.index])
    mask = ~np.isnan(closes)
    return days[mask], closes[mask]


def _entry_exit(days, closes, entry_day: str, horizon: int):
    """Return (entry_close, exit_close) using the last trading day ≤ entry_day
    as entry and `horizon` trading days later as exit. None if out of range."""
    idx = int(np.searchsorted(days, entry_day, side="right") - 1)
    if idx < 0:
        return None, None
    exit_idx = idx + horizon
    if exit_idx >= len(closes):
        return None, None  # not enough forward data yet (pending)
    e = float(closes[idx])
    x = float(closes[exit_idx])
    if e <= 0 or not math.isfinite(e) or not math.isfinite(x):
        return None, None
    return e, x


def compute_forward_returns(horizons=None, batch=60) -> dict:
    """Backfill snapshot_returns for every resolvable (ticker, day, horizon).

    Returns a coverage report. Idempotent — INSERT OR REPLACE.
    """
    horizons = horizons or HORIZONS
    grain = _daily_grain(db.get_all_snapshots())
    tickers = sorted(grain.keys())

    # SPY benchmark (one fetch, long window covers all snapshot dates + 60d fwd)
    spy_days, spy_closes = _close_series(price_history.get_history("SPY", period="2y"))

    rows = []
    resolved = pending = unresolved = 0
    now = datetime.now().isoformat()

    # Batch-fetch histories to limit network round-trips
    for i in range(0, len(tickers), batch):
        chunk = tickers[i:i + batch]
        hists = price_history.get_histories(chunk, period="2y")
        for ticker in chunk:
            days, closes = _close_series(hists.get(ticker))
            if days is None or len(days) < 5:
                unresolved += len(grain[ticker])
                continue
            for day, snap in grain[ticker].items():
                for h in horizons:
                    e, x = _entry_exit(days, closes, day, h)
                    if e is None:
                        pending += 1
                        continue
                    fwd = x / e - 1.0
                    spy_ret = None
                    excess = None
                    if spy_days is not None:
                        se, sx = _entry_exit(spy_days, spy_closes, day, h)
                        if se is not None:
                            spy_ret = sx / se - 1.0
                            excess = fwd - spy_ret
                    rows.append({
                        "ticker": ticker, "snap_day": day, "horizon": h,
                        "entry_price": round(e, 4), "exit_price": round(x, 4),
                        "fwd_return": round(fwd, 5),
                        "spy_return": round(spy_ret, 5) if spy_ret is not None else None,
                        "excess_return": round(excess, 5) if excess is not None else None,
                        "composite_score": snap.get("composite_score"),
                        "ml_score": snap.get("ml_score"),
                        "computed_at": now,
                    })
                    resolved += 1

    db.save_snapshot_returns(rows)
    coverage = {
        "tickers": len(tickers),
        "resolved": resolved,
        "pending": pending,        # too recent for that horizon
        "unresolved": unresolved,  # no price history (delisted/renamed/bad symbol)
        "horizons": horizons,
    }
    _cache["coverage"] = coverage
    _cache["last_run"] = now
    logger.info(f"Forward returns: {resolved} resolved, {pending} pending, {unresolved} unresolved")
    return coverage


# ── Statistics (numpy-only) ───────────────────────────────────────────────────

def _rankdata(a: np.ndarray) -> np.ndarray:
    """Average ranks (ties shared), like scipy.stats.rankdata."""
    order = np.argsort(a, kind="mergesort")
    ranks = np.empty(len(a), dtype=float)
    ranks[order] = np.arange(1, len(a) + 1)
    # average tied ranks
    _, inv, counts = np.unique(a, return_inverse=True, return_counts=True)
    csum = np.cumsum(counts)
    start = csum - counts
    avg = (start + csum + 1) / 2.0
    return avg[inv]


def _spearman(x: np.ndarray, y: np.ndarray) -> float:
    if len(x) < 5:
        return 0.0
    rx, ry = _rankdata(x), _rankdata(y)
    rx -= rx.mean(); ry -= ry.mean()
    denom = math.sqrt(float((rx ** 2).sum()) * float((ry ** 2).sum()))
    return float((rx * ry).sum() / denom) if denom > 0 else 0.0


def _isotonic(x: np.ndarray, y: np.ndarray) -> tuple:
    """Pool-adjacent-violators isotonic regression. Returns (x_sorted, y_fit)."""
    order = np.argsort(x, kind="mergesort")
    xs, ys = x[order], y[order].astype(float)
    w = np.ones(len(ys))
    # PAV
    i = 0
    yv = ys.copy()
    blocks = [[ys[k], 1.0, k, k] for k in range(len(ys))]  # value, weight, lo, hi
    merged = []
    for b in blocks:
        merged.append(b)
        while len(merged) > 1 and merged[-2][0] > merged[-1][0]:
            v2, w2, lo2, hi2 = merged.pop()
            v1, w1, lo1, hi1 = merged.pop()
            nw = w1 + w2
            merged.append([(v1 * w1 + v2 * w2) / nw, nw, lo1, hi2])
    fit = np.empty(len(ys))
    for v, wt, lo, hi in merged:
        fit[lo:hi + 1] = v
    return xs, fit


# ── Robust statistics: quarantine, winsorization, daily cross-sectional IC ────

OUTLIER_ABS_RETURN = 3.0   # |fwd_return| > 300% at h<=10d = data artifact, not alpha
MIN_NAMES_PER_DAY = 8      # cross-sectional IC needs a real cross-section
WINSOR_PCT = (2, 98)       # pooled clip percentiles for winsorized means


def _quarantine(data: list, horizon: int) -> tuple:
    """Split rows into (kept, flagged). A single yfinance artifact (+3810% '10d
    return') was found manufacturing the headline decile spread — such rows are
    data bugs to fix at the source, not alpha; exclude them from ALL return
    stats and surface them for auditing."""
    if horizon > 10:
        return data, []
    kept, flagged = [], []
    for d in data:
        r = d.get("fwd_return")
        if r is not None and abs(r) > OUTLIER_ABS_RETURN:
            flagged.append({"ticker": d.get("ticker"), "snap_day": d.get("snap_day"),
                            "fwd_return": round(float(r), 3)})
        else:
            kept.append(d)
    return kept, flagged


def _clip_bounds(rets: np.ndarray) -> tuple:
    """Pooled winsorization bounds — computed ONCE per matched sample, never
    per-bin (per-bin bounds let a single outlier keep its own bin inflated)."""
    if len(rets) < 20:
        return None, None
    lo, hi = np.nanpercentile(rets, list(WINSOR_PCT))
    return float(lo), float(hi)


def _wmean_pct(rt: np.ndarray, lo, hi):
    if lo is None:
        return round(float(np.nanmean(rt)) * 100, 2)
    return round(float(np.nanmean(np.clip(rt, lo, hi))) * 100, 2)


def _trading_days() -> set | None:
    """ISO dates of real trading sessions (from SPY history). None = unknown."""
    try:
        spy = price_history.get_history("SPY", period="1y")
        if spy is None or spy.empty:
            return None
        return {str(d)[:10] for d in spy.index.date}
    except Exception:
        return None


def _daily_ics(rows: list) -> list:
    """rows = [(snap_day, x, y)] → [(day, cross-sectional spearman)] over real
    trading days with >= MIN_NAMES_PER_DAY names. Pooled IC over all rows
    inflates n (40 names on one day are ONE market draw, not 40)."""
    tdays = _trading_days()
    by_day = {}
    for day, x, y in rows:
        d = str(day)[:10]
        if tdays is not None and d not in tdays:
            continue
        by_day.setdefault(d, []).append((x, y))
    out = []
    for d in sorted(by_day):
        pts = by_day[d]
        if len(pts) < MIN_NAMES_PER_DAY:
            continue
        xs = np.array([p[0] for p in pts], dtype=float)
        ys = np.array([p[1] for p in pts], dtype=float)
        out.append((d, _spearman(xs, ys)))
    return out


def _nw_tstat(series: list, lag: int) -> float | None:
    """t-stat of the mean of a (possibly autocorrelated) daily-IC series using a
    Newey-West (Bartlett) variance. A plain sqrt(n) t on overlapping-horizon
    daily ICs badly overstates significance (it already gave catalyst t≈3.9 off
    3 days of data)."""
    n = len(series)
    if n < 3:
        return None
    a = np.array(series, dtype=float)
    d = a - a.mean()
    # 1/n normalization throughout — with Bartlett weights this keeps the
    # long-run variance estimate positive semi-definite (1/(n-l) does not)
    gamma0 = float((d * d).sum()) / n
    if gamma0 <= 0:
        return None
    var = gamma0
    L = max(0, min(lag, n - 2))
    for l in range(1, L + 1):
        gamma_l = float((d[:-l] * d[l:]).sum()) / n
        var += 2.0 * (1.0 - l / (L + 1.0)) * gamma_l
    if var <= 0:
        var = gamma0  # numerical floor: never less than the no-autocorr variance
    return float(a.mean() / math.sqrt(var / n))


# ── Scorecard ─────────────────────────────────────────────────────────────────

def _decile_table(scores: np.ndarray, rets: np.ndarray, excess: np.ndarray, n_bins=10,
                  lo=None, hi=None, wt=WIN_THRESHOLD) -> list:
    """Bin by score; per bin report count, avg/median/winsorized return, win-rate.
    Raw mean stays visible (the fat right tail IS the strategy) but median and
    the pooled-winsorized mean are the decision-driving columns."""
    if len(scores) < n_bins * 2:
        n_bins = max(2, len(scores) // 4)
    order = np.argsort(scores, kind="mergesort")
    sc, rt, ex = scores[order], rets[order], excess[order]
    bins = np.array_split(np.arange(len(sc)), n_bins)
    out = []
    for k, idx in enumerate(bins):
        if len(idx) == 0:
            continue
        out.append({
            "bin": k + 1,
            "score_lo": round(float(sc[idx[0]]), 1),
            "score_hi": round(float(sc[idx[-1]]), 1),
            "n": int(len(idx)),
            "low_n": bool(len(idx) < 20),
            "avg_return_pct": round(float(rt[idx].mean()) * 100, 2),
            "median_return_pct": round(float(np.median(rt[idx])) * 100, 2),
            "wmean_return_pct": _wmean_pct(rt[idx], lo, hi),
            "avg_excess_pct": round(float(ex[idx].mean()) * 100, 2) if not np.isnan(ex[idx]).all() else None,
            "win_rate": round(float((rt[idx] >= wt).mean()) * 100, 1),
            "beat_spy_rate": round(float((ex[idx] > 0).mean()) * 100, 1) if not np.isnan(ex[idx]).all() else None,
        })
    return out


def scorecard(horizon: int = 20) -> dict:
    """Per-signal IC + decile tables + sample sizes for one horizon."""
    data = db.get_snapshot_returns(horizon)
    if not data:
        return {"available": False, "horizon": horizon, "n": 0,
                "detail": "No resolved forward returns yet — run compute_forward_returns()"}
    data, flagged = _quarantine(data, horizon)
    if not data:
        return {"available": False, "horizon": horizon, "n": 0,
                "n_excluded": len(flagged), "outliers_flagged": flagged,
                "detail": "All rows quarantined as data artifacts"}

    rets = np.array([d["fwd_return"] for d in data], dtype=float)
    excess = np.array([d["excess_return"] if d["excess_return"] is not None else np.nan for d in data], dtype=float)
    lo, hi = _clip_bounds(rets)
    wt = win_threshold(horizon)

    signals = {}
    for field in ("composite_score", "ml_score"):
        sc = np.array([d.get(field) if d.get(field) is not None else np.nan for d in data], dtype=float)
        m = ~np.isnan(sc) & ~np.isnan(rets)
        if m.sum() < 10:
            continue
        scm, rtm = sc[m], rets[m]
        exm = excess[m]
        ic = _spearman(scm, rtm)
        ic_excess = _spearman(scm, np.nan_to_num(exm, nan=0.0)) if not np.isnan(exm).all() else None
        # per-day cross-sectional IC — the honest n is DAYS, not rows
        dics = _daily_ics([(data[i]["snap_day"], sc[i], rets[i]) for i in np.where(m)[0]])
        ic_vals = [v for _, v in dics]
        t_nw = _nw_tstat(ic_vals, lag=horizon - 1)
        table = _decile_table(scm, rtm, exm, lo=lo, hi=hi, wt=wt)
        top, bot = table[-1], table[0]
        signals[field] = {
            "ic": round(ic, 3),
            "ic_excess": round(ic_excess, 3) if ic_excess is not None else None,
            "n": int(m.sum()),
            "n_days": len(dics),
            "mean_daily_ic": round(float(np.mean(ic_vals)), 3) if ic_vals else None,
            "t_nw": round(t_nw, 2) if t_nw is not None else None,
            "deciles": table,
            # winsorized-mean spread — the raw-mean version was manufactured by a
            # single +3810% artifact row in the bottom decile
            "top_minus_bottom_pct": round(top["wmean_return_pct"] - bot["wmean_return_pct"], 2),
            "top_minus_bottom_median_pct": round(top["median_return_pct"] - bot["median_return_pct"], 2),
            "top_win_rate": top["win_rate"],
            "bottom_win_rate": bot["win_rate"],
        }

    return {
        "available": True,
        "horizon": horizon,
        "n": len(data),
        "n_excluded": len(flagged),
        "outliers_flagged": flagged[:10],
        "win_threshold": wt,
        "overall_avg_return_pct": round(float(np.nanmean(rets)) * 100, 2),
        "overall_median_return_pct": round(float(np.nanmedian(rets)) * 100, 2),
        "overall_wmean_return_pct": _wmean_pct(rets, lo, hi),
        "overall_win_rate": round(float((rets >= wt).mean()) * 100, 1),
        "overall_beat_spy_rate": round(float((excess > 0).mean()) * 100, 1) if not np.isnan(excess).all() else None,
        "signals": signals,
    }


MIN_N_CALIBRATION = 120
CAL_SHRINK_N = 25   # served bins shrink toward the base rate by this pseudo-count


def _signal_values(data: list, signal: str) -> np.ndarray:
    """Signal per return-row. Plain column names read straight off the row;
    'bucket:<name>' resolves per-BUCKET raw scores via the snapshot join
    (snapshot_returns has no bucket columns — a naive column swap silently
    no-ops, which is how the catalyst calibration was almost mis-built)."""
    if not signal.startswith("bucket:"):
        return np.array([d.get(signal) if d.get(signal) is not None else np.nan
                         for d in data], dtype=float)
    bucket = signal.split(":", 1)[1]
    feats = _feature_lookup()
    vals = []
    for d in data:
        f = feats.get((d["ticker"], d["snap_day"]))
        v = None
        if f and f.get("bucket_scores"):
            try:
                v = json.loads(f["bucket_scores"]).get(bucket)
            except Exception:
                v = None
        vals.append(v if v is not None else np.nan)
    return np.array(vals, dtype=float)


def calibration(signal: str = "composite_score", horizon: int = 20, n_bins: int = 12,
                target: str = "win") -> dict:
    """Isotonic map raw score → measured P(outcome) at this horizon.

    target 'win'      = P(fwd_return >= win_threshold(horizon))
    target 'beat_spy' = P(excess_return > 0)
    Served bin probabilities are SHRUNK toward the base rate by a 25-row
    pseudo-count so a thin bin can't serve an extreme probability."""
    data = db.get_snapshot_returns(horizon)
    if not data:
        return {"available": False}
    data, _ = _quarantine(data, horizon)
    wt = win_threshold(horizon)
    sc = _signal_values(data, signal)
    if target == "beat_spy":
        y_raw = np.array([d["excess_return"] if d["excess_return"] is not None else np.nan
                          for d in data], dtype=float)
        rt = y_raw
        outcome = (y_raw > 0)
    else:
        rt = np.array([d["fwd_return"] for d in data], dtype=float)
        outcome = (rt >= wt)
    m = ~np.isnan(sc) & ~np.isnan(rt)
    if m.sum() < MIN_N_CALIBRATION:
        return {"available": False, "n": int(m.sum()), "need": MIN_N_CALIBRATION}
    sc_m, win = sc[m], outcome[m].astype(float)
    base = float(win.mean())
    xs, fit = _isotonic(sc_m, win)
    # Downsample to a small monotonic curve for storage/serving
    bins = np.array_split(np.arange(len(xs)), min(n_bins, len(xs)))
    curve = []
    for idx in bins:
        if len(idx) == 0:
            continue
        n_bin = int(len(idx))
        p_fit = float(fit[idx].mean())
        p_served = (n_bin * p_fit + CAL_SHRINK_N * base) / (n_bin + CAL_SHRINK_N)
        curve.append({
            "score": round(float(xs[idx].mean()), 1),
            "p_win": round(p_served, 3),
            "p_fit": round(p_fit, 3),
            "n": n_bin,
        })
    out = {
        "available": True, "signal": signal, "horizon": horizon, "target": target,
        "win_threshold": wt if target == "win" else None, "n": int(m.sum()),
        "base_rate": round(base, 3),
        "curve": curve,
    }
    key = (signal, horizon) if target == "win" else (signal, horizon, target)
    _cache["calibration"][key] = out
    return out


def cpw_gate(horizon: int = 5) -> float:
    """The alert/conviction bar for calibrated P(win): base rate plus a real
    margin — base + max(0.08, 2*sqrt(base*(1-base)/n)). Re-derives whenever the
    win threshold or data changes, so a threshold change can't silently flood
    alerts. Falls back to 0.30 before calibration is ready."""
    cal = _cache["calibration"].get(("composite_score", horizon))
    if not cal or not cal.get("available"):
        return 0.30
    base, n = cal["base_rate"], max(cal["n"], 1)
    return round(base + max(0.08, 2.0 * math.sqrt(base * (1 - base) / n)), 3)


def calibrated_p_win(score: float, signal: str = "composite_score", horizon: int = 20):
    """Look up measured P(win) for a score via the cached isotonic curve. None if uncalibrated."""
    cal = _cache["calibration"].get((signal, horizon))
    if not cal or not cal.get("available"):
        return None
    curve = cal["curve"]
    xs = [c["score"] for c in curve]
    ps = [c["p_win"] for c in curve]
    return float(np.interp(score, xs, ps))


def _feature_lookup() -> dict:
    """Daily-grain {(ticker, day): feature-row} (last snapshot of each day)."""
    out = {}
    for f in db.get_snapshot_features():
        sd = f.get("scan_date")
        if f.get("ticker") and sd:
            out[(f["ticker"], sd[:10])] = f
    return out


MIN_DAYS_EVIDENCE = 15   # independent trading days per horizon before "ready"
SHRINK_HALFLIFE_DAYS = 40  # k = n_days_eff / (n_days_eff + 40)


def _paired_bucket_rows(horizon: int) -> list:
    """[(snap_day, bucket_dict, fwd_return)] joined snapshot↔return rows."""
    rets = db.get_snapshot_returns(horizon)
    rets, _ = _quarantine(rets, horizon)
    feats = _feature_lookup()
    paired = []
    for r in rets:
        f = feats.get((r["ticker"], r["snap_day"]))
        if not f or not f.get("bucket_scores"):
            continue
        try:
            bs = json.loads(f["bucket_scores"])
        except Exception:
            continue
        if any(bs.get(b) is not None for b in BUCKETS):
            paired.append((r["snap_day"], bs, r["fwd_return"]))
    return paired


def _bucket_daily_stats(paired: list, horizon: int) -> dict:
    """Per bucket: daily cross-sectional ICs + Newey-West t. The honest sample
    size is trading DAYS, not rows — 40 names scored on one day are one market
    draw. A pooled Spearman over rows already almost shipped a 100%-catalyst
    weights recommendation off 3 days of data."""
    out = {}
    for b in BUCKETS:
        rows = [(day, bs.get(b), ret) for day, bs, ret in paired if bs.get(b) is not None]
        dics = _daily_ics(rows)
        vals = [v for _, v in dics]
        t = _nw_tstat(vals, lag=horizon - 1)
        out[b] = {
            "daily_ics": [round(v, 3) for v in vals],
            "mean_daily_ic": round(float(np.mean(vals)), 3) if vals else None,
            "sd_daily_ic": round(float(np.std(vals)), 3) if len(vals) > 1 else None,
            "n_days": len(vals),
            "positive_day_share": round(float(np.mean([v > 0 for v in vals])), 2) if vals else None,
            "t_nw": round(t, 2) if t is not None else None,
        }
    return out


def evidence_weights(horizon: int = 5) -> dict:
    """Per-bucket predictive power → evidence-based weights, hardened.

    Statistics per bucket are DAILY cross-sectional ICs with a Newey-West t
    (lag = horizon-1); a bucket is significant only if |t| >= 2 AND its mean
    daily IC has the same sign at BOTH 5d and 10d. The recommendation is a
    SHRUNK blend toward equal weight (k = n_days_eff/(n_days_eff+40)), clamped
    to [0.05, 0.50] per bucket — never again a 100%-one-bucket recommendation
    off a 3-day window. Report-only; weights are never auto-applied.
    """
    paired = _paired_bucket_rows(horizon)
    paired10 = _paired_bucket_rows(10) if horizon != 10 else paired
    n = len(paired)
    current = dict(config.WEIGHTS)

    stats5 = _bucket_daily_stats(paired, horizon)
    stats10 = _bucket_daily_stats(paired10, 10)
    n_days5 = min((stats5[b]["n_days"] for b in BUCKETS), default=0)
    n_days10 = min((stats10[b]["n_days"] for b in BUCKETS), default=0)

    # pooled IC kept for audit only — its n is inflated
    rt = np.array([p[2] for p in paired], dtype=float) if paired else np.array([])
    pooled = {}
    for b in BUCKETS:
        sc = np.array([p[1].get(b) if p[1].get(b) is not None else np.nan for p in paired], dtype=float)
        m = ~np.isnan(sc)
        pooled[b] = round(_spearman(sc[m], rt[m]), 3) if m.sum() >= 30 else None

    significant, harmful, reasons = {}, {}, {}
    for b in BUCKETS:
        s5, s10 = stats5[b], stats10[b]
        t5 = s5["t_nw"]
        if s10["n_days"] < 3 or s10["mean_daily_ic"] is None:
            significant[b] = False
            reasons[b] = f"h10 accruing ({s10['n_days']} days)"
        elif t5 is None or abs(t5) < 2:
            significant[b] = False
            reasons[b] = f"|t_NW|={abs(t5) if t5 is not None else 0:.1f} < 2"
        elif (s5["mean_daily_ic"] or 0) * (s10["mean_daily_ic"] or 0) <= 0:
            significant[b] = False
            reasons[b] = "5d/10d IC signs disagree"
        else:
            significant[b] = True
            reasons[b] = "significant"
        t10 = s10["t_nw"]
        harmful[b] = bool(t5 is not None and t5 <= -2 and t10 is not None and t10 <= -2)

    # shrunk recommendation: blend the positive-IC allocation toward equal weight
    # by data credibility; harmful buckets pinned at the 0.05 floor
    equal = 1.0 / len(BUCKETS)
    n_days_eff = min(n_days5, n_days10)
    k = n_days_eff / (n_days_eff + SHRINK_HALFLIFE_DAYS)
    pos = {b: max(0.0, stats5[b]["mean_daily_ic"] or 0.0) for b in BUCKETS if not harmful[b]}
    total_pos = sum(pos.values())
    raw_shrunk = {}
    for b in BUCKETS:
        if harmful[b]:
            raw_shrunk[b] = 0.05
        else:
            ic_alloc = (pos[b] / total_pos) if total_pos > 0 else equal
            raw_shrunk[b] = min(0.50, max(0.05, equal + k * (ic_alloc - equal)))
    total_shrunk = sum(raw_shrunk.values())
    shrunk = {b: round(v / total_shrunk, 3) for b, v in raw_shrunk.items()}

    # naive (old) recommendation kept for audit — pos/total over pooled IC
    naive_pos = {b: max(0.0, pooled[b] or 0.0) for b in BUCKETS}
    naive_total = sum(naive_pos.values())
    naive = ({b: round(naive_pos[b] / naive_total, 3) for b in BUCKETS}
             if naive_total > 0 else dict(current))

    accruing = n < MIN_N_EVIDENCE or n_days5 < MIN_DAYS_EVIDENCE or n_days10 < MIN_DAYS_EVIDENCE
    any_sig = any(significant.values())
    recommended = shrunk if (not accruing and any_sig) else current

    return {
        "available": not accruing, "status": "accruing" if accruing else "ready",
        "n": n, "need": MIN_N_EVIDENCE, "horizon": horizon,
        "n_days_5d": n_days5, "n_days_10d": n_days10, "need_days": MIN_DAYS_EVIDENCE,
        "bucket_ic": {b: stats5[b]["mean_daily_ic"] for b in BUCKETS},
        "bucket_stats_5d": stats5, "bucket_stats_10d": stats10,
        "pooled_ic_inflated_n": pooled,
        "significant": significant, "significance_reasons": reasons, "harmful": harmful,
        "current_weights": current,
        "recommended_weights": recommended,
        "shrunk_weights": shrunk,
        "naive_ic_weights": naive,
        "shrink_k": round(k, 2),
        "detail": ("Insufficient evidence to reallocate — recommendation = current weights. "
                   f"Daily cross-sectional ICs: {n_days5}d @5d, {n_days10}d @10d "
                   f"(need {MIN_DAYS_EVIDENCE} each); Newey-West t per bucket."
                   if (accruing or not any_sig) else
                   "Shrunk evidence-based weights (daily IC, NW-t significant, "
                   f"clamped [0.05, 0.50], shrink k={k:.2f}). Report-only."),
    }


CAT_COMPONENTS = ["cat_earnings_days", "cat_target_upside", "cat_rec_score",
                  "cat_n_analysts", "attention", "catalyst_event",
                  "prefly_component", "attention_component",
                  "vd_cmf", "vd_updown", "vd_diverge"]
MIN_N_CAT_COMPONENT = 250


def catalyst_components(horizon: int = 5) -> dict:
    """Which catalyst SUB-component carries the bucket's IC (+0.24 measured)?

    Raw sub-values (earnings proximity, analyst target upside, recommendation,
    coverage count, news attention) persist in bucket_scores from 2026-07-02.
    Per component: Spearman IC at this horizon AND at 10d over non-null rows.
    GUARDRAIL (documented here, enforced by the humans reading it): no weight /
    veto / filter change off a component until n>=250 AND >=60 distinct tickers
    AND >=25 distinct scan dates AND sign(ic_5d)==sign(ic_10d) AND |ic|>=0.10.
    Note: cat_earnings_days is DAYS-UNTIL — a NEGATIVE IC means sooner earnings
    → higher forward returns."""
    def _rows(h):
        rets = db.get_snapshot_returns(h)
        rets, _ = _quarantine(rets, h)
        feats = _feature_lookup()
        out = []
        for r in rets:
            f = feats.get((r["ticker"], r["snap_day"]))
            if not f or not f.get("bucket_scores"):
                continue
            try:
                bs = json.loads(f["bucket_scores"])
            except Exception:
                continue
            out.append((r["ticker"], r["snap_day"], bs, r["fwd_return"]))
        return out

    rows5, rows10 = _rows(horizon), _rows(10)
    comps = {}
    for c in CAT_COMPONENTS:
        stats = {}
        for label, rows in (("5d", rows5), ("10d", rows10)):
            pts = [(t, d, bs.get(c), ret) for t, d, bs, ret in rows if bs.get(c) is not None]
            n = len(pts)
            if n >= 30:
                x = np.array([p[2] for p in pts], dtype=float)
                y = np.array([p[3] for p in pts], dtype=float)
                stats[f"ic_{label}"] = round(_spearman(x, y), 3)
            else:
                stats[f"ic_{label}"] = None
            stats[f"n_{label}"] = n
            if label == "5d":
                stats["n_tickers"] = len({p[0] for p in pts})
                stats["n_days"] = len({str(p[1])[:10] for p in pts})
        # stale-single-analyst artifact check: target_upside from 1 analyst is
        # often months old — report that cohort's size separately
        if c == "cat_target_upside":
            single = [1 for t, d, bs, ret in rows5
                      if bs.get(c) is not None and (bs.get("cat_n_analysts") or 0) <= 1]
            stats["single_analyst_n"] = len(single)
        n5 = stats["n_5d"]
        stats["status"] = "ready" if n5 >= MIN_N_CAT_COMPONENT else "accruing"
        stats["need"] = MIN_N_CAT_COMPONENT
        comps[c] = stats

    return {
        "components": comps, "horizon": horizon,
        "actionable_when": "n>=250 AND >=60 tickers AND >=25 scan dates AND "
                           "sign(ic_5d)==sign(ic_10d) AND |ic|>=0.10",
        "detail": "Catalyst sub-component ICs — persisted from 2026-07-02, accrues from zero.",
    }


def tilt_ab(horizon: int = 5) -> dict:
    """Did the regime tilt help? PAIRED daily test: per trading day compute the
    cross-sectional IC of the tilted ordering (rank_score) and of the base
    ordering (composite) on the same names, then test the mean of the per-day
    DELTAS with a Newey-West t. A pooled comparison mixes days and inflates n."""
    rets = db.get_snapshot_returns(horizon)
    rets, _ = _quarantine(rets, horizon)
    feats = _feature_lookup()
    rows = []
    for r in rets:
        f = feats.get((r["ticker"], r["snap_day"]))
        if f and f.get("tilt_factor") is not None and f.get("rank_score") is not None:
            rows.append((r["snap_day"], f["composite_score"], f["rank_score"], f["tilt_factor"], r["fwd_return"]))

    n = len(rows)
    moved = sum(1 for _, c, rk, tf, _r in rows if abs((tf or 1) - 1) >= 0.04)
    base_ics = _daily_ics([(d, c, ret) for d, c, rk, tf, ret in rows])
    tilt_ics = _daily_ics([(d, rk, ret) for d, c, rk, tf, ret in rows])
    base_by_day = dict(base_ics)
    deltas = [(d, v - base_by_day[d]) for d, v in tilt_ics if d in base_by_day]
    n_days = len(deltas)
    delta_vals = [v for _, v in deltas]
    t_delta = _nw_tstat(delta_vals, lag=horizon - 1)

    if n < MIN_N_TILT or moved < 20 or n_days < MIN_DAYS_EVIDENCE:
        return {"available": False, "status": "accruing", "n": n, "moved": moved,
                "need": MIN_N_TILT, "horizon": horizon,
                "n_days": n_days, "need_days": MIN_DAYS_EVIDENCE,
                "mean_delta_ic": round(float(np.mean(delta_vals)), 3) if delta_vals else None,
                "t_delta_nw": round(t_delta, 2) if t_delta is not None else None,
                "detail": f"Paired daily tilt test accruing — {n}/{MIN_N_TILT} rows, "
                          f"{moved} tilted, {n_days}/{MIN_DAYS_EVIDENCE} trading days."}

    comp = np.array([r[1] for r in rows], dtype=float)
    rank = np.array([r[2] for r in rows], dtype=float)
    ret = np.array([r[4] for r in rows], dtype=float)
    lo, hi = _clip_bounds(ret)
    ic_base = _spearman(comp, ret)
    ic_tilt = _spearman(rank, ret)
    # Top-quartile winsorized-mean forward return under each ordering
    k = max(1, n // 4)
    top_base_r = ret[np.argsort(comp)[-k:]]
    top_tilt_r = ret[np.argsort(rank)[-k:]]
    return {
        "available": True, "status": "ready", "n": n, "horizon": horizon,
        "n_days": n_days,
        "ic_base": round(ic_base, 3), "ic_tilt": round(ic_tilt, 3),
        "ic_delta": round(ic_tilt - ic_base, 3),
        "mean_delta_ic": round(float(np.mean(delta_vals)), 3) if delta_vals else None,
        "t_delta_nw": round(t_delta, 2) if t_delta is not None else None,
        "top_quartile_base_pct": _wmean_pct(top_base_r, lo, hi),
        "top_quartile_tilt_pct": _wmean_pct(top_tilt_r, lo, hi),
        "top_quartile_base_median_pct": round(float(np.median(top_base_r)) * 100, 2),
        "top_quartile_tilt_median_pct": round(float(np.median(top_tilt_r)) * 100, 2),
        "tilt_helps": bool(delta_vals and float(np.mean(delta_vals)) > 0),
        "detail": "Paired per-day delta IC (tilted minus base) with Newey-West t; "
                  "top-quartile returns winsorized.",
    }


def _grade_table(grades: np.ndarray, rets: np.ndarray, excess: np.ndarray,
                 lo=None, hi=None, wt=WIN_THRESHOLD) -> list:
    """Per-grade breakdown: n / avg / median / winsorized return / win-rate.
    Mirrors _decile_table()'s shape but bins by discrete grade instead of score
    decile, since conviction grade is ordinal/categorical, not continuous."""
    out = []
    for g in GRADE_ORDER + ["—"]:
        m = grades == g
        n = int(m.sum())
        if n == 0:
            continue
        rt, ex = rets[m], excess[m]
        out.append({
            "grade": g, "n": n, "low_n": n < MIN_N_GRADE_PER_BUCKET,
            "avg_return_pct": round(float(rt.mean()) * 100, 2),
            "median_return_pct": round(float(np.median(rt)) * 100, 2),
            "wmean_return_pct": _wmean_pct(rt, lo, hi),
            "avg_excess_pct": round(float(ex.mean()) * 100, 2) if not np.isnan(ex).all() else None,
            "win_rate": round(float((rt >= wt).mean()) * 100, 1),
            "beat_spy_rate": round(float((ex > 0).mean()) * 100, 1) if not np.isnan(ex).all() else None,
        })
    return out


def grade_scorecard(horizon: int = 20) -> dict:
    """Does the conviction GRADE (A/B/C/WATCH/AVOID) predict forward returns?

    Grade is the newest, most heavily-used signal (it leads the whole Overview)
    but was the one signal never wired into this closed loop. Only NEW snapshots
    (setup_grade persisted from the scan onward) carry a value — historical rows
    have setup_grade IS NULL and are excluded, so this accrues from zero on
    deploy day regardless of how much snapshot history already exists. Not
    backfill-able: reconstructing a historical grade needs the full stock-dict
    shape (edge/coiled/smad/book/breakdown/quote/etc), which was never
    persisted — only a few derived scalar columns were.
    """
    rets = db.get_snapshot_returns(horizon)
    rets, _ = _quarantine(rets, horizon)
    feats = _feature_lookup()
    rows = []
    for r in rets:
        f = feats.get((r["ticker"], r["snap_day"]))
        if not f or not f.get("setup_grade"):
            continue
        ed = None
        if f.get("bucket_scores"):
            try:
                ed = json.loads(f["bucket_scores"]).get("cat_earnings_days")
            except Exception:
                ed = None
        rows.append((f["setup_grade"], r["fwd_return"], r["excess_return"], ed))

    n = len(rows)
    if n < MIN_N_GRADE:
        return {"available": False, "status": "accruing", "n": n, "need": MIN_N_GRADE,
                "horizon": horizon,
                "detail": f"setup_grade persists from new scans only (pre-existing snapshots "
                          f"have no grade recorded and are excluded) — {n}/{MIN_N_GRADE} resolved."}

    grades = np.array([r[0] for r in rows], dtype=object)
    fwd = np.array([r[1] for r in rows], dtype=float)
    excess = np.array([r[2] if r[2] is not None else np.nan for r in rows], dtype=float)
    lo, hi = _clip_bounds(fwd)

    ranked_mask = np.array([g in GRADE_ORDINAL for g in grades])
    ordinal = np.array([GRADE_ORDINAL[g] for g in grades[ranked_mask]], dtype=float)
    grade_ic = _spearman(ordinal, fwd[ranked_mask])

    table = _grade_table(grades, fwd, excess, lo=lo, hi=hi, wt=win_threshold(horizon))
    by_grade = {row["grade"]: row for row in table}

    # Inversion check — a WORSE grade showing a HIGHER forward excess return than
    # a BETTER grade, the same failure mode that made ml_score's confidence hollow.
    inversion = None
    present = [g for g in GRADE_ORDER if g in by_grade and not by_grade[g]["low_n"]]
    for i in range(len(present) - 1):
        worse, better = present[i], present[i + 1]
        wr, br = by_grade[worse]["avg_excess_pct"], by_grade[better]["avg_excess_pct"]
        if wr is not None and br is not None and wr > br:
            inversion = {"worse_grade": worse, "better_grade": better,
                         "worse_avg_excess_pct": wr, "better_avg_excess_pct": br,
                         "detail": f"{worse} outperformed {better} on excess return."}
            break

    a_row, avoid_row = by_grade.get("A"), by_grade.get("AVOID")
    avoid_beats_a = bool(
        a_row and avoid_row and not a_row["low_n"] and not avoid_row["low_n"]
        and avoid_row["avg_excess_pct"] is not None and a_row["avg_excess_pct"] is not None
        and avoid_row["avg_excess_pct"] > a_row["avg_excess_pct"]
    )

    # earnings-proximity cohorts — the kill data for conviction's earnings gate:
    # if ed<=3 is NOT worse than 11-30d at n>=100/cohort, the gate was vetoing edge
    def _cohort(pred):
        rs = np.array([r[1] for r in rows if pred(r[3])], dtype=float)
        ex = np.array([r[2] if r[2] is not None else np.nan for r in rows if pred(r[3])], dtype=float)
        return {"n": len(rs),
                "avg_return_pct": round(float(rs.mean()) * 100, 2) if len(rs) else None,
                "avg_excess_pct": round(float(np.nanmean(ex)) * 100, 2) if len(ex) and not np.isnan(ex).all() else None}
    earnings_cohorts = {
        "ed_0_3": _cohort(lambda e: e is not None and 0 <= e <= 3),
        "ed_4_10": _cohort(lambda e: e is not None and 4 <= e <= 10),
        "ed_11_30": _cohort(lambda e: e is not None and 11 <= e <= 30),
        "ed_none": _cohort(lambda e: e is None),
    }

    return {
        "available": True, "status": "ready", "n": n, "horizon": horizon,
        "win_threshold": win_threshold(horizon),
        "earnings_cohorts": earnings_cohorts,
        "grade_ic": round(grade_ic, 3), "grades": table,
        "inversion": inversion, "avoid_outperforms_a": avoid_beats_a,
        "detail": "Ordinal grade rank (AVOID=0..A=4) Spearman-correlated against forward return; "
                  "'—' shown separately, excluded from the correlation.",
    }


MIN_N_INTRADAY_KILL = 30   # the watcher's pre-registered kill sample


def intraday_scorecard() -> dict:
    """Forward excess returns (5/10/20d vs SPY) from intraday-breakout alert
    prices. PRE-REGISTERED KILL: n>=30 alerts with 10d avg excess <= 0 →
    disable the watcher loop (faster delivery of an unproven trigger is
    unproven value)."""
    alerts = db.get_alerts_by_type("intraday_breakout")
    if not alerts:
        return {"available": False, "n": 0, "need": MIN_N_INTRADAY_KILL,
                "detail": "No intraday breakout alerts fired yet."}
    spy_days, spy_closes = _close_series(price_history.get_history("SPY", period="1y"))
    rows = []
    for a in alerts:
        try:
            payload = json.loads(a.get("payload") or "{}")
            price = float(payload.get("price") or 0)
        except Exception:
            continue
        if price <= 0:
            continue
        day = (a.get("sent_at") or "")[:10]
        hist = price_history.get_history(a["ticker"], period="1y")
        days, closes = _close_series(hist)
        if days is None:
            continue
        row = {"ticker": a["ticker"], "day": day}
        for h in (5, 10, 20):
            e, x = _entry_exit(days, closes, day, h)
            if e is None:
                row[f"ret_{h}d"] = None
                continue
            fwd = x / price - 1.0    # entry at the ALERT price, not the close
            spy = None
            if spy_days is not None:
                se, sx = _entry_exit(spy_days, spy_closes, day, h)
                if se is not None:
                    spy = sx / se - 1.0
            row[f"ret_{h}d"] = round(fwd, 4)
            row[f"excess_{h}d"] = round(fwd - spy, 4) if spy is not None else None
        rows.append(row)

    out = {"available": True, "n": len(rows), "need": MIN_N_INTRADAY_KILL}
    for h in (5, 10, 20):
        ex = [r.get(f"excess_{h}d") for r in rows if r.get(f"excess_{h}d") is not None]
        out[f"avg_excess_{h}d_pct"] = round(float(np.mean(ex)) * 100, 2) if ex else None
        out[f"n_{h}d"] = len(ex)
    ex10 = [r.get("excess_10d") for r in rows if r.get("excess_10d") is not None]
    out["kill_triggered"] = bool(len(ex10) >= MIN_N_INTRADAY_KILL and float(np.mean(ex10)) <= 0)
    out["detail"] = ("KILL CRITERION MET — disable the intraday watcher loop."
                     if out["kill_triggered"] else
                     f"Kill check at n>={MIN_N_INTRADAY_KILL} resolved 10d alerts with avg excess <= 0.")
    return out


def day_movers_scorecard() -> dict:
    """Did the pre-open MOVERS WATCH names actually touch +5% / +10% that day?

    Reads every published movers list (logged with previous closes in the
    preopen_brief payload) and checks the SAME DAY's high against prev close.
    The list is a forecast — this is its box score. Accrues from first
    publication; descriptive below ~25 published names."""
    briefs = db.get_alerts_by_type("preopen_brief")
    rows = []
    for b in briefs:
        try:
            payload = json.loads(b.get("payload") or "{}")
        except Exception:
            continue
        day = (b.get("sent_at") or "")[:10]
        for m in (payload.get("movers") or []):
            t, pc = m.get("ticker"), m.get("prev_close")
            if not t or not pc:
                continue
            hist = price_history.get_history(t, period="3mo")
            if hist is None or hist.empty:
                continue
            try:
                bar = hist.loc[day]
                hi = float(bar["High"]) if hasattr(bar, "__getitem__") else None
            except (KeyError, TypeError):
                continue
            if not hi:
                continue
            move = hi / float(pc) - 1.0
            rows.append({"ticker": t, "day": day, "max_move_pct": round(move * 100, 1),
                         "hit5": move >= 0.05, "hit10": move >= 0.10})
    n = len(rows)
    return {
        "n": n, "descriptive_only": n < 25,
        "hit5_rate": round(float(np.mean([r["hit5"] for r in rows])) * 100, 1) if n else None,
        "hit10_rate": round(float(np.mean([r["hit10"] for r in rows])) * 100, 1) if n else None,
        "avg_max_move_pct": round(float(np.mean([r["max_move_pct"] for r in rows])), 1) if n else None,
        "recent": rows[-10:],
        "detail": "Same-day high vs previous close for every published movers-watch name.",
    }


MIN_N_LEDGER = 50   # below this, the ledger is descriptive only


def ledger_scorecard() -> dict:
    """Realized paper-ledger performance — the only measurement of 'the plan
    makes money' that includes discovery bias, vetoes, and entry feasibility.

    GUARDRAIL: no config/weights/threshold change may cite this until closed
    n>=50 overall AND n>=20 in the specific cited cell (grade or setup)."""
    trades = db.get_paper_trades()
    closed = [t for t in trades if t["status"] == "closed" and t.get("r_realised") is not None]
    opened = [t for t in trades if t["status"] == "open"]
    missed = [t for t in trades if t["status"] == "missed"]
    pending = [t for t in trades if t["status"] == "pending"]
    n = len(closed)

    def _cell(ts):
        rs = np.array([t["r_realised"] for t in ts], dtype=float)
        wins = rs[rs > 0]
        losses = rs[rs <= 0]
        pf = (float(wins.sum()) / abs(float(losses.sum()))) if len(losses) and losses.sum() != 0 else None
        return {
            "n": len(ts), "low_n": len(ts) < 20,
            "win_rate": round(float((rs > 0).mean()) * 100, 1) if len(ts) else None,
            "avg_r": round(float(rs.mean()), 2) if len(ts) else None,
            "profit_factor": round(pf, 2) if pf is not None else None,
            "avg_mfe_r": round(float(np.mean([t.get("mfe_r") or 0 for t in ts])), 2) if ts else None,
            "avg_mae_r": round(float(np.mean([t.get("mae_r") or 0 for t in ts])), 2) if ts else None,
        }

    by_grade = {}
    for g in ("A", "B"):
        ts = [t for t in closed if t.get("grade") == g]
        if ts:
            by_grade[g] = _cell(ts)
    by_setup = {}
    for t in closed:
        by_setup.setdefault(t.get("setup_type") or "?", []).append(t)
    by_setup = {k: _cell(v) for k, v in by_setup.items()}

    # $10k equity curve (fixed book, chronological) + max drawdown
    curve, equity, peak, max_dd = [], 10_000.0, 10_000.0, 0.0
    for t in sorted(closed, key=lambda x: x.get("closed_at") or ""):
        pnl = (t["exit_price"] - t["fill_price"]) * (t.get("shares") or 0)
        equity += pnl
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak if peak > 0 else 0.0)
        curve.append({"closed_at": (t.get("closed_at") or "")[:10], "equity": round(equity, 2)})

    slippages = [abs(t["fill_price"] / t["plan_entry"] - 1)
                 for t in closed + opened
                 if t.get("fill_price") and t.get("plan_entry")]
    attempted = n + len(opened) + len(missed)
    return {
        "n_closed": n, "n_open": len(opened), "n_pending": len(pending), "n_missed": len(missed),
        "descriptive_only": n < MIN_N_LEDGER, "need": MIN_N_LEDGER,
        "win_rate": _cell(closed)["win_rate"] if closed else None,
        "avg_r": _cell(closed)["avg_r"] if closed else None,
        "profit_factor": _cell(closed)["profit_factor"] if closed else None,
        "max_drawdown_pct": round(max_dd * 100, 1),
        "equity": round(equity, 2),
        "equity_curve": curve[-60:],
        "avg_entry_slippage_pct": round(float(np.mean(slippages)) * 100, 2) if slippages else None,
        "missed_fill_rate": round(len(missed) / attempted * 100, 1) if attempted else None,
        "by_grade": by_grade, "by_setup": by_setup,
        "banner": "Paper fills at 30-min granularity — optimistic vs real execution. "
                  f"Descriptive only below {MIN_N_LEDGER} closed trades; no parameter "
                  "change may cite a cell below n=20.",
    }


MIN_DAYS_FACTOR = 15      # independent trading days before a factor gets a verdict
PROMOTE_MIN_DAYS = 30     # pre-registered promotion gate — days ...
PROMOTE_MIN_ABS_T = 2.5   # ... and Newey-West |t|, both required


def _factor_verdict(mean_ic, t, n_days: int, sharpe: float) -> str:
    """How the measured IC lands against the paper's published prior.

    Deliberately asymmetric: 'reproduces' requires agreeing with a paper that
    claimed a real edge, while a paper reporting ~zero Sharpe cannot be
    'reproduced' at all — finding signal there is a genuinely new result and is
    labelled as such rather than being quietly counted as a confirmation."""
    if n_days < MIN_DAYS_FACTOR:
        return "accruing"
    if t is None or abs(t) < 2.0:
        return "no_edge"
    if abs(sharpe) < 0.05:
        return "beats_null_prior"
    return "reproduces" if (mean_ic > 0) == (sharpe > 0) else "inverts"


def factor_scorecard(horizon: int = 5) -> dict:
    """Do the academic factors from awesome-systematic-trading work HERE?

    Each factor in factors.FACTORS is scored the same way the core buckets are:
    per-DAY cross-sectional Spearman IC (n = trading days, never rows — 60 names
    scored on one morning are one market draw), then a Newey-West t with
    lag = horizon-1 to absorb the overlap between consecutive snapshots.

    The published Sharpe is reported beside the measured IC so the two can be
    read against each other. That comparison is the point: those Sharpes come
    from long-short portfolios on large liquid names rebalanced monthly, while
    this app is long-only micro/small-cap with day-to-week holds. Disagreement
    is the expected case, not an error.

    REPORT-ONLY. Nothing here feeds ranking. `promotable` marks a factor that
    cleared the pre-registered bar (>= PROMOTE_MIN_DAYS days AND |t| >=
    PROMOTE_MIN_ABS_T); promotion itself stays a deliberate, committed act."""
    try:
        import factors as _factors
    except Exception as e:
        return {"available": False, "status": "error", "detail": str(e)}

    paired = _paired_bucket_rows(horizon)
    out, n_rows_max = {}, 0
    for name, meta in _factors.FACTORS.items():
        rows = [(day, bs.get(name), ret) for day, bs, ret in paired
                if bs.get(name) is not None]
        n_rows_max = max(n_rows_max, len(rows))
        dics = _daily_ics(rows)
        vals = [v for _, v in dics]
        t = _nw_tstat(vals, lag=horizon - 1)
        mean_ic = float(np.mean(vals)) if vals else None
        verdict = _factor_verdict(mean_ic, t, len(vals), meta["sharpe"])
        out[name] = {
            "paper": meta["paper"],
            "published_sharpe": meta["sharpe"],
            "rebalance": meta["rebalance"],
            "kind": meta["kind"],
            "thesis": meta["thesis"],
            "is_control": name in _factors.CONTROLS,
            "n_rows": len(rows),
            "n_days": len(vals),
            "mean_daily_ic": round(mean_ic, 3) if mean_ic is not None else None,
            "sd_daily_ic": round(float(np.std(vals)), 3) if len(vals) > 1 else None,
            "positive_day_share": round(float(np.mean([v > 0 for v in vals])), 2) if vals else None,
            "t_nw": round(t, 2) if t is not None else None,
            "verdict": verdict,
            "promotable": bool(len(vals) >= PROMOTE_MIN_DAYS and t is not None
                               and abs(t) >= PROMOTE_MIN_ABS_T),
        }

    ready = [k for k, v in out.items() if v["verdict"] not in ("accruing",)]
    return {
        "available": bool(out),
        "status": "ready" if ready else "accruing",
        "horizon": horizon,
        "n_days_max": max((v["n_days"] for v in out.values()), default=0),
        "need_days": MIN_DAYS_FACTOR,
        "factors": out,
        "promotable": [k for k, v in out.items() if v["promotable"]],
        "detail": "Published Sharpes are long-short, large-cap, monthly-rebalanced; this "
                  "app is long-only micro/small-cap held days. The prior is a direction to "
                  "test, not evidence. Report-only — no factor touches ranking until it "
                  f"clears {PROMOTE_MIN_DAYS} days at |t|>={PROMOTE_MIN_ABS_T}.",
        "banner": "Factors persist from new scans only; pre-existing snapshots have no "
                  "fac_* values and are excluded, so this accrues from the deploy date.",
    }


PARABOLIC_SIGNALS = [
    ("par_n_pass", "criteria passed (collapsed)"),
    ("par_n_pass_raw", "criteria passed (uncollapsed)"),
    ("par_base", "base present"),
    ("par_v_recovery", "V-recovery gate fired"),
    ("par_rs20", "sector RS 20d (excess)"),
    ("par_rs40", "sector RS 40d (excess)"),
    ("par_rs20_mans", "sector RS 20d (Mansfield)"),
    ("par_rs40_mans", "sector RS 40d (Mansfield)"),
    ("par_T8_val", "distance above 20-DMA"),
    ("par_T2_val", "12-week range %"),
]


def parabolic_scorecard(horizon: int = 5) -> dict:
    """Does the parabolic criteria ledger predict forward returns?

    Same method as factor_scorecard — per-DAY cross-sectional Spearman IC
    (n = trading days, not rows) with a Newey-West t at lag = horizon-1.

    The comparison that earns its keep here is par_n_pass vs par_n_pass_raw:
    the collapsed and uncollapsed counts of the SAME checklist. If collapsing
    V-recovery artifacts is the right call, the collapsed count should carry the
    higher IC. If it does not, the collapse is costing information and should be
    reverted — which is the only honest way to hold an opinion about it.

    Report-only, on the same pre-registered gate as the academic factors."""
    paired = _paired_bucket_rows(horizon)
    out = {}
    for key, label in PARABOLIC_SIGNALS:
        rows = [(day, bs.get(key), ret) for day, bs, ret in paired
                if bs.get(key) is not None]
        dics = _daily_ics(rows)
        vals = [v for _, v in dics]
        t = _nw_tstat(vals, lag=horizon - 1)
        mean_ic = float(np.mean(vals)) if vals else None
        out[key] = {
            "label": label,
            "n_rows": len(rows),
            "n_days": len(vals),
            "mean_daily_ic": round(mean_ic, 3) if mean_ic is not None else None,
            "t_nw": round(t, 2) if t is not None else None,
            "positive_day_share": round(float(np.mean([v > 0 for v in vals])), 2) if vals else None,
            "promotable": bool(len(vals) >= PROMOTE_MIN_DAYS and t is not None
                               and abs(t) >= PROMOTE_MIN_ABS_T),
        }

    collapse = None
    a, b = out.get("par_n_pass"), out.get("par_n_pass_raw")
    if a and b and a["mean_daily_ic"] is not None and b["mean_daily_ic"] is not None \
            and min(a["n_days"], b["n_days"]) >= MIN_DAYS_FACTOR:
        delta = a["mean_daily_ic"] - b["mean_daily_ic"]
        collapse = {
            "collapsed_ic": a["mean_daily_ic"],
            "uncollapsed_ic": b["mean_daily_ic"],
            "delta": round(delta, 3),
            "verdict": ("collapse helps" if delta > 0.01 else
                        "collapse hurts — consider reverting" if delta < -0.01 else
                        "no measurable difference"),
        }

    n_days_max = max((v["n_days"] for v in out.values()), default=0)
    return {
        "available": bool(out),
        "status": "ready" if n_days_max >= MIN_DAYS_FACTOR else "accruing",
        "horizon": horizon,
        "n_days_max": n_days_max,
        "need_days": MIN_DAYS_FACTOR,
        "signals": out,
        "collapse_test": collapse,
        "promotable": [k for k, v in out.items() if v["promotable"]],
        "detail": "par_* persists from new scans only, so this accrues from the deploy "
                  "date. The collapse_test compares the V-recovery-collapsed criteria "
                  "count against the naive sum of the same checklist — that is the "
                  "measurement that decides whether the collapse was right.",
    }


def refresh(horizons=None) -> dict:
    """Recompute forward returns + scorecard + calibration. Never raises."""
    try:
        cov = compute_forward_returns(horizons)
        cards = {h: scorecard(h) for h in (horizons or HORIZONS)}
        for h in (horizons or HORIZONS):
            for sig in ("composite_score", "ml_score"):
                calibration(sig, h)
                calibration(sig, h, target="beat_spy")
            # catalyst-bucket calibration: BUILT for measurement, not yet served
            # to stocks/alerts (WAIT-gated on n>=300 and >=15 snap days)
            calibration("bucket:catalyst", h)
        _cache["scorecard"] = cards
        # Tuning analyses (auto-activate as the per-bucket / tilt data matures)
        _cache["evidence_weights"] = evidence_weights(5)
        _cache["tilt_ab"] = tilt_ab(5)
        _cache["grade_scorecard"] = {h: grade_scorecard(h) for h in (horizons or HORIZONS)}
        _cache["catalyst_components"] = catalyst_components(5)
        _cache["intraday_scorecard"] = intraday_scorecard()
        _cache["day_movers_scorecard"] = day_movers_scorecard()
        # academic factor candidates — measured at 5d and 10d, the horizons where
        # a day-to-week app can actually act on the answer
        _cache["factor_scorecard"] = {h: factor_scorecard(h) for h in (5, 10)}
        _cache["parabolic_scorecard"] = {h: parabolic_scorecard(h) for h in (5, 10)}
        # cross-horizon evidence matrix — is a bucket's IC consistent across 5/10/20/60d?
        matrix = {}
        for h in (horizons or HORIZONS):
            stats = _bucket_daily_stats(_paired_bucket_rows(h), h)
            for b, s in stats.items():
                matrix.setdefault(b, {})[h] = {
                    "ic": s["mean_daily_ic"], "n_days": s["n_days"], "t_nw": s["t_nw"]}
        _cache["evidence_weights_matrix"] = matrix
        return {"coverage": cov, "scorecards": cards}
    except Exception as e:
        logger.error(f"evaluation.refresh failed: {e}")
        return {"error": str(e)}


def data_status() -> dict:
    """Honest coverage straight from the DB (cheap, no network)."""
    snaps = db.get_all_snapshots()
    tickers_scored = {s["ticker"] for s in snaps}
    days = sorted({s["scan_date"][:10] for s in snaps})
    rets = db.get_snapshot_returns()
    by_h = {}
    for r in rets:
        by_h[r["horizon"]] = by_h.get(r["horizon"], 0) + 1
    tickers_with_returns = {r["ticker"] for r in rets}
    return {
        "tickers_scored": len(tickers_scored),
        "tickers_with_price_history": len(tickers_with_returns),
        "junk_tickers": len(tickers_scored) - len(tickers_with_returns),
        "trading_days_deep": len(days),
        "first_day": days[0] if days else None,
        "last_day": days[-1] if days else None,
        "resolved_by_horizon": by_h,
        "horizons": HORIZONS,
    }


def get_cached() -> dict:
    return {
        "scorecards": _cache.get("scorecard"),
        "coverage": _cache.get("coverage"),
        "data_status": data_status(),
        "last_run": _cache.get("last_run"),
        "calibration": {f"{k[0]}@{k[1]}": v for k, v in _cache.get("calibration", {}).items()},
        "evidence_weights": _cache.get("evidence_weights") or evidence_weights(5),
        "tilt_ab": _cache.get("tilt_ab") or tilt_ab(5),
        "grade_scorecard": _cache.get("grade_scorecard") or {h: grade_scorecard(h) for h in HORIZONS},
        "catalyst_components": _cache.get("catalyst_components") or catalyst_components(5),
        "evidence_weights_matrix": _cache.get("evidence_weights_matrix"),
        "intraday_scorecard": _cache.get("intraday_scorecard"),
        "day_movers_scorecard": _cache.get("day_movers_scorecard"),
        "factor_scorecard": _cache.get("factor_scorecard") or {h: factor_scorecard(h) for h in (5, 10)},
        "parabolic_scorecard": _cache.get("parabolic_scorecard") or {h: parabolic_scorecard(h) for h in (5, 10)},
    }
