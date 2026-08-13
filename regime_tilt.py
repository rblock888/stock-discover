"""Regime-aware ranking tilt.

The market regime and per-ticker edge gauges are otherwise display-only. This
turns them into a small, BOUNDED, LOGGED multiplier on the composite — used for
RANKING only. The composite itself is never altered, so the tilt is fully
reversible and measurable: tilt_factor is persisted per snapshot, letting the
evaluation engine A/B tilted-vs-base forward returns before we ever trust it.

factor ∈ [0.7, 1.3]; each rule nudges a log-space accumulator by a small amount
so the clip rarely binds and the tilt stays gentle.
"""

import math

# yfinance sector → market_regime sector-ETF display name
SECTOR_MAP = {
    "Technology": "Tech",
    "Healthcare": "Healthcare",
    "Financial Services": "Financials",
    "Energy": "Energy",
    "Industrials": "Industrials",
    "Consumer Cyclical": "Discretionary",
    "Consumer Defensive": "Staples",
    "Utilities": "Utilities",
    "Basic Materials": "Materials",
    "Real Estate": "Real Estate",
    "Communication Services": "Comm Svcs",
}


def _map_sector(sector: str, industry: str) -> str | None:
    ind = (industry or "").lower()
    if "semicond" in ind:
        return "Semis"
    if "biotech" in ind:
        return "Biotech"
    return SECTOR_MAP.get(sector)


def compute_tilt(stock: dict, regime: dict) -> dict:
    """Return {factor, reasons} for one scored stock under the current regime."""
    if not regime or not regime.get("available"):
        return {"factor": 1.0, "reasons": []}

    mood = (regime.get("mood") or {}).get("label")
    vol = (regime.get("volatility") or {}).get("state")
    smallcap = (regime.get("smallcap") or {}).get("state")

    edge = stock.get("edge") or {}
    flow = (edge.get("flow") or {}).get("state")
    bearing = (edge.get("bearing") or {}).get("state")
    pulse = (edge.get("pulse") or {}).get("state")
    sq = stock.get("short_squeeze") or {}
    quote = stock.get("quote") or {}
    mcap = quote.get("market_cap") or 0
    is_small = 0 < mcap < 2_000_000_000

    d = 0.0
    reasons = []

    def add(delta, label):
        nonlocal d
        d += delta
        reasons.append(("+" if delta > 0 else "−") + " " + label)

    # ── Risk appetite × trend quality ──
    if mood == "RISK-OFF":
        if bearing in ("DOWN", "CHOPPY DOWN"):
            add(-0.10, "risk-off tape, weak trend")
        if flow == "CROWDED":
            add(-0.05, "risk-off, crowded")
    elif mood == "RISK-ON":
        if bearing == "CLEAN UP":
            add(0.08, "risk-on, clean uptrend")

    # ── Volatility ──
    if vol == "WILD":
        if pulse == "WILD":
            add(-0.08, "wild tape, wild stock")
        if flow == "CROWDED":
            add(-0.04, "wild, crowded")
    elif vol == "QUIET":
        if pulse == "QUIET" and bearing in ("CLEAN UP", "FLAT"):
            add(0.05, "coiled in calm tape")

    # ── Small-cap appetite (Ruben's market) ──
    if smallcap == "HOT":
        if is_small:
            add(0.08, "small-caps hot")
        if (sq.get("score") or 0) >= 60:
            add(0.06, "squeeze + hot small-caps")
    elif smallcap == "COLD":
        if is_small:
            add(-0.08, "small-caps cold")

    # ── Liquidity / trend gates ──
    if flow == "THIN":
        add(-0.05, "thin participation")
    if bearing == "DOWN":
        add(-0.06, "downtrend")

    # ── Sector tailwind (best-effort) ──
    sectors = regime.get("sectors") or []
    if sectors:
        hot = {s["name"] for s in sectors[:3]}
        cold = {s["name"] for s in sectors[-3:]}
        sname = _map_sector(quote.get("sector", ""), quote.get("industry", ""))
        if sname in hot:
            add(0.04, f"{sname} sector hot")
        elif sname in cold:
            add(-0.04, f"{sname} sector cold")

    factor = max(0.7, min(1.3, math.exp(d)))
    return {"factor": round(factor, 3), "reasons": reasons}
