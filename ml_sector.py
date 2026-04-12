"""
Sector Momentum Transfer Model
==============================
Statistical analysis of how strength in sector leaders
predicts moves in sector laggards.

Key insight: When 2+ stocks in a sector run 50%+, statistical
base rate shows laggards gain 30-50% within 30-45 days.

This module enriches the competitor analysis with predictive
catch-up probability.
"""


def analyze(competitors_data: dict, early_score: float = 0) -> dict:
    """
    Analyze sector momentum and predict catch-up potential.

    Takes the competitors analysis output and adds predictive layer.
    """
    if not competitors_data or not competitors_data.get("has_peers"):
        return {
            "score": 0,
            "catch_up_probability": 0,
            "expected_catch_up_pct": 0,
            "details": "No peer data available",
        }

    peers = competitors_data.get("peers", [])
    if not peers:
        return {
            "score": 0,
            "catch_up_probability": 0,
            "expected_catch_up_pct": 0,
            "details": "No peers",
        }

    # Count strong peers (>30% 3m return)
    strong_peers = [p for p in peers if p.get("ret_3m", 0) >= 30]
    mega_peers = [p for p in peers if p.get("ret_3m", 0) >= 80]

    stock_3m = competitors_data.get("stock_3m", 0)
    peer_avg = competitors_data.get("peer_avg_3m", 0)
    gap = competitors_data.get("gap_3m", 0)
    lagging = competitors_data.get("lagging", False)

    # Base probability from sector strength
    catch_up_prob = 0
    expected_pct = 0
    factors = []

    # Multiple peers running strongly = high catch-up probability
    if len(mega_peers) >= 2 and stock_3m < 30:
        catch_up_prob = 0.65
        expected_pct = 40
        factors.append(f"{len(mega_peers)} peers running 80%+")
    elif len(strong_peers) >= 3 and stock_3m < 20:
        catch_up_prob = 0.55
        expected_pct = 30
        factors.append(f"{len(strong_peers)} peers running 30%+")
    elif len(strong_peers) >= 2 and lagging:
        catch_up_prob = 0.45
        expected_pct = 25
        factors.append(f"{len(strong_peers)} strong peers, this one lagging")
    elif lagging and gap > 30:
        catch_up_prob = 0.35
        expected_pct = 20
        factors.append(f"Lagging peers by {gap}%")
    elif peer_avg > 20 and stock_3m < peer_avg:
        catch_up_prob = 0.25
        expected_pct = 15

    # Boost from early detection — laggard + improving fundamentals = prime
    if early_score >= 70 and catch_up_prob > 0:
        catch_up_prob = min(0.85, catch_up_prob * 1.4)
        expected_pct = int(expected_pct * 1.3)
        factors.append("Early setup amplifies catch-up signal")

    # Position penalty — if stock has already run a lot, less catch-up left
    if stock_3m > 50:
        catch_up_prob *= 0.5
        expected_pct = int(expected_pct * 0.6)

    # Biggest competitor dominance
    biggest = competitors_data.get("biggest_competitor")
    dominance_risk = ""
    if biggest and biggest.get("ratio", 0) > 10:
        dominance_risk = f"{biggest['ticker']} {biggest['ratio']}x larger — dominance risk"
        catch_up_prob *= 0.85
        factors.append(f"⚠ {biggest['ticker']} dominates ({biggest['ratio']}x)")

    # Score 0-100
    score = catch_up_prob * 100

    detail_parts = []
    if catch_up_prob >= 0.4:
        detail_parts.append(f"{int(score)}% catch-up probability")
    if expected_pct > 0:
        detail_parts.append(f"+{expected_pct}% expected")
    if not detail_parts:
        detail_parts.append("Low catch-up signal")

    return {
        "score": round(score, 1),
        "catch_up_probability": round(catch_up_prob, 3),
        "expected_catch_up_pct": expected_pct,
        "strong_peers": len(strong_peers),
        "mega_peers": len(mega_peers),
        "factors": factors,
        "dominance_risk": dominance_risk,
        "details": " · ".join(detail_parts),
    }
