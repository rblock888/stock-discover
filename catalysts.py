"""Catalyst scoring: earnings dates, news, analyst targets."""

import fmp
from datetime import datetime, timedelta


def _fmp_score(ticker: str) -> dict:
    """Score using FMP API."""
    components = {}
    scores = []

    quote = fmp.get_quote(ticker)

    # Earnings date
    earnings_score = 30
    earnings = fmp.get_earnings_calendar(ticker)
    if earnings:
        for e in earnings:
            try:
                ed = datetime.strptime(e.get("date", ""), "%Y-%m-%d").date()
                days_away = (ed - datetime.now().date()).days
                if 0 < days_away <= 30:
                    earnings_score = 90
                    components["earnings"] = f"In {days_away} days"
                elif 0 < days_away <= 60:
                    earnings_score = 60
                    components["earnings"] = f"In {days_away} days"
                elif -7 <= days_away <= 0:
                    earnings_score = 70
                    components["earnings"] = "Just reported"
                break
            except Exception:
                continue
    scores.append(earnings_score * 0.30)

    # Analyst price target
    target_score = 50
    targets = fmp.get_price_target(ticker)
    price = quote.get("price", 0) or 0
    if targets and price > 0:
        avg_target = targets[0].get("targetConsensus", 0) or targets[0].get("targetMean", 0)
        if avg_target and avg_target > 0:
            upside = (avg_target - price) / price
            if upside > 0.50:
                target_score = 95
            elif upside > 0.25:
                target_score = 75
            elif upside > 0:
                target_score = 55
            else:
                target_score = 20
            components["target_upside"] = f"{upside:.0%}"
    scores.append(target_score * 0.25)

    # Analyst estimates / EPS growth
    estimate_score = 50
    estimates = fmp.get_analyst_estimates(ticker)
    if estimates and len(estimates) >= 2:
        est_rev_0 = estimates[0].get("estimatedRevenueAvg", 0)
        est_rev_1 = estimates[1].get("estimatedRevenueAvg", 0)
        if est_rev_0 and est_rev_1 and est_rev_1 > 0:
            rev_growth = (est_rev_0 - est_rev_1) / abs(est_rev_1)
            if rev_growth > 0.20:
                estimate_score = 90
            elif rev_growth > 0.10:
                estimate_score = 70
            elif rev_growth > 0:
                estimate_score = 55
            components["est_rev_growth"] = f"{rev_growth:.0%}"
    scores.append(estimate_score * 0.25)

    # Price change (recent momentum as catalyst proxy)
    change_score = 50
    change_pct = quote.get("changesPercentage", 0) or 0
    if change_pct > 5:
        change_score = 85
        components["today"] = f"+{change_pct:.1f}%"
    elif change_pct > 2:
        change_score = 65
        components["today"] = f"+{change_pct:.1f}%"
    elif change_pct < -5:
        change_score = 20
        components["today"] = f"{change_pct:.1f}%"
    scores.append(change_score * 0.20)

    total = sum(scores)
    return {"score": round(total, 1), "components": components,
            "details": ", ".join(f"{k}: {v}" for k, v in components.items())}


def _yf_score(ticker: str) -> dict:
    """Fallback to yfinance."""
    try:
        import yfinance as yf
        stock = yf.Ticker(ticker)
        info = stock.info or {}
    except Exception:
        return {"score": 0, "details": "Failed to fetch data", "components": {}}

    components = {}
    scores = []

    # Earnings
    earnings_score = 30
    try:
        cal = stock.calendar
        if cal and isinstance(cal, dict):
            ed = cal.get("Earnings Date")
            if ed:
                earnings_date = ed[0] if isinstance(ed, list) else ed
                if hasattr(earnings_date, "date"):
                    days_away = (earnings_date.date() - datetime.now().date()).days
                else:
                    days_away = (earnings_date - datetime.now().date()).days
                if 0 < days_away <= 30:
                    earnings_score = 90
                    components["earnings"] = f"In {days_away} days"
                elif 0 < days_away <= 60:
                    earnings_score = 60
                    components["earnings"] = f"In {days_away} days"
    except Exception:
        pass
    scores.append(earnings_score * 0.30)

    # Target
    target_score = 50
    target = info.get("targetMeanPrice")
    current = info.get("currentPrice") or info.get("regularMarketPrice")
    if target and current and current > 0:
        upside = (target - current) / current
        if upside > 0.50: target_score = 95
        elif upside > 0.25: target_score = 75
        elif upside > 0: target_score = 55
        else: target_score = 20
        components["target_upside"] = f"{upside:.0%}"
    scores.append(target_score * 0.25)

    # Recommendation
    rec_score = 50
    rec = info.get("recommendationKey", "").lower()
    rec_map = {"strong_buy": 95, "buy": 80, "outperform": 70, "hold": 50, "sell": 10}
    if rec in rec_map:
        rec_score = rec_map[rec]
        components["recommendation"] = rec.replace("_", " ").title()
    scores.append(rec_score * 0.25)

    scores.append(50 * 0.20)  # neutral for news

    total = sum(scores)
    return {"score": round(total, 1), "components": components,
            "details": ", ".join(f"{k}: {v}" for k, v in components.items())}


def score(ticker: str) -> dict:
    if fmp.is_configured():
        return _fmp_score(ticker)
    return _yf_score(ticker)
