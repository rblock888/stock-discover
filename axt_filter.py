"""
AXT-Style Microcap Filter
=========================
Finds compound semiconductor / photonics / advanced packaging micro-caps
positioned for AI-driven supply chain rerating.

AXT thesis: an upstream materials supplier gets reclassified from
"boring industrial" to "AI supply chain critical" and reprices 5-10x.
The move comes from reclassification, not growth.

Scores 5 filters + detects early warning signals:
  1. Stack Position      — how upstream/critical in AI optics supply chain
  2. Market Cap Fit      — $50M–$300M sweet spot (below repricing radar)
  3. Revenue Profile     — real industrial revenue, no narrative premium yet
  4. Supply Chain Depth  — touches III-V materials, photonics, packaging
  5. Capacity Signal     — language of constraint or expansion in recent news
"""

import logging
import fmp

logger = logging.getLogger("axt_filter")

# ─── Keyword sets ────────────────────────────────────────────────────────────

_TIER1_STACK = [
    "compound semiconductor", "iii-v", "gaas", "inp", "gan", "ingaas",
    "indium phosphide", "gallium arsenide", "gallium nitride",
    "substrate", "epitaxy", "epitaxial", "wafer growth", "crystal growth",
    "metalorganic", "mocvd", "molecular beam epitaxy", "mbe ",
]

_TIER2_STACK = [
    "photonic", "photonics", "optical interconnect", "co-packaged optics",
    "silicon photonic", "optical transceiver", "laser diode", "vcsel",
    "indium ", "gallium ", "epi wafer", "optical packaging",
    "photonic integration", "compound semi",
]

_TIER3_STACK = [
    "advanced packaging", "chiplet", "die attach", "wire bond",
    "flip chip", "wafer level package", "semiconductor inspection",
    "metrology", "laser component", "optical fiber",
    "infrared detector", "optoelectronic",
]

_SUPPLY_CHAIN_KEYWORDS = [
    "indium", "gallium", "antimony",
    "iii-v", "compound semiconductor", "epitax",
    "photonic interconnect", "optical interconnect", "co-packaged",
    "substrate material", "wafer substrate",
    "laser component", "vcsel", "laser diode",
    "packaging yield", "interconnect density",
    "optical module", "transceiver module", "photovoltaic junction",
]

_CAPACITY_SIGNAL_KEYWORDS = [
    # Constraint language — pre-rerating signal
    "fully allocated", "capacity constrained", "extended lead time",
    "supply constrained", "demand exceeds", "backlog",
    "booked through", "sold out", "waitlist", "allocation",
    # Expansion language — rerating trigger
    "expanding capacity", "capacity expansion", "new production line",
    "additional capacity", "increase capacity", "capacity investment",
    "qualification complete", "design win", "multi-year agreement",
    "long-term supply", "strategic supply", "new fab",
    # Revenue inflection language
    "record revenue", "strong demand", "growing demand",
    "customer qualification", "ramp", "production ramp",
]

_NARRATIVE_PREMIUM_KEYWORDS = [
    # These indicate the rerating narrative may already be priced in
    "ai chip", "artificial intelligence supplier", "nvidia partner",
    "ai infrastructure play", "generative ai leader",
    "ai revolution", "chatgpt", "llm supplier",
]

_UPSTREAM_SECTORS = [
    "semiconductor equipment", "electronic components", "specialty chemicals",
    "optical", "photonic", "semiconductor materials", "scientific instruments",
    "semiconductor", "electronic manufacturing",
]

# ─── Default seed universe ────────────────────────────────────────────────────

AXT_SEED_UNIVERSE = [
    "EMKR",  # Emcore Corp — GaAs/InP compound semi for fiber optics & defense
    "AAOI",  # Applied Optoelectronics — GaAs/InP for broadband/datacom transceivers
    "AEHR",  # Aehr Test Systems — GaN/SiC wafer-level burn-in test
    "ACMR",  # ACM Research — wafer cleaning & processing tools
    "CAMT",  # Camtek — advanced packaging inspection & metrology
    "AMSC",  # American Superconductor — power electronics & grid
    "KLIC",  # Kulicke & Soffa — wire bonding & advanced packaging equipment
    "FORM",  # FormFactor — wafer probe systems & metrology
    "ONTO",  # Onto Innovation — optical inspection & metrology
    "UCTT",  # Ultra Clean Holdings — semiconductor process supply chain
    "COHU",  # Cohu — semiconductor test handlers & contactors
    "VIAV",  # Viavi Solutions — photonics test & measurement
    "AXT",   # AXT Inc — reference company: InP/GaAs substrates
    "MTSI",  # MACOM Technology — GaAs/InP/GaN components for optical
    "ALGM",  # Allegro MicroSystems — magnetic sensing / compound semi adjacent
]


# ─── Internal helpers ─────────────────────────────────────────────────────────

def _match(text: str, keywords: list) -> list:
    t = text.lower()
    return [kw for kw in keywords if kw in t]


def _stack_position(description: str, sector: str, industry: str) -> tuple:
    text = f"{description} {sector} {industry}"
    t1 = len(_match(text, _TIER1_STACK))
    t2 = len(_match(text, _TIER2_STACK))
    t3 = len(_match(text, _TIER3_STACK))

    raw = min(100, t1 * 35 + t2 * 20 + t3 * 10)
    sector_bonus = 10 if _match(f"{sector} {industry}", _UPSTREAM_SECTORS) else 0
    score = min(100, raw + sector_bonus)

    if t1 >= 2:
        layer = "Compound Semi Materials"
    elif t1 >= 1 or t2 >= 2:
        layer = "Photonics Components"
    elif t2 >= 1 or t3 >= 2:
        layer = "Adv. Packaging / Test"
    else:
        layer = "General Semi"

    return score, layer


def _market_cap(mcap: float) -> tuple:
    if mcap <= 0:
        return 50, "Unknown"
    m = mcap / 1e6
    if 50 <= m <= 300:
        return 100, f"${m:.0f}M (sweet spot)"
    elif 300 < m <= 500:
        return 65, f"${m:.0f}M (upper range)"
    elif 30 <= m < 50:
        return 70, f"${m:.0f}M (lower range)"
    elif 500 < m <= 1_000:
        return 35, f"${m:.0f}M (too large)"
    elif m > 1_000:
        return 10, f"${m/1000:.1f}B (likely repriced)"
    else:
        return 40, f"${m:.0f}M (distressed)"


def _revenue_profile(income: list, sector: str, industry: str) -> tuple:
    if not income:
        return 30, "No revenue data"

    revenues = [q.get("revenue", 0) for q in income[:6] if (q.get("revenue") or 0) > 0]
    if not revenues:
        return 20, "Pre-revenue"

    latest = revenues[0]
    if latest < 1_000_000:
        return 25, f"Early-stage ${latest/1e6:.1f}M/Q"

    score = 50
    label = f"${latest/1e6:.0f}M/Q"
    if len(revenues) >= 4:
        year_ago = revenues[3]
        if year_ago > 0:
            growth = (latest - year_ago) / abs(year_ago)
            if 0.05 <= growth <= 0.30:
                score = 90
                label = f"{growth:.0%} YoY (industrial steady)"
            elif growth > 0.30:
                score = 55
                label = f"{growth:.0%} YoY (may be known)"
            elif growth > 0:
                score = 70
                label = f"{growth:.0%} YoY"
            else:
                score = 35
                label = f"{growth:.0%} YoY (declining)"

    ind_text = f"{sector} {industry}".lower()
    if any(s in ind_text for s in ["electronic", "semiconductor", "optical", "photonic", "instrument"]):
        score = min(100, score + 10)

    return score, label


def _supply_chain(description: str, headlines: list) -> tuple:
    text = description + " " + " ".join(headlines)
    hits = _match(text, _SUPPLY_CHAIN_KEYWORDS)
    score = min(100, len(hits) * 20)
    return score, list(set(hits))[:6]


def _capacity_signal(headlines: list, description: str) -> tuple:
    text = " ".join(headlines) + " " + description
    hits = _match(text, _CAPACITY_SIGNAL_KEYWORDS)
    score = min(100, len(hits) * 20)
    return score, list(set(hits))[:6]


def _fetch_headlines(ticker: str) -> list:
    try:
        import yfinance as yf
        news = yf.Ticker(ticker).news or []
        out = []
        for item in news[:20]:
            content = item.get("content") or item
            title = content.get("title", "") or item.get("title", "")
            summary = content.get("summary", "") or item.get("summary", "") or ""
            out.append(f"{title} {summary[:150]}")
        return out
    except Exception:
        return []


# ─── Public API ──────────────────────────────────────────────────────────────

def score(ticker: str) -> dict:
    """
    Run the AXT filter on a single ticker.
    Returns rerate_score (0–100) + full filter breakdown.
    """
    # Fetch market data
    if fmp.is_configured():
        quote = fmp.get_quote(ticker)
        income = fmp.get_income_statement(ticker, limit=8)
    else:
        try:
            import yfinance as yf
            info = yf.Ticker(ticker).info or {}
            quote = {
                "price": info.get("currentPrice") or info.get("regularMarketPrice", 0),
                "marketCap": info.get("marketCap", 0),
                "sector": info.get("sector", ""),
                "industry": info.get("industry", ""),
                "description": info.get("longBusinessSummary", ""),
                "companyName": info.get("shortName", ticker),
                "name": info.get("shortName", ticker),
            }
            income = []
        except Exception:
            quote, income = {}, []

    description = (quote.get("description") or quote.get("longBusinessSummary") or "")
    sector = quote.get("sector", "") or ""
    industry = quote.get("industry", "") or ""
    mcap = quote.get("marketCap", 0) or quote.get("mktCap", 0) or 0
    name = quote.get("name") or quote.get("companyName", ticker)

    headlines = _fetch_headlines(ticker)

    # Run 5 filters
    stack_score, stack_layer = _stack_position(description, sector, industry)
    mcap_score, mcap_label = _market_cap(mcap)
    revenue_score, revenue_label = _revenue_profile(income, sector, industry)
    supply_score, supply_hits = _supply_chain(description, headlines)
    capacity_score, capacity_hits = _capacity_signal(headlines, description)

    # Narrative premium penalty — discount if already widely known as AI play
    narrative_hits = _match(" ".join(headlines[:10]) + description, _NARRATIVE_PREMIUM_KEYWORDS)
    narrative_penalty = min(25, len(narrative_hits) * 10)

    rerate_score = max(0, min(100, round(
        stack_score * 0.30 +
        mcap_score * 0.20 +
        revenue_score * 0.15 +
        supply_score * 0.20 +
        capacity_score * 0.15 -
        narrative_penalty,
        1,
    )))

    filters = {
        "stack_position": {
            "score": stack_score,
            "label": stack_layer,
            "pass": stack_score >= 40,
        },
        "market_cap": {
            "score": mcap_score,
            "label": mcap_label,
            "pass": mcap_score >= 60,
        },
        "revenue_profile": {
            "score": revenue_score,
            "label": revenue_label,
            "pass": revenue_score >= 50,
        },
        "supply_chain": {
            "score": supply_score,
            "label": f"{len(supply_hits)} supply chain keywords" if supply_hits else "No keywords matched",
            "hits": supply_hits,
            "pass": supply_score >= 30,
        },
        "capacity_signal": {
            "score": capacity_score,
            "label": f"{len(capacity_hits)} signals detected" if capacity_hits else "No signals in news",
            "hits": capacity_hits,
            "pass": capacity_score >= 20,
        },
    }

    filters_passed = sum(1 for f in filters.values() if f["pass"])

    # Shortlist if passes ≥3 filters AND rerate_score ≥ 40
    is_candidate = filters_passed >= 3 and rerate_score >= 40

    return {
        "ticker": ticker,
        "name": name,
        "rerate_score": rerate_score,
        "stack_layer": stack_layer,
        "filters": filters,
        "filters_passed": filters_passed,
        "is_candidate": is_candidate,
        "narrative_penalty": narrative_penalty,
        "narrative_hits": narrative_hits,
        "supply_hits": supply_hits,
        "capacity_hits": capacity_hits,
        "market_cap": mcap,
        "sector": sector,
        "industry": industry,
        "price": quote.get("price", 0),
    }
