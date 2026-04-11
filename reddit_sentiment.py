"""Reddit sentiment scoring: mentions, sentiment, acceleration, breadth."""

import praw
from datetime import datetime, timedelta
from collections import defaultdict
from textblob import TextBlob
import config


def _get_reddit():
    """Initialize Reddit API client."""
    if not config.REDDIT_CLIENT_ID or not config.REDDIT_CLIENT_SECRET:
        return None
    return praw.Reddit(
        client_id=config.REDDIT_CLIENT_ID,
        client_secret=config.REDDIT_CLIENT_SECRET,
        user_agent=config.REDDIT_USER_AGENT,
    )


def _search_ticker(reddit, ticker: str, subreddit_name: str, limit: int = 100) -> list:
    """Search a subreddit for ticker mentions."""
    results = []
    try:
        sub = reddit.subreddit(subreddit_name)
        for post in sub.search(f"${ticker} OR {ticker}", sort="new", time_filter="month", limit=limit):
            results.append({
                "title": post.title,
                "text": post.selftext[:500],
                "score": post.score,
                "created": datetime.fromtimestamp(post.created_utc),
                "subreddit": subreddit_name,
                "num_comments": post.num_comments,
            })
    except Exception:
        pass
    return results


def score(ticker: str) -> dict:
    """Return a sentiment score (0-100) and details."""
    reddit = _get_reddit()
    if reddit is None:
        return {
            "score": 50,  # neutral when Reddit is not configured
            "details": "Reddit API not configured (set REDDIT_CLIENT_ID/SECRET in config.py)",
            "components": {"status": "not configured"},
        }

    components = {}
    scores_list = []
    all_posts = []
    subreddits_with_mentions = set()

    cutoff = datetime.now() - timedelta(days=config.REDDIT_LOOKBACK_DAYS)

    for sub_name in config.REDDIT_SUBREDDITS:
        posts = _search_ticker(reddit, ticker, sub_name)
        for p in posts:
            if p["created"] >= cutoff:
                all_posts.append(p)
                subreddits_with_mentions.add(sub_name)

    if not all_posts:
        return {
            "score": 30,
            "details": "No Reddit mentions found",
            "components": {"mentions": 0},
        }

    # --- Mention count ---
    mention_count = len(all_posts)
    mention_score = min(100, mention_count * 3)  # 33+ mentions = max
    components["mentions"] = mention_count
    scores_list.append(("mentions", mention_score, 0.25))

    # --- Sentiment analysis ---
    sentiments = []
    for p in all_posts:
        text = f"{p['title']} {p['text']}"
        blob = TextBlob(text)
        sentiments.append(blob.sentiment.polarity)

    avg_sentiment = sum(sentiments) / len(sentiments) if sentiments else 0
    # Map -1..1 to 0..100
    sentiment_score = min(100, max(0, (avg_sentiment + 1) * 50))
    components["avg_sentiment"] = f"{avg_sentiment:+.2f}"
    scores_list.append(("sentiment", sentiment_score, 0.25))

    # --- Mention acceleration (recent vs older half of window) ---
    accel_score = 50
    mid_date = cutoff + timedelta(days=config.REDDIT_LOOKBACK_DAYS / 2)
    recent = [p for p in all_posts if p["created"] >= mid_date]
    older = [p for p in all_posts if p["created"] < mid_date]
    if older:
        accel = len(recent) / max(1, len(older))
        accel_score = min(100, accel * 50)  # 2x acceleration = 100
        components["acceleration"] = f"{accel:.1f}x"
    elif recent:
        accel_score = 80
        components["acceleration"] = "New attention"
    scores_list.append(("acceleration", accel_score, 0.25))

    # --- Subreddit diversity ---
    diversity = len(subreddits_with_mentions)
    diversity_score = min(100, diversity * 25)  # 4+ subreddits = max
    components["subreddits"] = diversity
    scores_list.append(("diversity", diversity_score, 0.25))

    total = sum(s * w for _, s, w in scores_list)

    return {
        "score": round(total, 1),
        "components": components,
        "details": ", ".join(f"{k}: {v}" for k, v in components.items()),
    }
