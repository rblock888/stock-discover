"""News sentiment v2 — TONE ONLY (cutover 2026-07-02).

v1 blended tone (35%) with volume/acceleration/diversity (65%) and measured
IC −0.19: coverage VOLUME peaks marked tops, poisoning the whole bucket. v2
scores tone alone; volume/accel/diversity remain in components for DISPLAY
and the attention count persists separately so its (suspected negative) IC
can be measured on its own.

Hard-negative override: TextBlob reads "announces public offering" as
POSITIVE ("offering" scores well). Any fresh dilutive headline caps the tone
score at 35.

Weight stays at the 0.05 floor until post-cutover tone IC >= +0.05 at
n >= 120 resolved returns; if it reads <= 0 at that n, it stays floored
permanently — never inverted.
"""

from datetime import datetime, timedelta
from textblob import TextBlob

import news_cache

SENTIMENT_VERSION = 2


def score(ticker: str) -> dict:
    """Return news tone score (0-100). Never raises."""
    items = news_cache.get_news(ticker)
    if not items:
        return {"score": 50, "details": "News unavailable", "components": {}}

    now = datetime.now()
    cutoff_recent = now - timedelta(days=14)
    cutoff_older = now - timedelta(days=45)

    sentiments = []
    n_recent = n_older = n_dated_recent = 0
    publishers = set()

    for it in items:
        pub_time = it.get("pub_time")
        dated = pub_time is not None
        if not pub_time:
            pub_time = now - timedelta(days=7)   # undated: display buckets only
        if pub_time <= cutoff_older:
            continue
        if pub_time > cutoff_recent:
            n_recent += 1
            if dated:
                n_dated_recent += 1
        else:
            n_older += 1
        if it.get("publisher"):
            publishers.add(it["publisher"])
        text = f"{it.get('title', '')} {(it.get('summary') or '')[:200]}"
        if text.strip():
            sentiments.append(TextBlob(text).sentiment.polarity)

    if n_recent + n_older == 0:
        return {"score": 40, "details": "No recent news", "components": {"articles": 0}}

    # ── the score: tone only ──
    if sentiments:
        avg = sum(sentiments) / len(sentiments)
        tone = max(0.0, min(100.0, (avg + 1) * 50))
    else:
        avg, tone = 0.0, 50.0

    # dilution override — a fresh offering/reverse-split headline is not "positive"
    # no matter how cheerful the press release reads
    diluted = news_cache.fresh_dilution_headline(ticker)
    if diluted:
        tone = min(tone, 35.0)

    components = {
        "tone": f"{avg:+.2f}",
        "articles": n_recent + n_older,                       # display only (v1 legacy)
        "trend": f"{n_recent / max(1, n_older):.1f}x" if n_older else "new",
        "publishers": len(publishers),
        "attention": min(100, n_dated_recent * 10),           # persisted, measured separately
        "ver": SENTIMENT_VERSION,
    }
    if diluted:
        components["dilution_capped"] = True

    return {
        "score": round(tone, 1),
        "components": components,
        "details": ", ".join(f"{k}: {v}" for k, v in components.items()
                             if k not in ("attention", "ver")),
    }
