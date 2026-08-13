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


PAGE_SIZE = 20
MAX_PAGES = 20          # safety stop: 400 names is far beyond any of these screens


def _finviz_screen(filters: str, max_pages: int = MAX_PAGES) -> list:
    """Scrape a Finviz screen to EXHAUSTION, not to an arbitrary count.

    This used to stop after ~60 names. Finviz returns ticker-alphabetical by
    default, so the squeeze lane only ever saw tickers starting A-E — roughly a
    third of a ~190-name screen, and the cut fell in the same place every run,
    so nothing looked wrong. Sorting cannot fix it: Finviz silently falls back
    to reverse-ticker order for sort tokens it does not recognise (verified —
    `o=-shortfloat` returns ZBIO, XPOF, WYFI..., which is just Z-to-A), so a
    sort-based fix would have swapped one alphabetical blind spot for another.

    Paging to exhaustion is immune to that. Discovery over the full screen is
    cheap (HTML, ~10 requests); it is the per-ticker yfinance SCORING that costs,
    and that stays capped in discover_candidates() — but it now chooses from
    every match rather than from whatever sorted first."""
    tickers, seen = [], set()
    try:
        for page in range(max_pages):
            start = page * PAGE_SIZE + 1
            params = {"v": "111", "f": filters, "ft": "4", "r": str(start)}
            resp = requests.get(_FINVIZ, params=params, headers=_HEADERS, timeout=12)
            if resp.status_code != 200:
                logger.warning(f"Finviz page {page + 1} returned {resp.status_code}")
                break
            # Finviz moved from quote.ashx?t= to stock?t= links (2026) — match both.
            # Each row links the ticker more than once, so de-dup within the page
            # before deciding whether the page was full.
            on_page = list(dict.fromkeys(
                re.findall(r'(?:quote\.ashx|stock)\?t=([A-Z]{1,5})', resp.text)))
            fresh = [t for t in on_page if t not in seen]
            seen.update(fresh)
            tickers.extend(fresh)
            if len(on_page) < PAGE_SIZE:
                break        # short page = last page
            if not fresh:
                break        # same names repeating = pagination stopped advancing
            time.sleep(0.6)
        else:
            logger.warning(f"Finviz screen hit the {max_pages}-page safety stop "
                           f"({len(tickers)} names) — results may be truncated: {filters}")
    except Exception as e:
        logger.warning(f"Finviz scrape failed ({filters}): {e}")
    return tickers


def discover_candidates(max_tickers: int = 80) -> list:
    """
    Find high-short-interest candidates from multiple Finviz screens.
    Deduplicates and prioritises tickers that appear in multiple screens.
    """
    # (filters, label, weight) — weight reflects how much squeeze evidence the
    # screen itself implies, and breaks ties among the majority of names that
    # match only ONE screen. Without it, ranking by cross-screen count alone
    # leaves that whole group in Finviz's default alphabetical order, which
    # re-introduces the exact A-E bias the pagination fix just removed.
    SCREENS = [
        ("sh_short_o20,sh_float_u100,sh_avgvol_o200,sh_price_o1",
         "short>20% + float<100M", 2),
        ("sh_short_o30,sh_avgvol_o200,sh_price_o1",
         "short>30% (extreme)", 3),
        ("sh_short_o10,sh_float_u20,sh_avgvol_o100,sh_price_o1",
         "nano float<20M + short>10%", 2),
    ]

    counts: dict[str, int] = {}
    weights: dict[str, int] = {}
    for filters, label, w in SCREENS:
        found = _finviz_screen(filters)
        logger.info(f"  Screen ({label}): {len(found)} tickers")
        for t in found:
            counts[t] = counts.get(t, 0) + 1
            weights[t] = weights.get(t, 0) + w

    # Strongest evidence first: screen weight, then cross-screen frequency.
    ranked = sorted(counts.keys(),
                    key=lambda t: (weights[t], counts[t]), reverse=True)
    if len(ranked) > max_tickers:
        # Never truncate silently — a cap that is invisible reads as "we looked
        # at everything" when it did not. This is the line that would have made
        # the original A-E bug obvious years earlier.
        logger.info(f"Squeeze discovery: {len(ranked)} unique candidates found, "
                    f"scoring the top {max_tickers} by screen weight")
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
