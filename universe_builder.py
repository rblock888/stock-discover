"""
Auto-discovery universe builder.
Pulls candidate tickers from multiple sources instead of a manual list.

Sources:
1. Yahoo Finance screeners (gainers, most active, trending)
2. Finviz screener (fundamentals-based filtering)
3. Reddit trending tickers (social attention)
4. SEC EDGAR recent insider buying
5. RSS feeds (SEC filings, PR Newswire, GlobeNewsWire)
6. StockTwits trending tickers
"""

import re
import time
import xml.etree.ElementTree as ET
import requests
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

import config


def _headers():
    return {"User-Agent": "Mozilla/5.0 (StockDiscovery/1.0)"}


# ---------------------------------------------------------------------------
# Source 1: Yahoo Finance pre-built screens
# ---------------------------------------------------------------------------

def _yahoo_screen(screen_id: str, max_tickers: int = 50) -> list:
    """Fetch tickers from a Yahoo Finance predefined screener."""
    try:
        from yfinance.screener import screen
        result = screen(screen_id)
        quotes = result.get("quotes", [])
        return [q["symbol"] for q in quotes if "symbol" in q][:max_tickers]
    except Exception:
        pass
    return []


def from_yahoo_gainers(max_tickers: int = 50) -> list:
    """Top daily gainers — stocks with sudden momentum."""
    # Try FMP first (works on servers), fall back to yfinance
    try:
        import fmp
        if fmp.is_configured():
            data = fmp.get_gainers()
            if data:
                return [d["symbol"] for d in data if "symbol" in d][:max_tickers]
    except Exception:
        pass
    return _yahoo_screen("day_gainers", max_tickers)


def from_yahoo_most_active(max_tickers: int = 50) -> list:
    """Most active by volume — stocks getting attention."""
    try:
        import fmp
        if fmp.is_configured():
            data = fmp.get_most_active()
            if data:
                return [d["symbol"] for d in data if "symbol" in d][:max_tickers]
    except Exception:
        pass
    return _yahoo_screen("most_actives", max_tickers)


def from_yahoo_small_cap_gainers(max_tickers: int = 50) -> list:
    """Small cap gainers — the rerating sweet spot."""
    try:
        import fmp
        if fmp.is_configured():
            data = fmp.get_stock_screener(
                market_cap_min=50_000_000,
                market_cap_max=2_000_000_000,
                volume_min=100_000,
                limit=max_tickers,
            )
            if data:
                return [d["symbol"] for d in data if "symbol" in d][:max_tickers]
    except Exception:
        pass
    return _yahoo_screen("small_cap_gainers", max_tickers)


# ---------------------------------------------------------------------------
# Source 2: Finviz screener (HTML scraping)
# ---------------------------------------------------------------------------

def from_finviz_microcap(max_tickers: int = 80) -> list:
    """
    Micro/small-cap hunter — stocks under $500M market cap with:
    - Positive revenue growth (QoQ)
    - Price under $30
    - Avg volume > 200K (liquid enough)
    - Off 52w lows but below midpoint
    The LWLG-style universe.
    """
    tickers = []
    try:
        url = "https://finviz.com/screener.ashx"
        # cap_small = $300M-2B, cap_micro = $50M-300M
        # Combine both for our sweet spot
        params = {
            "v": "111",
            "f": "cap_microover,cap_smallunder,sh_avgvol_o200,sh_price_u30,fa_salesqoq_pos,ta_sma200_pb50,ta_highlow52w_a20h",
            "ft": "4",
            "r": "1",
        }
        headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)", "Accept": "text/html"}

        for start in range(1, max_tickers + 1, 20):
            params["r"] = str(start)
            resp = requests.get(url, params=params, headers=headers, timeout=10)
            if resp.status_code != 200:
                break
            matches = re.findall(r'quote\.ashx\?t=([A-Z]{1,5})', resp.text)
            unique = []
            for m in matches:
                if m not in tickers and m not in unique:
                    unique.append(m)
            tickers.extend(unique)
            if len(unique) < 10:
                break
            time.sleep(0.5)
    except Exception:
        pass
    return list(dict.fromkeys(tickers))[:max_tickers]


def from_finviz(max_tickers: int = 100) -> list:
    """
    Scrape Finviz screener for small/mid caps with:
    - Market cap $50M-$10B
    - Average volume > 100K
    - Price $0.50-$50
    - Positive revenue growth
    """
    tickers = []
    try:
        url = "https://finviz.com/screener.ashx"
        params = {
            "v": "111",  # overview view
            "f": "cap_smallover,sh_avgvol_o100,sh_price_u50,fa_salesqoq_poslow",
            "ft": "4",   # all filters
            "r": "1",    # starting row
        }
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
            "Accept": "text/html",
        }

        for start in range(1, max_tickers, 20):
            params["r"] = str(start)
            resp = requests.get(url, params=params, headers=headers, timeout=10)
            if resp.status_code != 200:
                break

            # Extract tickers from the screener table
            matches = re.findall(
                r'<a href="quote\.ashx\?t=([A-Z]+)&ty=c[^"]*"[^>]*class="tab-link"',
                resp.text,
            )
            if not matches:
                # Try alternative pattern
                matches = re.findall(
                    r'quote\.ashx\?t=([A-Z]{1,5})',
                    resp.text,
                )
            tickers.extend(matches)
            if len(matches) < 20:
                break
            time.sleep(0.5)  # be polite

    except Exception:
        pass

    return list(dict.fromkeys(tickers))[:max_tickers]


# ---------------------------------------------------------------------------
# Source 3: Reddit trending tickers
# ---------------------------------------------------------------------------

def from_reddit(max_tickers: int = 50) -> list:
    """Pull most-mentioned tickers from Reddit finance subs."""
    if not config.REDDIT_CLIENT_ID:
        return _from_reddit_no_auth(max_tickers)

    try:
        import praw
        reddit = praw.Reddit(
            client_id=config.REDDIT_CLIENT_ID,
            client_secret=config.REDDIT_CLIENT_SECRET,
            user_agent=config.REDDIT_USER_AGENT,
        )

        ticker_counts = {}
        ticker_pattern = re.compile(r'\$([A-Z]{1,5})\b')

        for sub_name in config.REDDIT_SUBREDDITS[:4]:  # limit to avoid rate limits
            try:
                sub = reddit.subreddit(sub_name)
                for post in sub.hot(limit=50):
                    text = f"{post.title} {post.selftext}"
                    found = ticker_pattern.findall(text)
                    for t in found:
                        if len(t) >= 2:  # skip single-letter
                            ticker_counts[t] = ticker_counts.get(t, 0) + 1
            except Exception:
                continue

        # Sort by mention count, return top N
        sorted_tickers = sorted(ticker_counts.items(), key=lambda x: x[1], reverse=True)
        return [t for t, _ in sorted_tickers[:max_tickers]]

    except Exception:
        return _from_reddit_no_auth(max_tickers)


def _from_reddit_no_auth(max_tickers: int = 50) -> list:
    """Scrape Reddit trending tickers without API auth using public JSON."""
    ticker_counts = {}
    ticker_pattern = re.compile(r'\$([A-Z]{1,5})\b')

    for sub_name in ["wallstreetbets", "stocks", "pennystocks", "smallstreetbets"]:
        try:
            url = f"https://www.reddit.com/r/{sub_name}/hot.json?limit=50"
            headers = {"User-Agent": config.REDDIT_USER_AGENT}
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code != 200:
                continue

            data = resp.json()
            for child in data.get("data", {}).get("children", []):
                post = child.get("data", {})
                text = f"{post.get('title', '')} {post.get('selftext', '')}"
                found = ticker_pattern.findall(text)
                for t in found:
                    if len(t) >= 2:
                        ticker_counts[t] = ticker_counts.get(t, 0) + 1

            time.sleep(1)  # rate limit
        except Exception:
            continue

    sorted_tickers = sorted(ticker_counts.items(), key=lambda x: x[1], reverse=True)
    return [t for t, _ in sorted_tickers[:max_tickers]]


# ---------------------------------------------------------------------------
# Source 4: SEC EDGAR — recent insider purchases
# ---------------------------------------------------------------------------

def from_sec_insider_buys(max_tickers: int = 50) -> list:
    """Find tickers with recent Form 4 insider purchases from EDGAR full-text search."""
    tickers = set()
    try:
        headers = {"User-Agent": config.SEC_USER_AGENT}

        # Search for recent Form 4 filings mentioning "purchase"
        url = "https://efts.sec.gov/LATEST/search-index"
        params = {
            "q": '"Purchase" OR "Bought"',
            "forms": "4",
            "dateRange": "custom",
            "startdt": (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d"),
            "enddt": datetime.now().strftime("%Y-%m-%d"),
        }

        resp = requests.get(url, params=params, headers=headers, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            hits = data.get("hits", {}).get("hits", [])
            for hit in hits[:200]:
                source = hit.get("_source", {})
                ticker_list = source.get("tickers", [])
                for t in ticker_list:
                    if t and 1 < len(t) <= 5 and t.isalpha():
                        tickers.add(t.upper())
    except Exception:
        pass

    # Fallback: use EDGAR XBRL company search for recent filings
    if not tickers:
        try:
            url = "https://efts.sec.gov/LATEST/search-index"
            params = {
                "forms": "4",
                "dateRange": "custom",
                "startdt": (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d"),
                "enddt": datetime.now().strftime("%Y-%m-%d"),
            }
            headers = {"User-Agent": config.SEC_USER_AGENT}
            resp = requests.get(url, params=params, headers=headers, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                for hit in data.get("hits", {}).get("hits", [])[:100]:
                    source = hit.get("_source", {})
                    for t in source.get("tickers", []):
                        if t and 1 < len(t) <= 5 and t.isalpha():
                            tickers.add(t.upper())
        except Exception:
            pass

    return list(tickers)[:max_tickers]


# ---------------------------------------------------------------------------
# Source 5: Unusual volume — stocks suddenly trading heavy
# ---------------------------------------------------------------------------

def from_unusual_volume(watchlist: list = None, max_tickers: int = 30) -> list:
    """
    Scan a broad list for stocks with unusual volume today.
    If no watchlist provided, use a default broad scan.
    """
    if watchlist is None:
        # Start with a broad set of small/mid-cap ETF holdings or known names
        # In practice, this gets fed by other sources
        return []

    unusual = []

    def check_volume(ticker):
        try:
            stock = yf.Ticker(ticker)
            info = stock.info or {}
            current_vol = info.get("volume", 0) or 0
            avg_vol = info.get("averageVolume", 1) or 1
            if avg_vol > 0 and current_vol > avg_vol * 2:
                return ticker, current_vol / avg_vol
        except Exception:
            pass
        return None, 0

    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(check_volume, t): t for t in watchlist}
        for future in as_completed(futures):
            ticker, ratio = future.result()
            if ticker:
                unusual.append((ticker, ratio))

    unusual.sort(key=lambda x: x[1], reverse=True)
    return [t for t, _ in unusual[:max_tickers]]


# ---------------------------------------------------------------------------
# Source 6: RSS feeds — SEC filings, news wires, earnings
# ---------------------------------------------------------------------------

RSS_FEEDS = {
    # SEC EDGAR recent filings (all types)
    "sec_rss": "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K&dateb=&owner=include&count=100&search_text=&action=getcurrent&output=atom",
    # SEC EDGAR Form 4 (insider transactions)
    "sec_form4": "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=4&dateb=&owner=include&count=100&search_text=&action=getcurrent&output=atom",
    # PR Newswire — company press releases
    "prnewswire": "https://www.prnewswire.com/rss/financial-services-latest-news/financial-services-latest-news-list.rss",
    # GlobeNewsWire — company announcements
    "globenewswire": "https://www.globenewswire.com/RssFeed/subjectcode/25-Earnings/feedTitle/GlobeNewswire%20-%20Earnings",
    # Seeking Alpha trending
    "seekingalpha": "https://seekingalpha.com/feed.xml",
}


def _extract_tickers_from_text(text: str) -> list:
    """Extract stock tickers from text using common patterns."""
    tickers = set()
    # Match $TICKER pattern
    for m in re.finditer(r'\$([A-Z]{1,5})\b', text):
        tickers.add(m.group(1))
    # Match "TICKER" in parentheses like (NASDAQ: LWLG) or (NYSE: SOFI)
    for m in re.finditer(r'\((?:NASDAQ|NYSE|AMEX|OTC):\s*([A-Z]{1,5})\)', text):
        tickers.add(m.group(1))
    # Match standalone uppercase 2-5 letter words that look like tickers
    # (more aggressive, filtered later)
    for m in re.finditer(r'\b([A-Z]{2,5})\b', text):
        word = m.group(1)
        if word not in {"THE", "FOR", "AND", "ALL", "NEW", "CEO", "IPO", "ETF",
                        "USD", "GDP", "FBI", "SEC", "INC", "LLC", "LTD", "RSS",
                        "XML", "HTML", "HTTP", "NYSE", "AMEX", "OTC", "NASDAQ",
                        "FORM", "FROM", "WITH", "THAT", "THIS", "HAVE", "BEEN",
                        "WILL", "THEY", "WERE", "SAID", "EACH", "MAKE", "LIKE",
                        "HAS", "HER", "HIM", "HIS", "HOW", "ITS", "MAY", "NOT",
                        "NOW", "OLD", "SEE", "WAY", "WHO", "BOY", "DID", "GET",
                        "LET", "SAY", "SHE", "TOO", "USE", "DAD", "MOM"}:
            tickers.add(word)
    return list(tickers)


def from_rss_feeds(max_tickers: int = 100) -> list:
    """Pull tickers mentioned in RSS feeds from financial news and filings."""
    ticker_counts = {}
    headers = {"User-Agent": "Mozilla/5.0 (StockDiscovery/1.0)"}

    for feed_name, feed_url in RSS_FEEDS.items():
        try:
            resp = requests.get(feed_url, headers=headers, timeout=15)
            if resp.status_code != 200:
                continue

            # Parse XML/Atom feed
            root = ET.fromstring(resp.content)

            # Handle both RSS and Atom formats
            entries = []
            # Atom
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            entries.extend(root.findall(".//atom:entry", ns))
            # RSS
            entries.extend(root.findall(".//item"))
            # Fallback no namespace
            entries.extend(root.findall(".//entry"))

            for entry in entries:
                title = ""
                summary = ""
                for elem in entry:
                    tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
                    if tag == "title":
                        title = elem.text or ""
                    elif tag in ("summary", "description", "content"):
                        summary = elem.text or ""

                text = f"{title} {summary}"
                found = _extract_tickers_from_text(text)
                for t in found:
                    ticker_counts[t] = ticker_counts.get(t, 0) + 1

            time.sleep(0.5)
        except Exception:
            continue

    # Sort by frequency
    sorted_tickers = sorted(ticker_counts.items(), key=lambda x: x[1], reverse=True)
    return [t for t, _ in sorted_tickers[:max_tickers]]


# ---------------------------------------------------------------------------
# Source 7: StockTwits trending tickers
# ---------------------------------------------------------------------------

def from_stocktwits(max_tickers: int = 30) -> list:
    """Get trending tickers from StockTwits."""
    try:
        import stocktwits
        return stocktwits.get_trending()[:max_tickers]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Main: combine all sources into a deduplicated universe
# ---------------------------------------------------------------------------

def build_universe(
    use_yahoo: bool = True,
    use_finviz: bool = True,
    use_reddit: bool = True,
    use_sec: bool = True,
    use_rss: bool = True,
    callback=None,
) -> dict:
    """
    Build the discovery universe from all sources.
    Returns dict with source breakdown and combined list.
    """
    sources = {}

    def log(msg):
        if callback:
            callback(msg)
        else:
            print(msg)

    # Run sources in parallel
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {}

        if use_yahoo:
            futures[pool.submit(from_yahoo_gainers)] = "yahoo_gainers"
            futures[pool.submit(from_yahoo_most_active)] = "yahoo_active"
            futures[pool.submit(from_yahoo_small_cap_gainers)] = "yahoo_smallcap"

        if use_finviz:
            futures[pool.submit(from_finviz)] = "finviz"
            futures[pool.submit(from_finviz_microcap)] = "finviz_microcap"

        if use_reddit:
            futures[pool.submit(from_reddit)] = "reddit"

        if use_sec:
            futures[pool.submit(from_sec_insider_buys)] = "sec_insiders"

        if use_rss:
            futures[pool.submit(from_rss_feeds)] = "rss_feeds"


        for future in as_completed(futures):
            source_name = futures[future]
            try:
                tickers = future.result()
                sources[source_name] = tickers
                log(f"  {source_name}: {len(tickers)} tickers")
            except Exception as e:
                sources[source_name] = []
                log(f"  {source_name}: failed ({e})")

    # Combine and deduplicate
    all_tickers = []
    seen = set()
    # Track how many sources mention each ticker
    ticker_source_count = {}

    for source_name, tickers in sources.items():
        for t in tickers:
            t = t.upper()
            if t not in seen:
                all_tickers.append(t)
                seen.add(t)
            ticker_source_count[t] = ticker_source_count.get(t, 0) + 1

    # Sort by number of sources (multi-source = more interesting)
    all_tickers.sort(key=lambda t: ticker_source_count.get(t, 0), reverse=True)

    # Filter to valid-looking tickers
    all_tickers = [
        t for t in all_tickers
        if 1 < len(t) <= 5 and t.isalpha() and t not in {"THE", "FOR", "AND", "ALL", "NEW", "CEO", "IPO", "ETF", "USD", "GDP", "FBI", "SEC"}
    ]

    return {
        "tickers": all_tickers,
        "sources": sources,
        "source_counts": ticker_source_count,
        "total": len(all_tickers),
    }
