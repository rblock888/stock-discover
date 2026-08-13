"""
Backtesting — realized performance of past picks at a FIXED forward horizon.

Reads the snapshot_returns table populated by evaluation.compute_forward_returns
(real close at scan_date + N trading days), so it measures a proper N-day
forward return — not the old "mark every pick to today's price" which smeared
holding periods together and returned nothing once the LIMIT 500 / 50-ticker
caps kicked in.
"""

import db

EMPTY = {
    "total_picks": 0, "avg_return": 0, "win_rate": 0,
    "best_picks": [], "worst_picks": [], "by_segment": {}, "by_window": {},
}


def _agg(rows: list) -> tuple:
    """(avg_return_pct, win_rate_pct) over fwd_return rows."""
    n = len(rows)
    if not n:
        return 0.0, 0.0
    avg = sum(r["fwd_return"] for r in rows) / n * 100
    wins = sum(1 for r in rows if r["fwd_return"] > 0) / n * 100
    return round(avg, 1), round(wins, 1)


def compute_performance(horizon: int = None) -> dict:
    """Realized forward-return performance, segmented by score tier and horizon."""
    all_rows = db.get_snapshot_returns()
    if not all_rows:
        return {**EMPTY, "details": "No realized returns yet — evaluation backfill pending"}

    by_h = {}
    for r in all_rows:
        by_h.setdefault(r["horizon"], []).append(r)
    horizons = sorted(by_h)

    # Primary horizon = the one with the most resolved data (longest meaningful sample)
    primary = horizon if horizon in by_h else max(horizons, key=lambda h: len(by_h[h]))
    rows = by_h[primary]

    total = len(rows)
    avg, win_rate = _agg(rows)
    excess_rows = [r for r in rows if r.get("excess_return") is not None]
    beat_spy = round(sum(1 for r in excess_rows if r["excess_return"] > 0) / len(excess_rows) * 100, 1) if excess_rows else None

    def fmt(r):
        return {
            "ticker": r["ticker"],
            "scan_date": r["snap_day"],
            "entry_price": r["entry_price"],
            "current_price": r["exit_price"],
            "return_pct": round(r["fwd_return"] * 100, 1),
            "days_held": primary,
            "composite_score": r["composite_score"],
            "ml_score": r["ml_score"],
        }

    # Best/worst — one row per ticker (its most extreme outcome), so the
    # leaderboards show distinct names rather than the same ticker repeated.
    ordered = sorted(rows, key=lambda x: x["fwd_return"], reverse=True)
    seen_best, seen_worst = set(), set()
    best = []
    for r in ordered:
        if r["ticker"] not in seen_best:
            seen_best.add(r["ticker"]); best.append(fmt(r))
        if len(best) >= 5:
            break
    worst = []
    for r in reversed(ordered):
        if r["ticker"] not in seen_worst:
            seen_worst.add(r["ticker"]); worst.append(fmt(r))
        if len(worst) >= 5:
            break

    # By composite-score tier (terciles) — does a higher score actually pay?
    scored = sorted([r for r in rows if r.get("composite_score") is not None],
                    key=lambda x: x["composite_score"])
    by_segment = {}
    if len(scored) >= 6:
        third = len(scored) // 3
        tiers = [
            ("Top composite", scored[-third:]),
            ("Mid composite", scored[third:-third] if len(scored) > 2 * third else []),
            ("Low composite", scored[:third]),
        ]
        for label, group in tiers:
            if group:
                a, w = _agg(group)
                by_segment[label] = {
                    "count": len(group),
                    "avg_return": a,
                    "win_rate": w,
                    "best": max(group, key=lambda x: x["fwd_return"])["ticker"],
                }

    # By horizon (all resolved horizons)
    by_window = {}
    for h in horizons:
        a, w = _agg(by_h[h])
        by_window[f"{h}-day"] = {"count": len(by_h[h]), "avg_return": a, "win_rate": w}

    return {
        "total_picks": total,
        "avg_return": avg,
        "win_rate": win_rate,
        "beat_spy_rate": beat_spy,
        "primary_horizon": primary,
        "best_picks": best,
        "worst_picks": worst,
        "by_segment": by_segment,
        "by_window": by_window,
        "details": f"{total} picks measured at {primary}-day horizon · {win_rate:.0f}% win · {avg:+.1f}% avg",
    }
