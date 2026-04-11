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


def _score_reddit_public(ticker: str) -> dict:
    """Score sentiment using Reddit public JSON (no auth needed)."""
    import requests as req

    components = {}
    all_posts = []
    subreddits_found = set()
    headers = {"User-Agent": config.REDDIT_USER_AGENT}

    for sub_name in config.REDDIT_SUBREDDITS[:4]:
        try:
            url = f"https://www.reddit.com/r/{sub_name}/search.json"
            params = {"q": ticker, "sort": "new", "t": "month", "limit": 25}
            resp = req.get(url, params=params, headers=headers, timeout=10)
            if resp.status_code != 200:
                continue
            data = resp.json()
            for child in data.get("data", {}).get("children", []):
                post = child.get("data", {})
                title = post.get("title", "")
                text = post.get("selftext", "")[:500]
                if ticker.upper() in f"{title} {text}".upper():
                    all_posts.append({"title": title, "text": text, "score": post.get("score", 0)})
                    subreddits_found.add(sub_name)
            time.sleep(1)
        except Exception:
            continue

    if not all_posts:
        return {"score": 30, "details": "No Reddit mentions", "components": {"mentions": 0}}

    # Mention count
    mention_score = min(100, len(all_posts) * 5)
    components["mentions"] = len(all_posts)

    # Basic sentiment from TextBlob
    sentiments = []
    for p in all_posts:
        blob = TextBlob(f"{p['title']} {p['text']}")
        sentiments.append(blob.sentiment.polarity)
    avg = sum(sentiments) / len(sentiments) if sentiments else 0
    sentiment_score = min(100, max(0, (avg + 1) * 50))
    components["sentiment"] = f"{avg:+.2f}"

    # Diversity
    diversity_score = min(100, len(subreddits_found) * 25)
    components["subreddits"] = len(subreddits_found)

    total = mention_score * 0.4 + sentiment_score * 0.35 + diversity_score * 0.25

    return {
        "score": round(total, 1),
        "components": components,
        "details": ", ".join(f"{k}: {v}" for k, v in components.items()),
    }


def score(ticker: str) -> dict:
    """Return a sentiment score (0-100) and details."""
    reddit = _get_reddit()
    if reddit is None:
        # Fall back to Reddit public JSON (no auth needed)
        return _score_reddit_public(ticker)

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
