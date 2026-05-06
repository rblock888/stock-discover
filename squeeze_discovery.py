"""
Squeeze Discovery
=================
Proactively finds high-short-interest stocks by scraping Finviz with
short-float and float-size filters, then scoring each candidate.

No manual ticker list — discovery is fully data-driven.
"""

import re
import time
import logging
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

import short_squeeze

logger = logging.getLogger("squeeze_discovery")

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
    "Accept": "text/html",
}
_FINVIZ = "https://finviz.com/screener.ashx"


def _finviz_screen(filters: str, max_tickers: int = 80) -> list:
    """Scrape Finviz screener with the given filter string."""
    tickers = []
    seen = set()
    try:
        for start in range(1, max_tickers + 1, 20):
            params = {"v": "111", "f": filters, "ft": "4", "r": str(start)}
            resp = requests.get(_FINVIZ, params=params, headers=_HEADERS, timeout=12)
            if resp.status_code != 200:
                break
            batch = []
            for t in re.findall(r'quote\.ashx\?t=([A-Z]{1,5})', resp.text):
                if t not in seen:
                    seen.add(t)
                    batch.append(t)
            tickers.extend(batch)
            if len(batch) < 10:
                break
            time.sleep(0.6)
    except Exception as e:
        logger.warning(f"Finviz scrape failed ({filters}): {e}")
    return tickers


def discover_candidates(max_tickers: int = 80) -> list:
    """
    Find high-short-interest candidates from multiple Finviz screens.
    Deduplicates and prioritises tickers that appear in multiple screens.
    """
    # Screen 1: short float >20%, float <100M, avg vol >200K, price >$1
    s1 = _finviz_screen("sh_short_o20,sh_float_u100,sh_avgvol_o200,sh_price_o1", 60)
    logger.info(f"  Screen 1 (short>20% + float<100M): {len(s1)} tickers")

    # Screen 2: extreme short float >30%, any float — catches large-cap squeezes too
    s2 = _finviz_screen("sh_short_o30,sh_avgvol_o200,sh_price_o1", 60)
    logger.info(f"  Screen 2 (short>30%): {len(s2)} tickers")

    # Screen 3: nano/micro float (<20M shares), moderate short interest >10%
    s3 = _finviz_screen("sh_short_o10,sh_float_u20,sh_avgvol_o100,sh_price_o1", 60)
    logger.info(f"  Screen 3 (nano float + short>10%): {len(s3)} tickers")

    counts: dict[str, int] = {}
    for t in s1 + s2 + s3:
        counts[t] = counts.get(t, 0) + 1

    # Sort by cross-screen frequency — appearing in multiple screens is a stronger signal
    ranked = sorted(counts.keys(), key=lambda t: counts[t], reverse=True)
    return ranked[:max_tickers]


def _score_ticker(ticker: str) -> dict | None:
    """Fetch yfinance info once, then score and attach display metadata."""
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info or {}

        # Score using pre-fetched data to avoid a second network call
        result = short_squeeze.score(ticker, yf_info=info)
        if result["score"] < 35:
            return None

        price = info.get("currentPrice") or info.get("regularMarketPrice") or 0
        prev = info.get("previousClose") or price
        change_pct = round((price - prev) / prev * 100, 2) if prev else 0

        result["ticker"] = ticker
        result["name"] = info.get("shortName") or info.get("longName") or ticker
        result["price"] = price
        result["change_pct"] = change_pct
        result["sector"] = info.get("sector") or ""
        result["market_cap"] = info.get("marketCap") or 0
        return result
    except Exception as e:
        logger.debug(f"  Failed {ticker}: {e}")
        return None


def scan(max_candidates: int = 80, min_score: int = 35) -> list:
    """
    Full scan: discover → score → rank.
    Returns list of enriched squeeze-scored dicts, sorted by score descending.
    """
    tickers = discover_candidates(max_candidates)
    logger.info(f"Squeeze discovery: scoring {len(tickers)} candidates")

    results = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(_score_ticker, t): t for t in tickers}
        done = 0
        for future in as_completed(futures):
            done += 1
            r = future.result()
            if r:
                results.append(r)
            if done % 10 == 0:
                logger.info(f"  Scored {done}/{len(tickers)}, {len(results)} passing")

    results.sort(key=lambda x: x["score"], reverse=True)
    logger.info(f"Squeeze scan done: {len(results)} candidates (score >= {min_score})")
    return results
