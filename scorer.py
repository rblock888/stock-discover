"""Composite scorer: combines all bucket scores into a final ranking."""

import math

import config


def composite_score(bucket_scores: dict) -> dict:
    """
    Combine bucket scores into a weighted composite.

    bucket_scores: dict with keys matching config.WEIGHTS keys,
                   each value is a dict with at least {"score": float, "details": str}
    """
    weighted_total = 0
    breakdown = {}
    signals_above_60 = 0

    for bucket, weight in config.WEIGHTS.items():
        bucket_data = bucket_scores.get(bucket, {"score": 0, "details": "N/A"})
        raw = bucket_data["score"]
        # yfinance gaps can yield NaN scores — a NaN here poisons the composite
        # and breaks JSON serialization downstream
        if not isinstance(raw, (int, float)) or not math.isfinite(raw):
            raw = 0
        weighted = raw * weight
        weighted_total += weighted
        breakdown[bucket] = {
            "raw": raw,
            "weight": weight,
            "weighted": round(weighted, 1),
            "details": bucket_data.get("details", ""),
            "components": bucket_data.get("components", {}),
        }
        if raw >= 60:
            signals_above_60 += 1

    multi_signal = signals_above_60 >= config.MULTI_SIGNAL_THRESHOLD

    return {
        "composite": round(weighted_total, 1),
        "breakdown": breakdown,
        "signals_above_60": signals_above_60,
        "multi_signal_alert": multi_signal,
    }


def format_result(ticker: str, result: dict) -> str:
    """Format a single stock's result for display."""
    lines = [f"\n{'='*60}"]
    alert = " *** MULTI-SIGNAL ALERT ***" if result["multi_signal_alert"] else ""
    lines.append(f"  {ticker}  |  Score: {result['composite']}/100{alert}")
    lines.append(f"  Signals above 60: {result['signals_above_60']}/5")
    lines.append(f"{'='*60}")

    for bucket in config.WEIGHTS:
        bd = result["breakdown"].get(bucket, {})
        raw = bd.get("raw", 0)
        weighted = bd.get("weighted", 0)
        bar = "█" * int(raw / 5) + "░" * (20 - int(raw / 5))
        marker = " <--" if raw >= 60 else ""
        lines.append(f"  {bucket:<14} {bar} {raw:5.1f} (x{bd.get('weight', 0):.2f} = {weighted:5.1f}){marker}")
        details = bd.get("details", "")
        if details:
            lines.append(f"                 {details}")

    return "\n".join(lines)


def rank_results(results: dict) -> list:
    """Sort tickers by composite score, descending."""
    ranked = sorted(results.items(), key=lambda x: x[1]["composite"], reverse=True)
    return ranked
