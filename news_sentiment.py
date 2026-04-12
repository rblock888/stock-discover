"""
News Sentiment Module
=====================
Replaces Reddit sentiment with news article sentiment.

Uses yfinance news (free, works from servers) + TextBlob sentiment analysis.
Scores based on:
- News volume (how much coverage)
- Sentiment polarity (positive vs negative tone)
- Recency (recent news weighted higher)
- Publisher diversity
"""

from datetime import datetime, timedelta
from textblob import TextBlob


def score(ticker: str) -> dict:
    """Return news sentiment score (0-100)."""
    try:
        import yfinance as yf
        stock = yf.Ticker(ticker)
        news = stock.news
    except Exception:
        return {"score": 50, "details": "News unavailable", "components": {}}

    if not news:
        return {"score": 40, "details": "No recent news", "components": {"articles": 0}}

    components = {}
    scores = []
    now = datetime.now()
    cutoff_recent = now - timedelta(days=14)
    cutoff_older = now - timedelta(days=45)

    recent_articles = []
    older_articles = []
    publishers = set()
    sentiments = []

    for item in news[:30]:
        try:
            # yfinance news format can vary
            content = item.get("content") or item
            title = content.get("title", "") or item.get("title", "")
            summary = content.get("summary", "") or content.get("description", "") or item.get("summary", "")
            publisher = content.get("publisher", {}).get("name") if isinstance(content.get("publisher"), dict) else item.get("publisher", "Unknown")

            # Get timestamp
            pub_time = None
            if "pubDate" in content:
                try:
                    pub_time = datetime.fromisoformat(content["pubDate"].replace("Z", "+00:00")).replace(tzinfo=None)
                except Exception:
                    pass
            if not pub_time and "providerPublishTime" in item:
                pub_time = datetime.fromtimestamp(item["providerPublishTime"])
            if not pub_time:
                pub_time = now - timedelta(days=7)  # assume recent

            if pub_time > cutoff_older:
                if pub_time > cutoff_recent:
                    recent_articles.append({"title": title, "summary": summary})
                else:
                    older_articles.append({"title": title, "summary": summary})

                if publisher:
                    publishers.add(publisher)

                # Sentiment analysis on title + first 200 chars of summary
                text = f"{title} {summary[:200] if summary else ''}"
                if text.strip():
                    blob = TextBlob(text)
                    sentiments.append(blob.sentiment.polarity)
        except Exception:
            continue

    total_articles = len(recent_articles) + len(older_articles)
    if total_articles == 0:
        return {"score": 40, "details": "No recent news", "components": {"articles": 0}}

    # 1. Volume score (30% weight)
    # 10+ articles in 14 days = strong coverage
    volume_score = min(100, len(recent_articles) * 10)
    components["articles"] = total_articles
    scores.append(volume_score * 0.30)

    # 2. Sentiment score (35% weight)
    if sentiments:
        avg_sent = sum(sentiments) / len(sentiments)
        # Map -1..1 to 0..100
        sent_score = max(0, min(100, (avg_sent + 1) * 50))
        components["tone"] = f"{avg_sent:+.2f}"
    else:
        sent_score = 50
    scores.append(sent_score * 0.35)

    # 3. Acceleration score (20% weight) - recent vs older
    accel_score = 50
    if older_articles:
        accel = len(recent_articles) / max(1, len(older_articles))
        accel_score = min(100, accel * 50)  # 2x acceleration = 100
        components["trend"] = f"{accel:.1f}x"
    elif recent_articles:
        accel_score = 75
        components["trend"] = "New coverage"
    scores.append(accel_score * 0.20)

    # 4. Publisher diversity (15% weight)
    diversity_score = min(100, len(publishers) * 20)
    components["publishers"] = len(publishers)
    scores.append(diversity_score * 0.15)

    total = sum(scores)

    return {
        "score": round(total, 1),
        "components": components,
        "details": ", ".join(f"{k}: {v}" for k, v in components.items()),
    }
