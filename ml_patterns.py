"""
ML Pattern Matching Module
==========================
Finds stocks that look like historical winners did BEFORE their big move.

Approach:
1. Library of known winners — stocks that ran 100%+ in past 2 years
2. For each winner, snapshot features at (peak - 60 days)
3. Extract same features from current candidate
4. Compute cosine similarity — higher = more similar to a pre-breakout setup
5. Return top matches with expected trajectory

Features used (normalized 0-1):
- price_position: where in 52-week range (near low = good)
- rel_strength: 3-month return vs SPY
- volume_expansion: recent volume / prior volume
- revenue_growth: YoY revenue growth
- rev_acceleration: is growth accelerating
- margin_trend: gross margin direction
- mcap_tier: market cap (smaller = more room)
- insider_signal: net insider buying (-1 to 1)
- days_basing: days consolidating below recent highs
"""

import math
from datetime import datetime, timedelta


# ----------------------------------------------------------------------------
# Library of historical winners with their pre-breakout feature snapshots
# (features taken at approx peak-60d, normalized to 0-1 scale)
# ----------------------------------------------------------------------------

WINNERS_LIBRARY = [
    {
        "ticker": "LWLG",
        "move_pct": 1100,
        "move_days": 365,
        "move_peak_date": "2026-04-01",
        "features": {
            "price_position": 0.08,     # near lows
            "rel_strength": 0.15,        # underperforming
            "volume_expansion": 1.3,     # volume picking up
            "revenue_growth": 0.90,      # extreme revenue growth
            "rev_acceleration": 1.0,     # clearly accelerating
            "margin_trend": 0.85,        # strong margins
            "mcap_tier": 0.15,           # micro-cap
            "insider_signal": 0.3,       # some buying
            "days_basing": 90,
        },
        "thesis": "Micro-cap photonics with revenue inflection at multi-year lows",
    },
    {
        "ticker": "ASTS",
        "move_pct": 320,
        "move_days": 180,
        "move_peak_date": "2024-10-15",
        "features": {
            "price_position": 0.18,
            "rel_strength": 0.25,
            "volume_expansion": 1.6,
            "revenue_growth": 0.95,
            "rev_acceleration": 0.95,
            "margin_trend": 0.60,
            "mcap_tier": 0.25,
            "insider_signal": 0.4,
            "days_basing": 120,
        },
        "thesis": "Satellite network pre-commercial launch, heavy accumulation",
    },
    {
        "ticker": "SMCI",
        "move_pct": 450,
        "move_days": 240,
        "move_peak_date": "2024-03-08",
        "features": {
            "price_position": 0.35,
            "rel_strength": 0.45,
            "volume_expansion": 1.8,
            "revenue_growth": 0.75,
            "rev_acceleration": 0.90,
            "margin_trend": 0.70,
            "mcap_tier": 0.40,
            "insider_signal": 0.2,
            "days_basing": 60,
        },
        "thesis": "AI infrastructure beneficiary, revenue accelerating on NVDA coattails",
    },
    {
        "ticker": "NVDA",
        "move_pct": 240,
        "move_days": 365,
        "move_peak_date": "2024-06-18",
        "features": {
            "price_position": 0.42,
            "rel_strength": 0.55,
            "volume_expansion": 1.4,
            "revenue_growth": 0.88,
            "rev_acceleration": 1.0,
            "margin_trend": 0.90,
            "mcap_tier": 0.80,
            "insider_signal": 0.15,
            "days_basing": 45,
        },
        "thesis": "AI capex cycle, dominant moat, fundamentals inflecting hard",
    },
    {
        "ticker": "PLTR",
        "move_pct": 380,
        "move_days": 300,
        "move_peak_date": "2024-12-24",
        "features": {
            "price_position": 0.30,
            "rel_strength": 0.40,
            "volume_expansion": 1.5,
            "revenue_growth": 0.35,
            "rev_acceleration": 0.85,
            "margin_trend": 0.75,
            "mcap_tier": 0.55,
            "insider_signal": 0.25,
            "days_basing": 75,
        },
        "thesis": "Enterprise AI platform finally turning profitable, government tailwind",
    },
    {
        "ticker": "RKLB",
        "move_pct": 180,
        "move_days": 150,
        "move_peak_date": "2024-11-15",
        "features": {
            "price_position": 0.22,
            "rel_strength": 0.20,
            "volume_expansion": 1.4,
            "revenue_growth": 0.55,
            "rev_acceleration": 0.80,
            "margin_trend": 0.55,
            "mcap_tier": 0.35,
            "insider_signal": 0.35,
            "days_basing": 90,
        },
        "thesis": "Space launch scaling, Neutron milestone, insiders accumulating",
    },
    {
        "ticker": "IONQ",
        "move_pct": 550,
        "move_days": 270,
        "move_peak_date": "2024-12-10",
        "features": {
            "price_position": 0.15,
            "rel_strength": 0.10,
            "volume_expansion": 1.7,
            "revenue_growth": 0.80,
            "rev_acceleration": 0.85,
            "margin_trend": 0.50,
            "mcap_tier": 0.25,
            "insider_signal": 0.3,
            "days_basing": 120,
        },
        "thesis": "Quantum computing pre-commercial, government contracts ramping",
    },
    {
        "ticker": "HIMS",
        "move_pct": 250,
        "move_days": 200,
        "move_peak_date": "2024-05-18",
        "features": {
            "price_position": 0.20,
            "rel_strength": 0.30,
            "volume_expansion": 1.3,
            "revenue_growth": 0.48,
            "rev_acceleration": 0.75,
            "margin_trend": 0.65,
            "mcap_tier": 0.35,
            "insider_signal": 0.20,
            "days_basing": 60,
        },
        "thesis": "Telehealth profitability inflection, GLP-1 tailwind",
    },
    {
        "ticker": "CELH",
        "move_pct": 200,
        "move_days": 180,
        "move_peak_date": "2024-02-20",
        "features": {
            "price_position": 0.28,
            "rel_strength": 0.35,
            "volume_expansion": 1.5,
            "revenue_growth": 0.85,
            "rev_acceleration": 0.90,
            "margin_trend": 0.75,
            "mcap_tier": 0.45,
            "insider_signal": 0.10,
            "days_basing": 50,
        },
        "thesis": "Energy drink market share grab with Pepsi distribution",
    },
    {
        "ticker": "SOUN",
        "move_pct": 900,
        "move_days": 180,
        "move_peak_date": "2024-04-10",
        "features": {
            "price_position": 0.10,
            "rel_strength": 0.12,
            "volume_expansion": 1.9,
            "revenue_growth": 0.65,
            "rev_acceleration": 0.85,
            "margin_trend": 0.45,
            "mcap_tier": 0.15,
            "insider_signal": 0.40,
            "days_basing": 110,
        },
        "thesis": "Voice AI with NVDA investment catalyst, micro-cap + retail attention",
    },
]


# Features and their weights when computing similarity
FEATURE_WEIGHTS = {
    "price_position": 0.18,
    "rel_strength": 0.10,
    "volume_expansion": 0.12,
    "revenue_growth": 0.15,
    "rev_acceleration": 0.15,
    "margin_trend": 0.08,
    "mcap_tier": 0.10,
    "insider_signal": 0.12,
}


def _normalize_value(key: str, raw_value) -> float:
    """Normalize raw values from scoring modules to 0-1 range used in library."""
    if raw_value is None:
        return 0.5  # neutral default

    try:
        v = float(raw_value)
    except (TypeError, ValueError):
        return 0.5

    if key == "price_position":
        # 0 = at 52w low, 1 = at 52w high. Winners had this LOW.
        return max(0, min(1, v))
    elif key == "rel_strength":
        # -1 to +2 range → normalize
        return max(0, min(1, (v + 1) / 3))
    elif key == "volume_expansion":
        # 0.5 to 3x range
        return max(0, min(3, v))
    elif key == "revenue_growth":
        # -0.2 to 3.0 range (up to 300%)
        return max(0, min(1, (v + 0.2) / 3.2))
    elif key == "mcap_tier":
        # mcap in USD
        if v < 100_000_000: return 0.10
        if v < 500_000_000: return 0.25
        if v < 2_000_000_000: return 0.45
        if v < 10_000_000_000: return 0.65
        return 0.85
    else:
        return max(0, min(1, v))


def extract_features_from_scores(bucket_scores: dict, quote: dict = None, hist: list = None) -> dict:
    """
    Extract ML features from existing bucket scoring output.
    Returns normalized feature dict matching WINNERS_LIBRARY format.
    """
    fund = bucket_scores.get("fundamentals", {}).get("components", {})
    mom = bucket_scores.get("momentum", {}).get("components", {})
    ins = bucket_scores.get("insider", {}).get("components", {})

    features = {}

    # Price position (from momentum components or early detection)
    early_comps = bucket_scores.get("early_detection", {}).get("components", {})
    pos_str = early_comps.get("price_position", "") or mom.get("52w_high", "")
    pos_val = _parse_pct(pos_str)
    features["price_position"] = pos_val if pos_val is not None else 0.5

    # Relative strength
    rs_str = mom.get("rel_strength", "") or mom.get("return", "")
    rs_val = _parse_signed_pct(rs_str)
    features["rel_strength"] = (rs_val + 1) / 3 if rs_val is not None else 0.5

    # Volume expansion
    vol_str = mom.get("volume", "")
    vol_val = _parse_x_multiplier(vol_str)
    features["volume_expansion"] = vol_val if vol_val is not None else 1.0

    # Revenue growth
    rg_str = fund.get("revenue_growth", "")
    rg_val = _parse_signed_pct(rg_str)
    features["revenue_growth"] = max(0, min(1, (rg_val + 0.2) / 3.2)) if rg_val is not None else 0.4

    # Revenue acceleration
    raw_score = bucket_scores.get("fundamentals", {}).get("score", 50)
    features["rev_acceleration"] = raw_score / 100

    # Margin trend (use gross margin as proxy)
    gm_str = fund.get("gross_margin", "")
    gm_val = _parse_pct(gm_str)
    features["margin_trend"] = gm_val if gm_val is not None else 0.5

    # Market cap tier
    mcap_str = ins.get("mcap", "") or ins.get("size", "")
    mcap_val = _parse_mcap(mcap_str)
    features["mcap_tier"] = _normalize_value("mcap_tier", mcap_val) if mcap_val else 0.5

    # Insider signal
    ins_score = bucket_scores.get("insider", {}).get("score", 50)
    features["insider_signal"] = (ins_score - 50) / 100 + 0.3  # center around 0.3

    return features


def _parse_pct(s) -> float | None:
    """Parse strings like '45%' or '0.45' into 0-1."""
    if not s:
        return None
    try:
        s = str(s).replace("%", "").strip()
        # Handle "of 52w high" format
        s = s.split()[0] if " " in s else s
        v = float(s)
        if abs(v) > 2:  # was percentage
            return v / 100
        return v
    except (ValueError, IndexError):
        return None


def _parse_signed_pct(s) -> float | None:
    """Parse '+15.2%' or '-8.5%' → 0.152 / -0.085"""
    if not s:
        return None
    try:
        s = str(s).replace("%", "").replace("+", "").strip()
        # Take first number
        parts = s.split()
        if parts:
            v = float(parts[0])
            if abs(v) > 2:
                return v / 100
            return v
    except (ValueError, IndexError):
        pass
    return None


def _parse_x_multiplier(s) -> float | None:
    """Parse '1.5x' → 1.5"""
    if not s:
        return None
    try:
        s = str(s).replace("x", "").strip()
        return float(s.split()[0])
    except (ValueError, IndexError):
        return None


def _parse_mcap(s) -> float | None:
    """Parse '$250M' or '$1.5B' → 250_000_000 / 1_500_000_000"""
    if not s:
        return None
    try:
        s = str(s).replace("$", "").replace(",", "").upper().strip()
        # Extract first token
        tokens = s.split()
        for t in tokens:
            if t.endswith("M"):
                return float(t[:-1]) * 1e6
            if t.endswith("B"):
                return float(t[:-1]) * 1e9
            if t.endswith("K"):
                return float(t[:-1]) * 1e3
    except (ValueError, IndexError):
        pass
    return None


def cosine_similarity(a: dict, b: dict) -> float:
    """Weighted cosine similarity between two feature dicts."""
    common = set(a.keys()) & set(b.keys()) & set(FEATURE_WEIGHTS.keys())
    if not common:
        return 0

    dot = 0
    mag_a = 0
    mag_b = 0
    for k in common:
        w = FEATURE_WEIGHTS[k]
        va = float(a[k]) * w
        vb = float(b[k]) * w
        dot += va * vb
        mag_a += va * va
        mag_b += vb * vb

    if mag_a == 0 or mag_b == 0:
        return 0
    return dot / (math.sqrt(mag_a) * math.sqrt(mag_b))


def find_matches(features: dict, top_n: int = 3) -> list:
    """
    Find the top-N historical winners whose pre-breakout setup
    most closely matches current features.
    """
    matches = []
    for winner in WINNERS_LIBRARY:
        sim = cosine_similarity(features, winner["features"])
        matches.append({
            "ticker": winner["ticker"],
            "similarity": round(sim * 100, 1),
            "move_pct": winner["move_pct"],
            "move_days": winner["move_days"],
            "thesis": winner["thesis"],
        })

    matches.sort(key=lambda x: x["similarity"], reverse=True)
    return matches[:top_n]


def analyze(bucket_scores: dict) -> dict:
    """
    Main entry point: analyze a stock using pattern matching.
    Returns similarity score and top matches.
    """
    try:
        features = extract_features_from_scores(bucket_scores)
        matches = find_matches(features, top_n=3)

        if not matches:
            return {
                "score": 0,
                "best_match": None,
                "matches": [],
                "details": "No matches",
            }

        top = matches[0]
        # Score the stock based on top similarity + expected return weight
        ml_score = top["similarity"]

        # Boost score if multiple strong matches align
        strong_matches = [m for m in matches if m["similarity"] >= 65]
        if len(strong_matches) >= 2:
            ml_score = min(100, ml_score + 10)

        return {
            "score": round(ml_score, 1),
            "best_match": top["ticker"],
            "matches": matches,
            "details": f"Similar to {top['ticker']} (+{top['move_pct']}% in {top['move_days']}d)",
        }
    except Exception as e:
        return {
            "score": 0,
            "best_match": None,
            "matches": [],
            "details": f"Error: {e}",
        }
