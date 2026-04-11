"""Catalyst scoring: earnings dates, news, upcoming events."""

import yfinance as yf
from datetime import datetime, timedelta


def score(ticker: str) -> dict:
    """Return a catalyst score (0-100) and details."""
    try:
        stock = yf.Ticker(ticker)
        info = stock.info or {}
    except Exception:
        return {"score": 0, "details": "Failed to fetch data", "components": {}}

    components = {}
    scores = []

    # --- Upcoming earnings (proximity = higher score) ---
    earnings_score = 30  # baseline
    try:
        cal = stock.calendar
        if cal is not None:
            earnings_date = None
            if isinstance(cal, dict):
                ed = cal.get("Earnings Date")
                if ed:
                    earnings_date = ed[0] if isinstance(ed, list) else ed
            if earnings_date:
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
                elif days_away <= 0 and days_away > -7:
                    earnings_score = 70  # just reported
                    components["earnings"] = "Just reported"
                else:
                    components["earnings"] = f"In {days_away} days"
    except Exception:
        pass
    scores.append(("earnings", earnings_score, 0.30))

    # --- Recent news volume (yfinance news) ---
    news_score = 30
    try:
        news = stock.news
        if news:
            recent_count = 0
            cutoff = datetime.now() - timedelta(days=14)
            for item in news[:20]:
                pub_time = item.get("providerPublishTime")
                if pub_time:
                    pub_date = datetime.fromtimestamp(pub_time)
                    if pub_date >= cutoff:
                        recent_count += 1
            if recent_count >= 5:
                news_score = 90
                components["news"] = f"{recent_count} articles in 14d"
            elif recent_count >= 3:
                news_score = 70
                components["news"] = f"{recent_count} articles in 14d"
            elif recent_count >= 1:
                news_score = 50
                components["news"] = f"{recent_count} articles in 14d"
            else:
                components["news"] = "No recent news"
        else:
            components["news"] = "No news available"
    except Exception:
        pass
    scores.append(("news", news_score, 0.25))

    # --- Analyst target vs current price (upside potential) ---
    target_score = 50
    try:
        target = info.get("targetMeanPrice")
        current = info.get("currentPrice") or info.get("regularMarketPrice")
        if target and current and current > 0:
            upside = (target - current) / current
            if upside > 0.50:
                target_score = 95
                components["target_upside"] = f"{upside:.0%}"
            elif upside > 0.25:
                target_score = 75
                components["target_upside"] = f"{upside:.0%}"
            elif upside > 0:
                target_score = 55
                components["target_upside"] = f"{upside:.0%}"
            else:
                target_score = 20
                components["target_upside"] = f"{upside:.0%} (downside)"
    except Exception:
        pass
    scores.append(("target", target_score, 0.20))

    # --- Recommendation trend ---
    rec_score = 50
    try:
        rec = info.get("recommendationKey", "").lower()
        rec_map = {
            "strong_buy": 95,
            "buy": 80,
            "outperform": 70,
            "overweight": 70,
            "hold": 50,
            "underperform": 25,
            "sell": 10,
            "strong_sell": 5,
        }
        if rec in rec_map:
            rec_score = rec_map[rec]
            components["recommendation"] = rec.replace("_", " ").title()
    except Exception:
        pass
    scores.append(("recommendation", rec_score, 0.25))

    total = sum(s * w for _, s, w in scores)

    return {
        "score": round(total, 1),
        "components": components,
        "details": ", ".join(f"{k}: {v}" for k, v in components.items()),
    }
