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
WIN_THRESHOLD = 0.10            # "win" = +10% forward return
SIGNALS = ["composite_score", "ml_score", "early_score"]
BUCKETS = ["fundamentals", "momentum", "catalyst", "insider", "sentiment"]

# Minimum sample before a measured result is trusted (vs "accruing")
MIN_N_EVIDENCE = 120
MIN_N_TILT = 80

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


# ── Scorecard ─────────────────────────────────────────────────────────────────

def _decile_table(scores: np.ndarray, rets: np.ndarray, excess: np.ndarray, n_bins=10) -> list:
    """Bin by score; per bin report count, avg return, avg excess, win-rate."""
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
            "avg_return_pct": round(float(rt[idx].mean()) * 100, 2),
            "avg_excess_pct": round(float(ex[idx].mean()) * 100, 2) if not np.isnan(ex[idx]).all() else None,
            "win_rate": round(float((rt[idx] >= WIN_THRESHOLD).mean()) * 100, 1),
            "beat_spy_rate": round(float((ex[idx] > 0).mean()) * 100, 1) if not np.isnan(ex[idx]).all() else None,
        })
    return out


def scorecard(horizon: int = 20) -> dict:
    """Per-signal IC + decile tables + sample sizes for one horizon."""
    data = db.get_snapshot_returns(horizon)
    if not data:
        return {"available": False, "horizon": horizon, "n": 0,
                "detail": "No resolved forward returns yet — run compute_forward_returns()"}

    rets = np.array([d["fwd_return"] for d in data], dtype=float)
    excess = np.array([d["excess_return"] if d["excess_return"] is not None else np.nan for d in data], dtype=float)

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
        table = _decile_table(scm, rtm, exm)
        top, bot = table[-1], table[0]
        signals[field] = {
            "ic": round(ic, 3),
            "ic_excess": round(ic_excess, 3) if ic_excess is not None else None,
            "n": int(m.sum()),
            "deciles": table,
            "top_minus_bottom_pct": round(top["avg_return_pct"] - bot["avg_return_pct"], 2),
            "top_win_rate": top["win_rate"],
            "bottom_win_rate": bot["win_rate"],
        }

    return {
        "available": True,
        "horizon": horizon,
        "n": len(data),
        "overall_avg_return_pct": round(float(np.nanmean(rets)) * 100, 2),
        "overall_win_rate": round(float((rets >= WIN_THRESHOLD).mean()) * 100, 1),
        "overall_beat_spy_rate": round(float((excess > 0).mean()) * 100, 1) if not np.isnan(excess).all() else None,
        "signals": signals,
    }


def calibration(signal: str = "composite_score", horizon: int = 20, n_bins: int = 12) -> dict:
    """Isotonic map raw score → measured P(forward return ≥ WIN_THRESHOLD)."""
    data = db.get_snapshot_returns(horizon)
    if not data:
        return {"available": False}
    sc = np.array([d.get(signal) if d.get(signal) is not None else np.nan for d in data], dtype=float)
    rt = np.array([d["fwd_return"] for d in data], dtype=float)
    m = ~np.isnan(sc) & ~np.isnan(rt)
    if m.sum() < 20:
        return {"available": False, "n": int(m.sum())}
    sc, win = sc[m], (rt[m] >= WIN_THRESHOLD).astype(float)
    xs, fit = _isotonic(sc, win)
    # Downsample to a small monotonic curve for storage/serving
    bins = np.array_split(np.arange(len(xs)), min(n_bins, len(xs)))
    curve = []
    for idx in bins:
        if len(idx) == 0:
            continue
        curve.append({
            "score": round(float(xs[idx].mean()), 1),
            "p_win": round(float(fit[idx].mean()), 3),
            "n": int(len(idx)),
        })
    out = {
        "available": True, "signal": signal, "horizon": horizon,
        "win_threshold": WIN_THRESHOLD, "n": int(m.sum()),
        "base_rate": round(float(win.mean()), 3),
        "curve": curve,
    }
    _cache["calibration"][(signal, horizon)] = out
    return out


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


def evidence_weights(horizon: int = 5) -> dict:
    """Per-bucket Information Coefficient vs forward return → evidence-based weights.

    Measures which buckets actually predict and what the composite weights
    *should* be (∝ positive IC). Reports current vs recommended but does NOT
    auto-apply — it stays "accruing" until per-bucket data (persisted from
    2026-06-22) resolves enough forward returns to be trustworthy.
    """
    rets = db.get_snapshot_returns(horizon)
    feats = _feature_lookup()
    paired = []  # (bucket_dict, fwd_return)
    for r in rets:
        f = feats.get((r["ticker"], r["snap_day"]))
        if not f or not f.get("bucket_scores"):
            continue
        try:
            bs = json.loads(f["bucket_scores"])
        except Exception:
            continue
        if any(bs.get(b) is not None for b in BUCKETS):
            paired.append((bs, r["fwd_return"]))

    n = len(paired)
    current = dict(config.WEIGHTS)
    if n < MIN_N_EVIDENCE:
        return {"available": False, "status": "accruing", "n": n,
                "need": MIN_N_EVIDENCE, "horizon": horizon,
                "current_weights": current,
                "detail": f"Per-bucket scores resolve from 2026-06-22 — {n}/{MIN_N_EVIDENCE} forward returns so far."}

    rt = np.array([p[1] for p in paired], dtype=float)
    ics, pos = {}, {}
    for b in BUCKETS:
        sc = np.array([p[0].get(b) if p[0].get(b) is not None else np.nan for p in paired], dtype=float)
        m = ~np.isnan(sc)
        ic = _spearman(sc[m], rt[m]) if m.sum() >= MIN_N_EVIDENCE else 0.0
        ics[b] = round(ic, 3)
        pos[b] = max(0.0, ic)

    total = sum(pos.values())
    recommended = ({b: round(pos[b] / total, 3) for b in BUCKETS} if total > 0 else current)
    return {
        "available": True, "status": "ready", "n": n, "horizon": horizon,
        "bucket_ic": ics,
        "current_weights": current,
        "recommended_weights": recommended,
        "detail": "Evidence-based weights ∝ each bucket's positive IC vs forward return.",
    }


def tilt_ab(horizon: int = 5) -> dict:
    """Did the regime tilt help? Compare tilted (rank_score) vs base (composite)
    ordering on realized forward returns. Accrues until tilted snapshots age."""
    rets = db.get_snapshot_returns(horizon)
    feats = _feature_lookup()
    rows = []
    for r in rets:
        f = feats.get((r["ticker"], r["snap_day"]))
        if f and f.get("tilt_factor") is not None and f.get("rank_score") is not None:
            rows.append((f["composite_score"], f["rank_score"], f["tilt_factor"], r["fwd_return"]))

    n = len(rows)
    moved = sum(1 for c, rk, tf, _ in rows if abs((tf or 1) - 1) >= 0.04)
    if n < MIN_N_TILT or moved < 20:
        return {"available": False, "status": "accruing", "n": n, "moved": moved,
                "need": MIN_N_TILT, "horizon": horizon,
                "detail": f"Regime tilt persists from 2026-06-22; needs tilted picks to age {horizon}d — {n}/{MIN_N_TILT} resolved, {moved} actually tilted."}

    comp = np.array([r[0] for r in rows], dtype=float)
    rank = np.array([r[1] for r in rows], dtype=float)
    ret = np.array([r[3] for r in rows], dtype=float)
    ic_base = _spearman(comp, ret)
    ic_tilt = _spearman(rank, ret)
    # Top-quartile mean forward return under each ordering
    k = max(1, n // 4)
    top_base = float(np.mean(ret[np.argsort(comp)[-k:]]))
    top_tilt = float(np.mean(ret[np.argsort(rank)[-k:]]))
    return {
        "available": True, "status": "ready", "n": n, "horizon": horizon,
        "ic_base": round(ic_base, 3), "ic_tilt": round(ic_tilt, 3),
        "ic_delta": round(ic_tilt - ic_base, 3),
        "top_quartile_base_pct": round(top_base * 100, 2),
        "top_quartile_tilt_pct": round(top_tilt * 100, 2),
        "tilt_helps": ic_tilt > ic_base,
        "detail": "Tilted ranking (rank_score) vs base (composite) on realized returns.",
    }


def refresh(horizons=None) -> dict:
    """Recompute forward returns + scorecard + calibration. Never raises."""
    try:
        cov = compute_forward_returns(horizons)
        cards = {h: scorecard(h) for h in (horizons or HORIZONS)}
        for h in (horizons or HORIZONS):
            for sig in ("composite_score", "ml_score"):
                calibration(sig, h)
        _cache["scorecard"] = cards
        # Tuning analyses (auto-activate as the per-bucket / tilt data matures)
        _cache["evidence_weights"] = evidence_weights(5)
        _cache["tilt_ab"] = tilt_ab(5)
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
    }
