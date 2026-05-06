"""
Short Squeeze Score
===================
Scores stocks on their short squeeze potential (0-100).

A squeeze requires:
  1. High short float    — fuel (shorts must buy to close)
  2. High days to cover  — trapped (can't exit quickly without moving price)
  3. Small float         — amplifier (less stock = bigger price impact per share covered)
  4. Upcoming catalyst   — ignition (forces the move NOW)
  5. Insider alignment   — confidence (smart money positioned the same way)

Classic setup (LFVN-style):
  ~40% float shorted, 25+ DTC, insider buys right before blackout window,
  earnings catalyst coming → forced cover into thin float = violent move
"""

import logging
import fmp

logger = logging.getLogger("short_squeeze")


def score(ticker: str, bucket_scores: dict = None) -> dict:
    """
    Score short squeeze potential (0-100).

    bucket_scores: optional pre-computed insider/catalyst scores from the main pipeline.
    """
    components = {}
    score_parts = []

    # ── Fetch short interest data ────────────────────────────────────────────
    short_pct = 0.0
    dtc = 0.0
    float_shares = 0
    shares_short = 0

    if fmp.is_configured():
        # FMP short interest endpoint
        data = fmp._get("short-interest", {"symbol": ticker})
        if data and isinstance(data, list) and len(data) > 0:
            latest = data[0]
            short_pct = latest.get("shortPercentOfFloat") or 0
            if short_pct > 1:
                short_pct /= 100
            shares_short = latest.get("shortInterest") or 0

        # Get float from profile
        profile = fmp.get_profile(ticker)
        float_shares = profile.get("floatShares", 0) or 0
        avg_vol = profile.get("avgVolume", 0) or 0
        if shares_short and avg_vol:
            dtc = shares_short / avg_vol

    if not short_pct:
        # yfinance fallback
        try:
            import yfinance as yf
            info = yf.Ticker(ticker).info or {}
            raw_pct = info.get("shortPercentOfFloat") or 0
            short_pct = raw_pct / 100 if raw_pct > 1 else raw_pct
            dtc = info.get("shortRatio") or 0
            float_shares = info.get("floatShares") or 0
            shares_short = info.get("sharesShort") or 0
        except Exception:
            pass

    # ── 1. Short % of Float (35% weight) ─────────────────────────────────────
    if short_pct >= 0.40:
        s_short = 100
        components["short_float"] = f"{short_pct:.0%} (extreme)"
    elif short_pct >= 0.25:
        s_short = 80
        components["short_float"] = f"{short_pct:.0%} (high)"
    elif short_pct >= 0.15:
        s_short = 55
        components["short_float"] = f"{short_pct:.0%} (elevated)"
    elif short_pct > 0:
        s_short = 25
        components["short_float"] = f"{short_pct:.0%} (low)"
    else:
        s_short = 0
    score_parts.append(s_short * 0.35)

    # ── 2. Days to Cover (25% weight) ────────────────────────────────────────
    if dtc >= 20:
        s_dtc = 100
        components["days_to_cover"] = f"{dtc:.0f}d (very trapped)"
    elif dtc >= 10:
        s_dtc = 80
        components["days_to_cover"] = f"{dtc:.0f}d (trapped)"
    elif dtc >= 5:
        s_dtc = 50
        components["days_to_cover"] = f"{dtc:.0f}d"
    elif dtc > 0:
        s_dtc = 20
        components["days_to_cover"] = f"{dtc:.1f}d"
    else:
        s_dtc = 0
    score_parts.append(s_dtc * 0.25)

    # ── 3. Float size (15% weight) ────────────────────────────────────────────
    if 0 < float_shares < 5_000_000:
        s_float = 100
        components["float"] = f"{float_shares/1e6:.1f}M shares (nano)"
    elif float_shares < 20_000_000:
        s_float = 85
        components["float"] = f"{float_shares/1e6:.1f}M shares (micro)"
    elif float_shares < 50_000_000:
        s_float = 65
        components["float"] = f"{float_shares/1e6:.0f}M shares (small)"
    elif float_shares < 200_000_000:
        s_float = 35
        components["float"] = f"{float_shares/1e6:.0f}M shares (mid)"
    elif float_shares > 0:
        s_float = 10
        components["float"] = f"{float_shares/1e6:.0f}M shares (large)"
    else:
        s_float = 0
    score_parts.append(s_float * 0.15)

    # ── 4. Insider alignment (15% weight) ────────────────────────────────────
    s_insider = 50
    if bucket_scores:
        insider_raw = bucket_scores.get("insider", {}).get("score", 50)
        s_insider = insider_raw
        c = bucket_scores.get("insider", {}).get("components", {})
        if insider_raw >= 70:
            components["insiders"] = c.get("insider_txns", "Buying")
        elif insider_raw < 40:
            components["insiders"] = "Selling pressure"
    score_parts.append(s_insider * 0.15)

    # ── 5. Catalyst proximity (10% weight) ───────────────────────────────────
    s_catalyst = 50
    if bucket_scores:
        catalyst_raw = bucket_scores.get("catalyst", {}).get("score", 50)
        s_catalyst = catalyst_raw
        c = bucket_scores.get("catalyst", {}).get("components", {})
        if c.get("earnings"):
            components["catalyst"] = f"Earnings: {c['earnings']}"
        elif c.get("target_upside"):
            components["catalyst"] = f"Analyst target {c['target_upside']}"
    score_parts.append(s_catalyst * 0.10)

    total = round(sum(score_parts), 1)

    if total >= 75:
        level = "extreme"
    elif total >= 60:
        level = "high"
    elif total >= 45:
        level = "moderate"
    else:
        level = "low"

    return {
        "score": total,
        "level": level,
        "short_pct_float": round(short_pct * 100, 1),
        "days_to_cover": round(dtc, 1),
        "float_shares": float_shares,
        "shares_short": shares_short,
        "components": components,
        "details": ", ".join(f"{k}: {v}" for k, v in components.items()),
    }
