"""Momentum scoring: relative strength, volume, moving averages, trend."""

import numpy as np
import config
import fmp


def _calc_momentum(closes: list, volumes: list, spy_closes: list = None) -> dict:
    """Calculate momentum metrics from price/volume arrays (newest first).

    spy_closes: ascending SPY closes — when provided, relative strength is
    scored on SPY-EXCESS return (true RS), not raw absolute return.
    """
    if len(closes) < config.MA_LONG:
        return {"score": 0, "details": "Insufficient price history", "components": {}}

    # Reverse to oldest-first for calculations
    closes = list(reversed(closes))
    volumes = list(reversed(volumes))

    components = {}
    scores = []
    n = len(closes)

    # Relative strength — SPY-excess return over the lookback (the real signal)
    rs_score = 50  # neutral if we can't compute
    days = min(config.RS_LOOKBACK_DAYS, n - 1)
    if days > 10:
        stock_ret = (closes[-1] / closes[-days]) - 1
        if spy_closes is not None and len(spy_closes) > days and spy_closes[-days] > 0:
            spy_ret = (spy_closes[-1] / spy_closes[-days]) - 1
            excess = stock_ret - spy_ret
            # Matching SPY → 50; +25% excess → 100; -25% → 0
            rs_score = min(100, max(0, 50 + excess * 200))
            components["rel_strength"] = f"{excess:+.1%} vs SPY"
            components["return"] = f"{stock_ret:+.1%} ({days}d)"
        else:
            # No benchmark available — fall back to absolute return
            rs_score = min(100, max(0, 50 + stock_ret * 100))
            components["return"] = f"{stock_ret:+.1%} ({days}d)"
    scores.append(rs_score * 0.30)

    # 52-week high proximity
    high_score = 0
    high_52w = max(closes[-min(252, n):])
    current = closes[-1]
    pct_from_high = current / high_52w if high_52w > 0 else 0
    high_score = min(100, max(0, pct_from_high * 100))
    components["52w_high"] = f"{pct_from_high:.0%} of high"
    scores.append(high_score * 0.15)

    # Price trend (20MA slope)
    trend_score = 0
    if n >= config.MA_SHORT + 20:
        ma_vals = []
        for i in range(n - config.MA_SHORT + 1):
            ma_vals.append(sum(closes[i:i+config.MA_SHORT]) / config.MA_SHORT)
        if len(ma_vals) >= 20:
            slope = (ma_vals[-1] / ma_vals[-20]) - 1
            trend_score = min(100, max(0, slope * 500))
            components["trend"] = f"20MA slope {slope:+.1%}"
    scores.append(trend_score * 0.20)

    # Volume expansion
    vol_score = 50
    lb = config.VOLUME_EXPANSION_LOOKBACK
    if len(volumes) >= lb * 2:
        recent_vol = sum(volumes[-lb:]) / lb
        prior_vol = sum(volumes[-lb*2:-lb]) / lb
        if prior_vol > 0:
            expansion = recent_vol / prior_vol
            vol_score = min(100, max(0, (expansion - 0.5) * 66.7))
            components["volume"] = f"{expansion:.1f}x vs prior {lb}d"
    scores.append(vol_score * 0.20)

    # MA breakout
    breakout_score = 0
    if n >= config.MA_LONG:
        ma_short = sum(closes[-config.MA_SHORT:]) / config.MA_SHORT
        ma_long = sum(closes[-config.MA_LONG:]) / config.MA_LONG
        above_short = current > ma_short
        above_long = current > ma_long
        ma_cross = ma_short > ma_long

        if above_short and above_long and ma_cross:
            breakout_score = 100
            components["breakout"] = "Above 20/50 MA, golden cross"
        elif above_short and above_long:
            breakout_score = 75
            components["breakout"] = "Above 20/50 MA"
        elif above_short:
            breakout_score = 50
            components["breakout"] = "Above 20 MA only"
        else:
            breakout_score = 10
            components["breakout"] = "Below key MAs"
    scores.append(breakout_score * 0.15)

    total = sum(scores)
    return {"score": round(total, 1), "components": components,
            "details": ", ".join(f"{k}: {v}" for k, v in components.items())}


def _fmp_score(ticker: str) -> dict:
    """Score using FMP historical prices."""
    hist = fmp.get_historical_price(ticker, days=252)
    if not hist:
        return {"score": 0, "details": "No price data", "components": {}}

    closes = [d["close"] for d in hist if "close" in d]
    volumes = [d.get("volume", 0) for d in hist if "close" in d]
    return _calc_momentum(closes, volumes)


def _yf_score(ticker: str, hist=None) -> dict:
    """Fallback to yfinance (via the shared, TTL-cached price_history fetcher)."""
    try:
        import price_history
        if hist is None:
            hist = price_history.get_history(ticker, period="1y")
        if hist is None or hist.empty or len(hist) < config.MA_LONG:
            return {"score": 0, "details": "Insufficient history", "components": {}}

        closes = hist["Close"].tolist()
        volumes = hist["Volume"].tolist()

        # SPY benchmark (fetched once per cycle via the shared cache) → true RS
        spy_closes = None
        try:
            spy = price_history.get_history("SPY", period="1y")
            if spy is not None and not spy.empty:
                spy_closes = spy["Close"].tolist()  # ascending
        except Exception:
            pass

        return _calc_momentum(list(reversed(closes)), list(reversed(volumes)), spy_closes=spy_closes)
    except Exception:
        return {"score": 0, "details": "Failed to fetch data", "components": {}}


def score(ticker: str, hist=None) -> dict:
    """Return a momentum score (0-100). Accepts a pre-fetched daily history frame."""
    if fmp.is_configured():
        return _fmp_score(ticker)
    return _yf_score(ticker, hist=hist)
