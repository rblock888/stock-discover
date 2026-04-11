"""StockTwits sentiment and trending tickers. Free API, no auth needed."""

import requests
from datetime import datetime, timedelta


STOCKTWITS_API = "https://api.stocktwits.com/api/2"


def get_sentiment(ticker: str) -> dict:
    """Get sentiment data for a ticker from StockTwits."""
    try:
        url = f"{STOCKTWITS_API}/streams/symbol/{ticker}.json"
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            return {"score": 50, "details": "StockTwits unavailable", "components": {}}

        data = resp.json()
        symbol = data.get("symbol", {})
        messages = data.get("messages", [])

        if not messages:
            return {"score": 40, "details": "No StockTwits posts", "components": {}}

        # Count bullish/bearish from message sentiment labels
        bullish = 0
        bearish = 0
        total = len(messages)

        for msg in messages:
            sentiment = msg.get("entities", {}).get("sentiment", {})
            if sentiment:
                if sentiment.get("basic") == "Bullish":
                    bullish += 1
                elif sentiment.get("basic") == "Bearish":
                    bearish += 1

        labeled = bullish + bearish
        components = {}

        # Sentiment ratio
        if labeled > 0:
            bull_pct = bullish / labeled
            sentiment_score = bull_pct * 100
            components["bullish"] = f"{bull_pct:.0%} ({bullish}/{labeled})"
        else:
            sentiment_score = 50
            components["bullish"] = "No labeled posts"

        # Message volume (activity level)
        volume_score = min(100, total * 3.3)  # 30 messages = max
        components["posts"] = total

        # Watchlist count (popularity)
        watchers = symbol.get("watchlist_count", 0)
        watcher_score = min(100, watchers / 100)  # 10K watchers = max
        if watchers:
            components["watchers"] = f"{watchers:,}"

        # Weighted combination
        score = sentiment_score * 0.50 + volume_score * 0.30 + watcher_score * 0.20

        return {
            "score": round(score, 1),
            "components": components,
            "details": ", ".join(f"{k}: {v}" for k, v in components.items()),
        }

    except Exception:
        return {"score": 50, "details": "StockTwits error", "components": {}}


def get_trending() -> list:
    """Get trending tickers from StockTwits."""
    try:
        url = f"{STOCKTWITS_API}/trending/symbols.json"
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            return []

        data = resp.json()
        symbols = data.get("symbols", [])
        return [s["symbol"] for s in symbols if "symbol" in s]

    except Exception:
        return []


def score(ticker: str) -> dict:
    """Score a ticker using StockTwits sentiment. Used by the scoring pipeline."""
    return get_sentiment(ticker)
