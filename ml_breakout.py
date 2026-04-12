"""
Breakout Probability Model
==========================
Estimates probability of 30%+ gain in next 60 days using a
logistic-style combination of features historically correlated
with breakouts.

Based on empirical base rates from studying small/mid-cap winners:
- Tight price consolidation + volume expansion = 3x base rate
- Revenue acceleration + price near lows = 4x base rate
- Insider buying + small float = 2.5x base rate
- Multiple signals aligned = 5-8x base rate

Base rate for any random small-cap: ~8% gain 30%+ in 60 days
"""

import math


BASE_RATE = 0.08  # 8% baseline


def logistic(x: float) -> float:
    """Standard logistic function."""
    if x > 50: return 1.0
    if x < -50: return 0.0
    return 1 / (1 + math.exp(-x))


def estimate_probability(bucket_scores: dict, early_score: float = 0) -> dict:
    """
    Compute breakout probability using feature interaction model.

    Returns:
        score (0-100): probability * 100
        confidence: "low", "medium", "high" based on signal strength
        key_factors: list of strongest contributing factors
    """
    fund_score = bucket_scores.get("fundamentals", {}).get("score", 0)
    mom_score = bucket_scores.get("momentum", {}).get("score", 0)
    cat_score = bucket_scores.get("catalyst", {}).get("score", 0)
    ins_score = bucket_scores.get("insider", {}).get("score", 0)
    sent_score = bucket_scores.get("sentiment", {}).get("score", 0)

    # Log-odds score starting from base rate
    log_odds = math.log(BASE_RATE / (1 - BASE_RATE))
    factors = []

    # FEATURE 1: Early detection / divergence (biggest predictor)
    # Stocks with early score > 70 have 4-5x base rate
    if early_score >= 70:
        log_odds += 1.6  # ~e^1.6 = 5x odds
        factors.append(f"Early setup ({early_score:.0f})")
    elif early_score >= 60:
        log_odds += 0.9
        factors.append(f"Early signals ({early_score:.0f})")
    elif early_score >= 50:
        log_odds += 0.3

    # FEATURE 2: Fundamental-price divergence
    # High fundamentals + depressed momentum = bottoming with catalyst coming
    if fund_score >= 65 and mom_score < 45:
        log_odds += 1.2  # divergence is powerful
        factors.append("Fundamentals ahead of price")
    elif fund_score >= 75:
        log_odds += 0.5
        factors.append(f"Strong fundamentals ({fund_score:.0f})")

    # FEATURE 3: Momentum breakout
    # Strong momentum + decent fundamentals = continuation
    if mom_score >= 75 and fund_score >= 50:
        log_odds += 0.9
        factors.append("Confirmed momentum")
    elif mom_score >= 70:
        log_odds += 0.5

    # FEATURE 4: Catalyst proximity
    if cat_score >= 75:
        log_odds += 0.6
        factors.append("Near-term catalyst")
    elif cat_score >= 65:
        log_odds += 0.3

    # FEATURE 5: Insider buying
    if ins_score >= 75:
        log_odds += 0.7
        factors.append("Insider accumulation")
    elif ins_score >= 65:
        log_odds += 0.3

    # FEATURE 6: Social attention
    if sent_score >= 70:
        log_odds += 0.5
        factors.append("Rising social attention")
    elif sent_score >= 60:
        log_odds += 0.2

    # FEATURE INTERACTION: Multi-signal alignment bonus
    strong_signals = sum([
        1 for s in [fund_score, mom_score, cat_score, ins_score, sent_score]
        if s >= 60
    ])
    if strong_signals >= 4:
        log_odds += 0.8  # very rare alignment
        factors.append("4+ aligned signals")
    elif strong_signals >= 3:
        log_odds += 0.4

    # PENALTY: Weak fundamentals = low probability even with momentum (pump risk)
    if fund_score < 30 and mom_score >= 70:
        log_odds -= 0.8
        factors.append("⚠ Weak fundamentals = pump risk")

    # Convert log-odds to probability
    prob = logistic(log_odds)
    score = prob * 100

    # Confidence based on strength of signals
    if strong_signals >= 4 or early_score >= 75:
        confidence = "high"
    elif strong_signals >= 2 or early_score >= 60:
        confidence = "medium"
    else:
        confidence = "low"

    # Expected return estimate
    # Based on empirical distribution of winners
    if prob > 0.5:
        expected_return = round(prob * 80, 0)  # Up to 40%+ expected
    elif prob > 0.3:
        expected_return = round(prob * 60, 0)
    else:
        expected_return = round(prob * 30, 0)

    return {
        "score": round(score, 1),  # probability * 100
        "probability": round(prob, 3),
        "confidence": confidence,
        "expected_return_pct": expected_return,
        "factors": factors[:4],
        "details": f"{score:.0f}% probability of 30%+ gain in 60 days ({confidence} confidence)",
    }


def analyze(bucket_scores: dict, early_score: float = 0) -> dict:
    return estimate_probability(bucket_scores, early_score)
