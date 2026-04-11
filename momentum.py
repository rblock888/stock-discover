"""Momentum scoring: relative strength, volume, moving averages, trend."""

import yfinance as yf
import numpy as np
import config


def score(ticker: str) -> dict:
    """Return a momentum score (0-100) and component details."""
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="6mo")
        spy = yf.Ticker("SPY").history(period="6mo")
    except Exception:
        return {"score": 0, "details": "Failed to fetch price data", "components": {}}

    if hist.empty or len(hist) < config.MA_LONG:
        return {"score": 0, "details": "Insufficient price history", "components": {}}

    components = {}
    scores = []
    close = hist["Close"]
    volume = hist["Volume"]

    # --- Relative strength vs SPY ---
    rs_score = 0
    try:
        days = min(config.RS_LOOKBACK_DAYS, len(close) - 1, len(spy) - 1)
        if days > 10:
            stock_ret = (close.iloc[-1] / close.iloc[-days]) - 1
            spy_ret = (spy["Close"].iloc[-1] / spy["Close"].iloc[-days]) - 1
            excess = stock_ret - spy_ret
            # +50% excess = 100, 0% = 50, -50% = 0
            rs_score = min(100, max(0, 50 + excess * 100))
            components["rel_strength"] = f"{excess:+.1%} vs SPY ({days}d)"
    except Exception:
        pass
    scores.append(("rel_strength", rs_score, 0.30))

    # --- 52-week high proximity ---
    high_score = 0
    try:
        hist_1y = stock.history(period="1y")
        if not hist_1y.empty:
            high_52w = hist_1y["Close"].max()
            current = close.iloc[-1]
            pct_from_high = current / high_52w
            # At 52w high = 100, 20% below = 50, 50%+ below = 0
            high_score = min(100, max(0, pct_from_high * 100))
            components["52w_high"] = f"{pct_from_high:.0%} of 52w high"
    except Exception:
        pass
    scores.append(("52w_high", high_score, 0.15))

    # --- Price trend (slope of 20-day MA) ---
    trend_score = 0
    try:
        ma20 = close.rolling(config.MA_SHORT).mean().dropna()
        if len(ma20) >= 20:
            slope = (ma20.iloc[-1] / ma20.iloc[-20]) - 1
            # 20% rise over 20 days of MA = 100
            trend_score = min(100, max(0, slope * 500))
            components["trend"] = f"20MA slope {slope:+.1%}"
    except Exception:
        pass
    scores.append(("trend", trend_score, 0.20))

    # --- Volume expansion ---
    vol_score = 0
    try:
        if len(volume) >= config.VOLUME_EXPANSION_LOOKBACK * 2:
            recent_vol = volume.iloc[-config.VOLUME_EXPANSION_LOOKBACK:].mean()
            prior_vol = volume.iloc[-config.VOLUME_EXPANSION_LOOKBACK*2:-config.VOLUME_EXPANSION_LOOKBACK].mean()
            if prior_vol > 0:
                expansion = recent_vol / prior_vol
                # 2x volume = 100, 1x = 50, 0.5x = 0
                vol_score = min(100, max(0, (expansion - 0.5) * 66.7))
                components["volume"] = f"{expansion:.1f}x vs prior {config.VOLUME_EXPANSION_LOOKBACK}d"
    except Exception:
        pass
    scores.append(("volume", vol_score, 0.20))

    # --- MA breakout (price above both 20 and 50 MA) ---
    breakout_score = 0
    try:
        ma_short = close.rolling(config.MA_SHORT).mean()
        ma_long = close.rolling(config.MA_LONG).mean()
        current = close.iloc[-1]
        above_short = current > ma_short.iloc[-1]
        above_long = current > ma_long.iloc[-1]
        ma_cross = ma_short.iloc[-1] > ma_long.iloc[-1]  # golden cross

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
    except Exception:
        pass
    scores.append(("breakout", breakout_score, 0.15))

    total = sum(s * w for _, s, w in scores)

    return {
        "score": round(total, 1),
        "components": components,
        "details": ", ".join(f"{k}: {v}" for k, v in components.items()),
    }
