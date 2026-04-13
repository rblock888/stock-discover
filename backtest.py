"""
Backtesting module — measures historical performance of past picks.

Compares each saved snapshot's price to current price, computes returns.
Aggregates by segment (AI Picks, Multi-Signal Alerts, etc.) and time window.
"""

from datetime import datetime, timedelta
from collections import defaultdict
import db


def _get_current_price(ticker: str) -> float:
    """Get current price using FMP or yfinance."""
    try:
        import fmp
        if fmp.is_configured():
            q = fmp.get_quote(ticker)
            if q and q.get("price"):
                return q["price"]
    except Exception:
        pass

    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info or {}
        return info.get("currentPrice") or info.get("regularMarketPrice", 0)
    except Exception:
        return 0


def _days_between(date_str: str) -> int:
    try:
        d = datetime.fromisoformat(date_str)
        return (datetime.now() - d).days
    except Exception:
        return 0


def compute_performance() -> dict:
    """
    Compute backtest performance across all saved snapshots.

    Returns:
        - total_picks: how many snapshots tracked
        - avg_return: average % return
        - win_rate: % of picks that gained
        - best_picks: top 5 winners
        - worst_picks: bottom 5 losers
        - by_segment: breakdown by AI Pick / Alert / Other
        - by_window: breakdown by time held
    """
    snapshots = db.get_snapshots()
    if not snapshots:
        return {
            "total_picks": 0,
            "avg_return": 0,
            "win_rate": 0,
            "best_picks": [],
            "worst_picks": [],
            "by_segment": {},
            "by_window": {},
            "details": "No historical data yet — needs at least 1 scan",
        }

    # Get unique tickers in snapshots
    tickers = list({s["ticker"] for s in snapshots})

    # Cache current prices
    current_prices = {}
    for t in tickers[:50]:  # cap at 50 for speed
        p = _get_current_price(t)
        if p > 0:
            current_prices[t] = p

    results = []
    for s in snapshots:
        ticker = s["ticker"]
        if ticker not in current_prices:
            continue
        if not s["price"] or s["price"] <= 0:
            continue

        days_held = _days_between(s["scan_date"])
        if days_held < 1:
            continue  # not enough time

        return_pct = (current_prices[ticker] - s["price"]) / s["price"] * 100

        results.append({
            "ticker": ticker,
            "scan_date": s["scan_date"],
            "entry_price": s["price"],
            "current_price": current_prices[ticker],
            "return_pct": round(return_pct, 1),
            "days_held": days_held,
            "composite_score": s["composite_score"],
            "ml_score": s["ml_score"],
            "is_alert": s["is_alert"],
            "is_ai_pick": s["is_ai_pick"],
        })

    if not results:
        return {
            "total_picks": 0,
            "avg_return": 0,
            "win_rate": 0,
            "best_picks": [],
            "worst_picks": [],
            "by_segment": {},
            "by_window": {},
            "details": "No old enough snapshots for backtesting yet",
        }

    # Aggregate
    total = len(results)
    avg = sum(r["return_pct"] for r in results) / total
    wins = sum(1 for r in results if r["return_pct"] > 0)
    win_rate = wins / total * 100

    # Top/bottom
    sorted_results = sorted(results, key=lambda x: x["return_pct"], reverse=True)
    best = sorted_results[:5]
    worst = sorted_results[-5:][::-1]

    # By segment
    ai_picks = [r for r in results if r["is_ai_pick"]]
    alerts = [r for r in results if r["is_alert"]]
    other = [r for r in results if not r["is_ai_pick"] and not r["is_alert"]]

    by_segment = {}
    for label, group in [("AI Picks", ai_picks), ("Multi-Signal Alerts", alerts), ("Other Picks", other)]:
        if group:
            avg_g = sum(r["return_pct"] for r in group) / len(group)
            wins_g = sum(1 for r in group if r["return_pct"] > 0)
            by_segment[label] = {
                "count": len(group),
                "avg_return": round(avg_g, 1),
                "win_rate": round(wins_g / len(group) * 100, 1),
                "best": max(group, key=lambda x: x["return_pct"])["ticker"] if group else None,
            }

    # By time window
    by_window = {}
    for label, min_d, max_d in [("1-7 days", 1, 7), ("8-30 days", 8, 30),
                                  ("31-60 days", 31, 60), ("60+ days", 60, 9999)]:
        group = [r for r in results if min_d <= r["days_held"] <= max_d]
        if group:
            avg_g = sum(r["return_pct"] for r in group) / len(group)
            wins_g = sum(1 for r in group if r["return_pct"] > 0)
            by_window[label] = {
                "count": len(group),
                "avg_return": round(avg_g, 1),
                "win_rate": round(wins_g / len(group) * 100, 1),
            }

    return {
        "total_picks": total,
        "avg_return": round(avg, 1),
        "win_rate": round(win_rate, 1),
        "best_picks": best,
        "worst_picks": worst,
        "by_segment": by_segment,
        "by_window": by_window,
        "details": f"{total} snapshots tracked, {win_rate:.0f}% win rate, {avg:+.1f}% avg return",
    }
