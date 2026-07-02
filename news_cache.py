"""Shared per-ticker news cache + headline classification.

One yfinance news fetch per ticker per scan cycle (25-min TTL), consumed by
three independent readers:
  • news_sentiment (tone scoring)
  • catalysts (shadow event classifier — zero composite weight until promoted)
  • conviction's dilution veto (via api's news_flags)

Classification uses ONLY headlines with a real parsed timestamp within the
last 7 days — undated items are ignored (yfinance recycles stale stories).
"""

import logging
import threading
import time
from datetime import datetime, timedelta

logger = logging.getLogger("discovery")

TTL_SECONDS = 25 * 60
FRESH_DAYS = 7

_cache: dict = {}   # ticker -> (monotonic_ts, items)
_lock = threading.Lock()

# TextBlob reads "offering" as positive; these are mechanically dilutive/negative
DILUTIVE_TERMS = ("offering", "registered direct", "at-the-market", "atm program",
                  "warrant inducement", "reverse split", "going concern",
                  "shelf registration", "chapter 11")
# ...unless the headline says the raise is DONE (the overhang is behind, not ahead)
COMPLETION_TERMS = ("closes", "closing of", "completed", "completion of")

POSITIVE_TERMS = ("fda approval", "pdufa", "510(k)", "clearance",
                  "breakthrough designation", "fast track", "orphan drug",
                  "contract award", "purchase order", "partnership", "uplist",
                  "patent granted", "patent issued", "topline", "phase 3 met",
                  "raises guidance")


def get_news(ticker: str) -> list:
    """[{title, summary, pub_time(datetime|None)}] — cached, never raises."""
    now = time.monotonic()
    with _lock:
        entry = _cache.get(ticker)
    if entry and now - entry[0] < TTL_SECONDS:
        return entry[1]
    items = []
    try:
        import yfinance as yf
        for item in (yf.Ticker(ticker).news or [])[:30]:
            content = item.get("content") or item
            title = content.get("title", "") or item.get("title", "") or ""
            summary = (content.get("summary", "") or content.get("description", "")
                       or item.get("summary", "") or "")
            publisher = (content.get("publisher", {}).get("name")
                         if isinstance(content.get("publisher"), dict)
                         else item.get("publisher"))
            pub_time = None
            if "pubDate" in content:
                try:
                    pub_time = datetime.fromisoformat(
                        content["pubDate"].replace("Z", "+00:00")).replace(tzinfo=None)
                except Exception:
                    pass
            if not pub_time and "providerPublishTime" in item:
                try:
                    pub_time = datetime.fromtimestamp(item["providerPublishTime"])
                except Exception:
                    pass
            items.append({"title": title, "summary": summary,
                          "publisher": publisher, "pub_time": pub_time})
    except Exception:
        items = entry[1] if entry else []
    with _lock:
        _cache[ticker] = (now, items)
    return items


def _fresh_titles(ticker: str, days: int = FRESH_DAYS) -> list:
    cutoff = datetime.now() - timedelta(days=days)
    return [i["title"].lower() for i in get_news(ticker)
            if i.get("pub_time") and i["pub_time"] > cutoff and i.get("title")]


def fresh_dilution_headline(ticker: str) -> str | None:
    """The first fresh (<7d, dated) dilutive headline, or None. Completion
    headlines ('closes offering') are excluded — the overhang is behind."""
    for i in get_news(ticker):
        if not i.get("pub_time") or i["pub_time"] < datetime.now() - timedelta(days=FRESH_DAYS):
            continue
        t = (i.get("title") or "").lower()
        if any(term in t for term in DILUTIVE_TERMS) \
                and not any(term in t for term in COMPLETION_TERMS):
            logger.info(f"dilution flag: {ticker} — {i['title'][:90]}")
            return i["title"][:160]
    return None


def classify_event(ticker: str) -> int:
    """Shadow catalyst-event score from fresh headlines: 90 positive-event,
    10 dilutive, 50 none. Persisted for IC measurement; carries ZERO composite
    weight until it earns promotion (IC >= +0.05 at n >= 120)."""
    titles = _fresh_titles(ticker)
    if any(any(p in t for p in POSITIVE_TERMS) for t in titles):
        return 90
    if any(any(d in t for d in DILUTIVE_TERMS) and not any(cx in t for cx in COMPLETION_TERMS)
           for t in titles):
        return 10
    return 50
