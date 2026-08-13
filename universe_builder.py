"""
Auto-discovery universe builder.
Pulls candidate tickers from multiple sources instead of a manual list.

Sources:
1. Yahoo Finance screeners (gainers, most active, small-cap)
2. Finviz screens (growth, microcap, basing, biotech)
3. Reddit trending tickers (social attention)
4. SEC EDGAR insider buying (Form 4 API) + fresh 8-K filers (CIK-mapped)
5. News RSS feeds (PR Newswire + health vertical, GlobeNewswire earnings/
   FDA/clinical verticals, Seeking Alpha)
6. extra_sources: siloed engines (squeeze screen, photonics seeds) merged
   through the same validate/rerank funnel

Everything funnels through: junk-ticker stoplist -> price validation -> the
pre-fly rerank (attention 0.30 / coiled-technical 0.70, source-weighted).
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


# Common 2-5 letter uppercase words that are NOT tickers — text scraping (RSS,
# Reddit, SEC filings) otherwise turns these into phantom "stocks" (the audit
# found ~62% of scored symbols were junk like FDA / GPU / CLASS / PCAOB).
STOPWORDS = frozenset({
    # agencies / regulators / orgs
    "FDA", "SEC", "FBI", "IRS", "DOJ", "FTC", "EPA", "CDC", "WHO", "FAA", "NASA",
    "NATO", "FOMC", "ECB", "IMF", "OPEC", "PCAOB", "FINRA", "GAAP", "NCAA", "NFL",
    "NBA", "MLB", "UN", "EU", "UK", "US", "USA", "USD", "EUR", "GBP", "JPY", "CNY",
    # exchanges / market terms
    "NYSE", "NASDAQ", "AMEX", "OTC", "OTCQB", "OTCQX", "TSX", "LSE", "ETF", "ETN",
    "SPAC", "REIT", "IPO", "ADR", "NAV", "AUM",
    # finance jargon / metrics
    "CEO", "CFO", "COO", "CTO", "CIO", "EPS", "ROE", "ROI", "ROA", "YOY", "QOQ",
    "GDP", "CPI", "PCE", "EBIT", "EBITDA", "ESG", "MOU", "LOI", "NDA", "SaaS",
    "Q1", "Q2", "Q3", "Q4", "FY", "YTD", "TTM", "EOD", "PRE", "PR", "IR",
    # tech / units / misc acronyms
    "AI", "ML", "EV", "VR", "AR", "API", "SDK", "URL", "PDF", "USB", "GPU", "CPU",
    "RAM", "SSD", "OS", "IOS", "APP", "WEB", "HTML", "HTTP", "HTTPS", "XML", "RSS",
    "FAQ", "CEO", "MDMA", "GLOBE", "BLACK", "CLASS", "ALERT", "YORK", "MENA",
    # biotech/regulatory acronyms — the FDA/clinical vertical feeds are full of these
    "NDA", "BLA", "IND", "ANDA", "CRL", "PDUFA", "DSMB", "CHMP", "EMA", "MHRA",
    "ODD", "SPA", "ORR", "PFS", "EUA", "HHS", "NIH", "CMS", "ASCO", "ESMO",
    "AACR", "NSCLC",
    # org suffixes
    "INC", "LLC", "LTD", "CORP", "PLC", "LP", "LLP", "CO", "AG", "SA", "NV",
    # common English words the regex catches
    "THE", "FOR", "AND", "ALL", "NEW", "FORM", "FROM", "WITH", "THAT", "THIS",
    "HAVE", "BEEN", "WILL", "THEY", "WERE", "SAID", "EACH", "MAKE", "LIKE", "MORE",
    "MOST", "OVER", "SOME", "TIME", "ONLY", "JUST", "ALSO", "INTO", "THAN", "THEN",
    "THEM", "WHAT", "WHEN", "YOUR", "ABLE", "BACK", "CALL", "CAME", "DOWN", "EVEN",
    "GOOD", "HERE", "HIGH", "KEEP", "KNOW", "LAST", "LONG", "MANY", "MUST", "NEXT",
    "PART", "TAKE", "TELL", "VERY", "WANT", "WEEK", "WELL", "WENT", "YEAR", "DAYS",
    "HAS", "HER", "HIM", "HIS", "HOW", "ITS", "MAY", "NOT", "NOW", "OLD", "SEE",
    "WAY", "WHO", "BOY", "DID", "GET", "LET", "SAY", "SHE", "TOO", "USE", "DAD",
    "MOM", "CAN", "OUR", "OUT", "DAY", "TWO", "ONE", "BIG", "TOP", "END", "RUN",
})


def _looks_like_ticker(t: str) -> bool:
    return bool(t) and 1 < len(t) <= 5 and t.isalpha() and t.upper() not in STOPWORDS


def _validate_with_prices(candidates: list, limit: int = 90) -> list:
    """Ground-truth filter: keep only candidates that resolve to real price data.

    One batched yfinance download — junk symbols return nothing and are dropped.
    Bounded to the top `limit` candidates (only the top ~40 are ever scored).
    """
    head = candidates[:limit]
    if not head:
        return candidates
    try:
        import price_history
        resolved = price_history.get_histories(head, period="1mo")
        valid = [t for t in head if t in resolved and resolved[t] is not None and len(resolved[t]) > 0]
        # Keep the validated head (order preserved) + the untouched tail
        return valid + candidates[limit:]
    except Exception:
        return candidates


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
            "o": "-volume",   # without an explicit sort Finviz defaults to ticker-
                              # alphabetical, which silently locks the universe to
                              # A/B-name tickers once paginated results are capped
            "r": "1",
        }
        headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)", "Accept": "text/html"}

        for start in range(1, max_tickers + 1, 20):
            params["r"] = str(start)
            resp = requests.get(url, params=params, headers=headers, timeout=10)
            if resp.status_code != 200:
                break
            # Finviz moved from quote.ashx?t= to stock?t= links (2026) — match both
            matches = re.findall(r'(?:quote\.ashx|stock)\?t=([A-Z]{1,5})', resp.text)
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


def from_finviz_basing(max_tickers: int = 60) -> list:
    """
    Quiet-base hunter — the opposite bias from gainers/most-active. Targets
    names sitting ABOVE their 20/50-day average (not a downtrend) but well OFF
    their 52-week high (not extended) — the coiling-before-the-move zone that
    momentum screens structurally can't see (a basing stock isn't moving yet,
    so it never shows up in "day gainers" or "most active").
    """
    tickers = []
    try:
        url = "https://finviz.com/screener.ashx"
        params = {
            "v": "111",
            # cap_microover + cap_smallunder bounds this to micro-to-small cap (matches
            # from_finviz_microcap's proven pattern) — cap_smallover alone has NO upper
            # bound and would flood the basing scan with mega-cap ADRs (Novo Nordisk,
            # UBS, CSX...) that happen to look "calm" simply because they're huge.
            "f": "cap_microover,cap_smallunder,sh_avgvol_o100,sh_price_u50,ta_sma20_pa,ta_sma50_pa,ta_highlow52w_b30to50",
            "ft": "4",
            "o": "-marketcap",
            "r": "1",
        }
        headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)", "Accept": "text/html"}

        for start in range(1, max_tickers + 1, 20):
            params["r"] = str(start)
            resp = requests.get(url, params=params, headers=headers, timeout=10)
            if resp.status_code != 200:
                break
            matches = re.findall(r'(?:quote\.ashx|stock)\?t=([A-Z]{1,5})', resp.text)
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


# cap_mid is $2-10B EXACTLY. Deliberately not cap_midover, which has no ceiling
# and returned 819 names — every mega cap in an uptrend, an index not a
# watchlist. Module-level so the bound is assertable without scraping source.
LEADER_FILTERS = ("cap_mid,sh_avgvol_o400,sh_price_o10,"
                  "ta_sma20_pa,ta_sma50_pa,ta_sma200_pa,ta_highlow52w_b0to30")


def from_finviz_leader(max_tickers: int = 60) -> list:
    """Leader-continuation lane — established $2-10B names in a real uptrend.

    A SEPARATE lane, deliberately not a widening of the microcap screens. The
    existing lanes hard-cap at cap_smallunder ($2B) and sh_price_u50, which is
    why a $57 / $2.7B name could never appear no matter how clean its setup was.
    Loosening those caps in place would have flooded momentum.py, day_movers.py
    and oversold.py with large caps and contaminated ICs that have been accruing
    since July. Keeping it as its own source means the two populations stay
    separately taggable and separately measurable.

    Bounded ABOVE as well as below: cap_mid is $2-10B exactly. cap_midover has no
    ceiling and returned 819 names — essentially every mega cap in an uptrend
    (NVDA, MSFT, BRK, JPM), which is an index, not a watchlist.

    The pattern is continuation, not reversal: above the 20/50/200-day averages
    (an established trend, unlike the basing lane's off-the-high bias) and within
    30% of the 52-week high. Verified live that COHU — the name that prompted
    this lane — passes every clause.
    """
    tickers = []
    try:
        url = "https://finviz.com/screener.ashx"
        params = {
            "v": "111",
            "f": LEADER_FILTERS,
            "ft": "4",
            # This screen returns ~389 names and we take ~80, so WHICH 80 matters.
            # Sorting does not cure truncation — it decides what the truncation
            # selects. Unsorted, Finviz returns ticker-alphabetical and the cap
            # would silently mean "leaders whose ticker starts with A", the same
            # defect that hid in squeeze_discovery for years.
            #
            # -perf26w = strongest 6-month performers, which is what "leader"
            # actually means (relative-strength leadership, not merely liquidity).
            # Verified to be honoured; -relativestrength is NOT — Finviz silently
            # falls back to reverse-ticker order for tokens it does not recognise,
            # so an unverified sort token is indistinguishable from no sort.
            #
            # Known tension, deliberately accepted: ranking by past performance
            # biases toward names that have already moved, which is the opposite
            # of this app's usual catch-it-early bias. That is the point of a
            # CONTINUATION lane — and parabolic.py's base test and chase limit
            # are what decide whether any given one is still entrable or already
            # extended, rather than this screen pretending to know.
            "o": "-perf26w",
            "r": "1",
        }
        headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
                   "Accept": "text/html"}
        for start in range(1, max_tickers + 1, 20):
            params["r"] = str(start)
            resp = requests.get(url, params=params, headers=headers, timeout=10)
            if resp.status_code != 200:
                break
            on_page = list(dict.fromkeys(
                re.findall(r'(?:quote\.ashx|stock)\?t=([A-Z]{1,5})', resp.text)))
            fresh = [t for t in on_page if t not in tickers]
            tickers.extend(fresh)
            if len(on_page) < 20 or not fresh:
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
            "o": "-change",  # diversify vs the other finviz sources' sort keys —
                             # else all three default to ticker-alphabetical and
                             # only ever surface A/B-name tickers once paginated
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
            # (Finviz moved from quote.ashx?t= to stock?t= links in 2026 — match both)
            matches = re.findall(
                r'<a href="(?:quote\.ashx|stock)\?t=([A-Z]+)&ty=c[^"]*"[^>]*class="tab-link"',
                resp.text,
            )
            if not matches:
                # Try alternative pattern
                matches = re.findall(
                    r'(?:quote\.ashx|stock)\?t=([A-Z]{1,5})',
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

_CIK_TICKER_MAP = None
_CIK_MAP_TS = 0.0
_CIK_MAP_TTL = 24 * 3600   # refresh daily — new listings/ticker changes appear


def _load_cik_to_ticker_map() -> dict:
    """Load SEC CIK→ticker mapping, cached with a 24h TTL."""
    global _CIK_TICKER_MAP, _CIK_MAP_TS
    if _CIK_TICKER_MAP and time.monotonic() - _CIK_MAP_TS < _CIK_MAP_TTL:
        return _CIK_TICKER_MAP
    try:
        headers = {"User-Agent": config.SEC_USER_AGENT}
        resp = requests.get(
            "https://www.sec.gov/files/company_tickers.json",
            headers=headers, timeout=15
        )
        if resp.status_code == 200:
            data = resp.json()
            # Build CIK → ticker (pad CIK to 10 digits)
            _CIK_TICKER_MAP = {
                str(v["cik_str"]).zfill(10): v["ticker"]
                for v in data.values()
            }
            _CIK_MAP_TS = time.monotonic()
            return _CIK_TICKER_MAP
    except Exception:
        pass
    return _CIK_TICKER_MAP or {}


# 8-K items worth a discovery slot: material agreements (1.01), acquisitions
# (2.01), results (2.02), leadership (5.02), reg-FD (7.01), other events (8.01).
# A LONE 3.02 (unregistered equity sale) is dilution paperwork, not a catalyst.
SEC_8K_ITEMS = {"1.01", "2.01", "2.02", "5.02", "7.01", "8.01"}


def from_sec_8k(max_tickers: int = 40) -> list:
    """Fresh 8-K filers, CIK-mapped to tickers — NO text scraping.

    The old path ran the generic ticker-regex over SEC filing text (67-74%
    junk); the atom title carries the filer's CIK '(0001234567)' which maps
    exactly via the official company_tickers.json (live-tested: 88/100
    resolvable). Item codes are parsed from the summary and filtered to the
    catalyst-relevant set."""
    cik_map = _load_cik_to_ticker_map()
    if not cik_map:
        return []
    tickers = []
    try:
        url = ("https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent"
               "&type=8-K&dateb=&owner=include&count=100&output=atom")
        # SEC throttles aggressively — generous timeout; one fetch per scan cycle
        resp = requests.get(url, headers={"User-Agent": config.SEC_USER_AGENT}, timeout=25)
        if resp.status_code != 200:
            return []
        root = ET.fromstring(resp.content)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        for entry in root.findall(".//atom:entry", ns):
            title_el = entry.find("atom:title", ns)
            summary_el = entry.find("atom:summary", ns)
            title = title_el.text if title_el is not None else ""
            summary = (summary_el.text if summary_el is not None else "") or ""
            m = re.search(r"\((\d{10})\)", title or "")
            if not m:
                continue
            t = cik_map.get(m.group(1))
            if not t or len(t) > 5 or not t.isalpha():
                continue
            if len(t) == 5 and t.endswith("W"):
                continue   # warrant class (SOARW/TNONW...), not the common stock
            items = set(re.findall(r"\d+\.\d+", summary))
            if not (items & SEC_8K_ITEMS):
                continue
            if items == {"3.02"} or items <= {"3.02", "9.01"}:
                continue   # lone unregistered-sale filing = dilution, skip
            t = t.upper()
            if t not in tickers:
                tickers.append(t)
            if len(tickers) >= max_tickers:
                break
    except Exception:
        pass
    return tickers


def from_sec_insider_buys(max_tickers: int = 50) -> list:
    """Find tickers with recent Form 4 insider filings from EDGAR."""
    cik_map = _load_cik_to_ticker_map()
    if not cik_map:
        return []

    tickers = []
    ticker_counts = {}
    try:
        headers = {"User-Agent": config.SEC_USER_AGENT}
        url = "https://efts.sec.gov/LATEST/search-index"
        params = {
            "forms": "4",
            "dateRange": "custom",
            "startdt": (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d"),
            "enddt": datetime.now().strftime("%Y-%m-%d"),
        }

        resp = requests.get(url, params=params, headers=headers, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            hits = data.get("hits", {}).get("hits", [])
            for hit in hits[:300]:
                src = hit.get("_source", {})
                for cik in src.get("ciks", []):
                    cik_padded = str(cik).zfill(10)
                    ticker = cik_map.get(cik_padded)
                    if ticker and len(ticker) <= 5 and ticker.isalpha():
                        ticker_counts[ticker] = ticker_counts.get(ticker, 0) + 1
    except Exception:
        pass

    # Return tickers with 2+ filings (higher signal = more insider activity)
    sorted_t = sorted(ticker_counts.items(), key=lambda x: x[1], reverse=True)
    tickers = [t for t, count in sorted_t if count >= 1]
    return tickers[:max_tickers]

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

# Text-scraped news feeds. SEC feeds are deliberately ABSENT: 8-Ks are handled
# by from_sec_8k() with exact CIK->ticker mapping (text-scraping SEC filings
# resolved 26-74% junk), and Form 4 duplicates from_sec_insider_buys.
RSS_FEEDS = {
    # PR Newswire — company press releases
    "prnewswire": "https://www.prnewswire.com/rss/financial-services-latest-news/financial-services-latest-news-list.rss",
    # PR Newswire — health/biotech vertical (the user's core universe)
    "prn_health": "https://www.prnewswire.com/rss/health-latest-news/health-latest-news-list.rss",
    # GlobeNewsWire verticals — earnings, FDA/regulatory, clinical trials
    "globenewswire": "https://www.globenewswire.com/RssFeed/subjectcode/25-Earnings/feedTitle/GlobeNewswire%20-%20Earnings",
    "gnw_fda": "https://www.globenewswire.com/RssFeed/subjectcode/27-FDA%20Approvals/feedTitle/GlobeNewswire%20-%20FDA",
    "gnw_clinical": "https://www.globenewswire.com/RssFeed/subjectcode/22-Clinical%20Study/feedTitle/GlobeNewswire%20-%20Clinical",
    # Seeking Alpha trending
    "seekingalpha": "https://seekingalpha.com/feed.xml",
}
RSS_PER_FEED_CAP = 25   # cap BEFORE the global merge so one firehose feed can't dominate

# ticker -> the vertical feed that first surfaced it this build (persisted per
# snapshot so per-feed forward-return ICs can be measured before any bonus)
_feed_hints: dict = {}


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
    # (aggressive — relies on STOPWORDS + price validation downstream)
    for m in re.finditer(r'\b([A-Z]{2,5})\b', text):
        word = m.group(1)
        if word not in STOPWORDS:
            tickers.add(word)
    return list(tickers)


def from_rss_feeds(max_tickers: int = 100) -> list:
    """Pull tickers mentioned in news RSS feeds. Each feed is capped at
    RSS_PER_FEED_CAP before merging; vertical feeds record a feed_hint per
    ticker (persisted downstream for per-feed IC measurement)."""
    global _feed_hints
    _feed_hints = {}
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

            feed_found = []
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
                for t in _extract_tickers_from_text(text):
                    if t not in feed_found:
                        feed_found.append(t)
            for t in feed_found[:RSS_PER_FEED_CAP]:
                ticker_counts[t] = ticker_counts.get(t, 0) + 1
                if feed_name in ("prn_health", "gnw_fda", "gnw_clinical"):
                    _feed_hints.setdefault(t, feed_name)

            time.sleep(0.5)
        except Exception:
            continue

    # Sort by frequency
    sorted_tickers = sorted(ticker_counts.items(), key=lambda x: x[1], reverse=True)
    return [t for t, _ in sorted_tickers[:max_tickers]]


# ---------------------------------------------------------------------------
# Source 7: Finviz biotech screen (the user's core universe, structure-gated)
# ---------------------------------------------------------------------------

def from_finviz_biotech(max_tickers: int = 30) -> list:
    """Micro/small-cap biotech above its 50-day — the niche the generic screens
    dilute away. Liquidity + price floors keep untradeable shells out."""
    tickers = []
    try:
        url = "https://finviz.com/screener.ashx"
        params = {
            "v": "111",
            "f": "ind_biotechnology,cap_microover,cap_smallunder,sh_avgvol_o100,sh_price_o1,ta_sma50_pa",
            "ft": "4",
            "o": "-volume",
            "r": "1",
        }
        headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)", "Accept": "text/html"}
        for start in (1, 21):   # 2 pages
            params["r"] = str(start)
            resp = requests.get(url, params=params, headers=headers, timeout=10)
            if resp.status_code != 200:
                break
            matches = re.findall(r'(?:quote\.ashx|stock)\?t=([A-Z]{1,5})', resp.text)
            for m in matches:
                if m not in tickers:
                    tickers.append(m)
            time.sleep(0.5)
    except Exception:
        pass
    return tickers[:max_tickers]


# ---------------------------------------------------------------------------
# Pre-fly re-rank — bias the scored top-N toward BASING/COILED, not just attention
# ---------------------------------------------------------------------------

# how strongly each pre-breakout state should compete for a scoring slot —
# COILED/BASING (the pre-fly setups) score highest; BREAKING is already moving
# (momentum sources already surface these); EXTENDED is actively de-prioritized
# (that's the "already flew" chart this whole engine exists to avoid chasing)
_PREFLY_STATE_WEIGHT = {
    "COILED": 1.00, "BASING": 0.80, "NO SETUP": 0.35, "BREAKING": 0.55, "EXTENDED": 0.05,
}


# how much a mention from each source is worth in the attention term — insider
# buying and the basing screen are deliberate signals; gainers/active/rss are
# attention echoes of moves that already happened
_SOURCE_WEIGHT = {
    "sec_insiders": 1.5, "finviz_basing": 1.5, "sec_8k": 1.25,
    "finviz": 1.0, "finviz_microcap": 1.0, "finviz_biotech": 1.0,
    "squeeze_screen": 1.0, "photonics_seeds": 1.0,
    "yahoo_smallcap": 0.75,
    "yahoo_gainers": 0.5, "yahoo_active": 0.5, "reddit": 0.5, "rss_feeds": 0.5,
}


def _prefly_rerank(tickers: list, source_counts: dict, limit: int = 130,
                   sources: dict = None) -> tuple:
    """Re-rank discovery candidates so a quiet, coiling microcap that only one
    source mentions can out-rank a hyped, already-extended gainer for a scoring
    slot. Attention (source-weighted mention count, 0.30) blends with a real
    technical pre-fly read (0.70) from the coiled-spring detector.

    Returns (reranked_tickers, meta) where meta[ticker] carries the components
    (persisted per snapshot so the blend itself can be IC-measured later).
    Never raises; on failure returns (input order, {}).
    """
    head = tickers[:limit]
    if not head:
        return tickers, {}
    try:
        import price_history
        import pre_breakout
        histories = price_history.get_histories(head, period="1y")
    except Exception:
        return tickers, {}

    # source-weighted attention per ticker
    by_source = sources or {}
    weighted = {}
    for src, tks in by_source.items():
        w = _SOURCE_WEIGHT.get(src, 0.75)
        for t in tks:
            weighted[t.upper()] = weighted.get(t.upper(), 0.0) + w
    if not weighted:   # fallback to raw counts
        weighted = {t: float(source_counts.get(t, 1)) for t in head}
    max_w = max(weighted.values()) if weighted else 1.0

    scored, meta = [], {}
    for t in head:
        attention = weighted.get(t, 0.5) / max_w  # 0..1
        prefly = 0.0
        state = None
        hist = histories.get(t)
        if hist is not None and len(hist) >= 120:
            try:
                cb = pre_breakout.compute(t, hist)
                if cb.get("available"):
                    state = cb.get("state")
                    weight = _PREFLY_STATE_WEIGHT.get(state, 0.3)
                    prefly = (cb.get("coiled_score", 0) / 100.0) * weight
            except Exception:
                prefly = 0.0
        elif hist is not None and 60 <= len(hist) < 120:
            # recent-IPO fallback (biotechs listed <6mo scored prefly=0 before):
            # a cheap 20-bar tightness read, capped so it can't outrank real coils
            try:
                import numpy as _np
                c = float(hist["Close"].iloc[-1])
                rng20 = (float(hist["High"].tail(20).max()) - float(hist["Low"].tail(20).min())) / c
                prefly = min(0.30, max(0.0, (0.35 - rng20)))
                state = "SHORT_HISTORY"
            except Exception:
                prefly = 0.0
        blend = 0.30 * attention + 0.70 * prefly
        scored.append((t, blend))
        meta[t] = {"attention": round(attention, 3), "prefly": round(prefly, 3),
                   "state": state, "n_sources": int(source_counts.get(t, 1))}

    scored.sort(key=lambda x: -x[1])
    reranked = [t for t, _ in scored]

    # catalyst safety valve: a name >=3 raw sources are ALL shouting about is
    # news-hot regardless of chart shape — force the top 5 such names into the
    # scored window if the blend pushed them out
    hot = sorted([t for t in head if source_counts.get(t, 0) >= 3],
                 key=lambda t: -source_counts.get(t, 0))[:5]
    for t in hot:
        if t in reranked and reranked.index(t) >= 39:
            reranked.remove(t)
            reranked.insert(38, t)
            meta[t]["safety_valve"] = True

    for rank, t in enumerate(reranked):
        if t in meta:
            meta[t]["rank"] = rank

    seen = set(head)
    tail = [t for t in tickers if t not in seen]
    return reranked + tail, meta


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
    extra_sources: dict = None,
) -> dict:
    """
    Build the discovery universe from all sources.
    Returns dict with source breakdown, combined list, and per-ticker discovery
    metadata (rerank components + vertical-feed hints, persisted per snapshot).

    extra_sources: {name: [tickers]} — siloed engines (squeeze screen, photonics
    seeds) merged through the SAME validate/rerank funnel as everything else.
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
            futures[pool.submit(from_finviz_basing)] = "finviz_basing"
            futures[pool.submit(from_finviz_biotech)] = "finviz_biotech"
            # separate lane, its own source name — so leader names stay taggable
            # and their ICs can be measured apart from the microcap population
            futures[pool.submit(from_finviz_leader)] = "finviz_leader"

        if use_reddit:
            futures[pool.submit(from_reddit)] = "reddit"

        if use_sec:
            futures[pool.submit(from_sec_insider_buys)] = "sec_insiders"
            futures[pool.submit(from_sec_8k)] = "sec_8k"

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

    # Siloed engines (squeeze/photonics) join through the same funnel
    for name, tks in (extra_sources or {}).items():
        clean = [str(t).upper() for t in (tks or []) if t]
        if clean:
            sources[name] = clean
            log(f"  {name}: {len(clean)} tickers (extra)")

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

    # Filter to valid-looking tickers (format + comprehensive stoplist)
    pre = len(all_tickers)
    all_tickers = [t for t in all_tickers if _looks_like_ticker(t)]

    # Ground-truth validation: drop anything that doesn't resolve to real price
    # data (one batched fetch over the top candidates that would actually score).
    all_tickers = _validate_with_prices(all_tickers, limit=130)

    # Re-rank toward pre-fly (basing/coiled) setups instead of pure attention —
    # otherwise the top-40 that actually get scored is always whatever's already
    # hyped/extended, which is the opposite of "catch it before it flies".
    all_tickers, discovery_meta = _prefly_rerank(
        all_tickers, ticker_source_count, limit=130, sources=sources)
    for t, hint in _feed_hints.items():
        if t in discovery_meta:
            discovery_meta[t]["feed_hint"] = hint

    # Lane tag. The leader lane is a structurally different population ($2-10B,
    # $10+) from the micro/small-cap lanes, so it is marked here and persisted
    # per snapshot. Two reasons this matters more than a cosmetic label:
    #   • the day-trade scanners (day_movers, oversold) exclude it, so their ICs
    #     keep measuring the one population they were tuned on;
    #   • evaluation can segment leader vs microcap rows instead of pooling two
    #     different return distributions into one meaningless average.
    for t in sources.get("finviz_leader", []) or []:
        if t in discovery_meta:
            discovery_meta[t]["lane"] = "leader"

    return {
        "tickers": all_tickers,
        "sources": sources,
        "source_counts": ticker_source_count,
        "discovery_meta": discovery_meta,
        "total": len(all_tickers),
        "dropped_invalid": pre - len(all_tickers),
    }
