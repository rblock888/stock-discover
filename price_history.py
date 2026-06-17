"""Shared yfinance daily OHLCV fetcher with a TTL cache.

All modules that need price history should go through get_history() so each
ticker is fetched at most once per scan cycle, no matter how many scorers
look at it. On fetch failure a stale cached frame (any age) is served before
giving up — yfinance flakiness should degrade, not break, a scan.
"""

import logging
import threading
import time

logger = logging.getLogger("discovery")

TTL_SECONDS = 20 * 60  # < SCAN_INTERVAL → at most one fetch per ticker per cycle

_cache: dict = {}  # key "TICKER:period" -> (monotonic_ts, DataFrame)
_lock = threading.Lock()


def get_history(ticker: str, period: str = "1y", max_age: float = TTL_SECONDS):
    """Return daily OHLCV (ascending DatetimeIndex, yfinance-native columns) or None."""
    key = f"{ticker}:{period}"
    now = time.monotonic()
    with _lock:
        entry = _cache.get(key)
    if entry and now - entry[0] < max_age:
        return entry[1]

    try:
        import yfinance as yf
        df = yf.Ticker(ticker).history(period=period, auto_adjust=True)
        if df is not None and not df.empty:
            df = df[df["Close"].notna()]  # NaN closes poison every downstream calc
        if df is not None and not df.empty:
            with _lock:
                _cache[key] = (now, df)
            return df
    except Exception as e:
        logger.warning(f"price_history: fetch failed for {ticker}: {e}")

    return entry[1] if entry else None


def get_histories(symbols: list, period: str = "1y", max_age: float = TTL_SECONDS) -> dict:
    """Batch-fetch daily OHLCV for many symbols via one yf.download call.

    Returns {symbol: DataFrame} containing only symbols with usable data
    (fresh, just-fetched, or stale-fallback).
    """
    now = time.monotonic()
    out = {}
    to_fetch = []
    with _lock:
        for s in symbols:
            entry = _cache.get(f"{s}:{period}")
            if entry and now - entry[0] < max_age:
                out[s] = entry[1]
            else:
                to_fetch.append(s)

    if to_fetch:
        try:
            import yfinance as yf
            raw = yf.download(
                to_fetch, period=period, interval="1d", group_by="ticker",
                auto_adjust=True, progress=False, threads=True,
            )
            for s in to_fetch:
                try:
                    df = raw[s] if len(to_fetch) > 1 else raw
                    df = df.dropna(how="all")
                    if df is not None and not df.empty:
                        df = df[df["Close"].notna()]
                    if df is not None and not df.empty:
                        with _lock:
                            _cache[f"{s}:{period}"] = (now, df)
                        out[s] = df
                except Exception:
                    continue
        except Exception as e:
            logger.warning(f"price_history: batch fetch failed: {e}")

        # Stale fallback for anything the download didn't cover
        with _lock:
            for s in to_fetch:
                if s not in out:
                    entry = _cache.get(f"{s}:{period}")
                    if entry:
                        out[s] = entry[1]

    return out


def clear():
    with _lock:
        _cache.clear()
