"""Macro directional bias — per-market bullish/bearish read on the big tape.

The paid version of this ("Directional Bias Engine", $119/mo elsewhere) covers
9 futures/FX markets with minute updates off institutional orderflow. This is
the free daily-bar edition on the SAME markets via yfinance: trend structure
(price vs 20/50MA + slope) blended with signed volume flow (CMF, where the
instrument reports volume — FX pairs don't, so they read trend-only).

Honest scope: daily-bar bias refreshed every 15 minutes alongside the market
regime — a swing-trader's weather report, not tick-level orderflow.
"""

import time

import numpy as np

import price_history
import volume_delta

MARKETS = [
    ("ES=F", "S&P 500"),
    ("NQ=F", "Nasdaq"),
    ("GC=F", "Gold"),
    ("CL=F", "Crude Oil"),
    ("EURUSD=X", "EUR/USD"),
    ("GBPUSD=X", "GBP/USD"),
    ("USDJPY=X", "USD/JPY"),
    ("BTC-USD", "Bitcoin"),
]

_cache = {"data": None, "as_of": 0.0}


def _bias_one(symbol: str, name: str, hist) -> dict | None:
    if hist is None or len(hist) < 60:
        return None
    c = hist["Close"].to_numpy(float)
    c = c[~np.isnan(c)]
    if len(c) < 60:
        return None
    px = float(c[-1])
    ma20 = float(np.mean(c[-20:]))
    ma50 = float(np.mean(c[-50:]))
    slope10 = (px / float(c[-11]) - 1) if len(c) > 11 else 0.0
    chg_1d = (px / float(c[-2]) - 1) * 100 if len(c) > 2 else 0.0

    score = 50.0
    score += 15 if px > ma20 else -15
    score += 15 if px > ma50 else -15
    score += max(-12.0, min(12.0, slope10 * 600))

    # signed volume flow, when the instrument reports volume (FX doesn't)
    vd = volume_delta.compute(hist)
    flow = None
    if vd.get("available"):
        cmf = vd.get("cmf20") or 0.0
        score += max(-8.0, min(8.0, cmf * 40))
        flow = cmf
        if vd.get("divergence") == "bearish":
            score -= 6
        elif vd.get("divergence") == "bullish":
            score += 6

    score = max(0.0, min(100.0, score))
    bias = "BULLISH" if score >= 60 else ("BEARISH" if score <= 40 else "NEUTRAL")
    return {
        "symbol": symbol, "name": name, "bias": bias, "score": round(score),
        "price": round(px, 4 if px < 10 else 2), "chg_1d_pct": round(chg_1d, 2),
        "cmf": round(flow, 2) if flow is not None else None,
        "above_20ma": px > ma20, "above_50ma": px > ma50,
    }


def refresh() -> list:
    """Recompute all market biases (one batched fetch). Never raises."""
    try:
        hists = price_history.get_histories([s for s, _ in MARKETS], period="6mo")
        out = []
        for symbol, name in MARKETS:
            try:
                b = _bias_one(symbol, name, hists.get(symbol))
                if b:
                    out.append(b)
            except Exception:
                continue
        if out:
            _cache["data"] = out
            _cache["as_of"] = time.time()
        return out
    except Exception:
        return _cache["data"] or []


def get_cached() -> list:
    return _cache["data"] or []


def brief_line() -> str | None:
    """One compact line for the pre-open brief: 'ES ▲ NQ ▲ Gold ▼ Oil ·' ."""
    data = get_cached()
    if not data:
        return None
    glyph = {"BULLISH": "▲", "BEARISH": "▼", "NEUTRAL": "·"}
    short = {"S&P 500": "ES", "Nasdaq": "NQ", "Gold": "Gold", "Crude Oil": "Oil",
             "EUR/USD": "EUR", "GBP/USD": "GBP", "USD/JPY": "JPY", "Bitcoin": "BTC"}
    return " ".join(f"{short.get(b['name'], b['name'])}{glyph[b['bias']]}" for b in data)
