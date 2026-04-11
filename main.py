#!/usr/bin/env python3
"""
Stock Discovery Tool
====================
Surfaces stocks with multi-signal alignment for potential rerating.
Scores across fundamentals, momentum, catalysts, insider activity, and sentiment.

Usage:
    python main.py                          # Use default universe file
    python main.py LWLG ASTS RKLB LUNR     # Score specific tickers
    python main.py --universe universe.txt  # Use a custom universe file
    python main.py --top 10                 # Show top 10 only
"""

import sys
import argparse
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import yfinance as yf

import config
import fundamentals
import momentum
import catalysts
import insiders
import reddit_sentiment
import scorer


def load_universe(filepath: str) -> list:
    """Load tickers from a file (one per line)."""
    p = Path(filepath)
    if not p.exists():
        print(f"Universe file '{filepath}' not found.")
        print("Create it with one ticker per line, or pass tickers as arguments.")
        sys.exit(1)
    tickers = []
    for line in p.read_text().splitlines():
        t = line.strip().upper()
        if t and not t.startswith("#"):
            tickers.append(t)
    return tickers


def filter_universe(tickers: list) -> list:
    """Remove illiquid or obviously low-quality names."""
    filtered = []
    print(f"\nFiltering {len(tickers)} tickers...")

    def check(ticker):
        try:
            stock = yf.Ticker(ticker)
            info = stock.info or {}
            price = info.get("currentPrice") or info.get("regularMarketPrice") or 0
            avg_vol = info.get("averageVolume") or 0
            mcap = info.get("marketCap") or 0

            if price < config.MIN_PRICE or price > config.MAX_PRICE:
                return None, f"price ${price:.2f}"
            if avg_vol < config.MIN_AVG_VOLUME:
                return None, f"volume {avg_vol:,.0f}"
            if mcap < config.MIN_MARKET_CAP:
                return None, f"mcap ${mcap/1e6:.0f}M"
            return ticker, None
        except Exception:
            return None, "error"

    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(check, t): t for t in tickers}
        for future in as_completed(futures):
            t = futures[future]
            result, reason = future.result()
            if result:
                filtered.append(result)
            else:
                print(f"  Filtered out {t}: {reason}")

    print(f"  {len(filtered)} tickers passed filters\n")
    return filtered


def score_ticker(ticker: str) -> tuple:
    """Score a single ticker across all buckets."""
    print(f"  Scoring {ticker}...", flush=True)
    start = time.time()

    bucket_scores = {
        "fundamentals": fundamentals.score(ticker),
        "momentum": momentum.score(ticker),
        "catalyst": catalysts.score(ticker),
        "insider": insiders.score(ticker),
        "sentiment": reddit_sentiment.score(ticker),
    }

    result = scorer.composite_score(bucket_scores)
    elapsed = time.time() - start
    print(f"  Scoring {ticker}... done ({elapsed:.1f}s)", flush=True)
    return ticker, result


def run_pipeline(tickers: list, top_n: int, skip_filter: bool = False):
    """Run the full discovery pipeline."""
    print("=" * 60)
    print("  STOCK DISCOVERY TOOL")
    print("=" * 60)

    # Filter
    if skip_filter:
        universe = tickers
    else:
        universe = filter_universe(tickers)

    if not universe:
        print("No tickers to score after filtering.")
        return

    # Score
    print(f"Scoring {len(universe)} tickers across 5 dimensions...")
    results = {}

    # Use threads for I/O-bound yfinance calls, but limit concurrency
    # to avoid rate limits
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(score_ticker, t): t for t in universe}
        for future in as_completed(futures):
            ticker, result = future.result()
            results[ticker] = result

    # Rank
    ranked = scorer.rank_results(results)

    # Output
    print(f"\n{'='*60}")
    print(f"  TOP {min(top_n, len(ranked))} STOCKS BY COMPOSITE SCORE")
    print(f"{'='*60}")

    alerts = []
    for i, (ticker, result) in enumerate(ranked[:top_n]):
        print(scorer.format_result(ticker, result))
        if result["multi_signal_alert"]:
            alerts.append(ticker)

    # Summary
    print(f"\n{'='*60}")
    print(f"  SUMMARY")
    print(f"{'='*60}")
    print(f"  Tickers scored: {len(results)}")
    print(f"  Multi-signal alerts ({config.MULTI_SIGNAL_THRESHOLD}+ buckets above 60):")
    if alerts:
        for t in alerts:
            r = results[t]
            print(f"    >>> {t}: {r['composite']}/100 ({r['signals_above_60']}/5 signals)")
    else:
        print("    None")
    print()


def main():
    parser = argparse.ArgumentParser(description="Stock Discovery Tool")
    parser.add_argument("tickers", nargs="*", help="Tickers to score")
    parser.add_argument("--universe", "-u", default=config.DEFAULT_UNIVERSE_FILE,
                        help="Path to universe file (one ticker per line)")
    parser.add_argument("--top", "-n", type=int, default=config.TOP_N,
                        help=f"Number of top stocks to display (default: {config.TOP_N})")
    parser.add_argument("--no-filter", action="store_true",
                        help="Skip universe filtering")
    args = parser.parse_args()

    if args.tickers:
        tickers = [t.upper() for t in args.tickers]
        run_pipeline(tickers, args.top, skip_filter=args.no_filter)
    else:
        tickers = load_universe(args.universe)
        run_pipeline(tickers, args.top)


if __name__ == "__main__":
    main()
