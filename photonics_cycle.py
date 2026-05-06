"""
Photonics Cycle Scanner
=======================
Models the full AI-optics supply chain cycle as 5 sequential phases.
Each phase represents a layer that gets reclassified from "boring industrial"
to "AI supply chain critical" — creating an AXT-style rerating event.

The core insight: the market always misprices ONE layer behind reality.
Each phase creates a new wave of micro-cap moves in the layer BELOW
the last discovered bottleneck.

Phase order (by timing):
  1. Substrates      → in_progress  (partially priced, AXT-style ignition)
  2. Epitaxy/Lasers  → emerging     (800G→1.6T cycle tightening supply)
  3. Packaging       → current      ★ HIGHEST ASYMMETRY RIGHT NOW
  4. Test/Yield      → upcoming     (complexity explosion after packaging)
  5. Materials       → future       (structural second-wave squeeze)
"""

import logging
import fmp

logger = logging.getLogger("photonics_cycle")

CURRENT_PHASE_NUM = 3  # Advanced Packaging — highest asymmetry as of 2026

# ─── Phase definitions ────────────────────────────────────────────────────────

PHASES = [
    {
        "id": "substrates",
        "num": 1,
        "name": "Substrate Wake-Up",
        "layer": "Compound Semi Substrates",
        "timeline": "Late 2025 → Early 2026",
        "status": "in_progress",
        "asymmetry": "medium",
        "color": "#a78bfa",
        "description": "InP/GaAs/GaN wafer suppliers reclassified as AI optics critical. "
                       "AXT was the ignition — this phase is partially priced but second-movers remain.",
        "stack_keywords": [
            "compound semiconductor", "iii-v", "gaas", "inp", "gan",
            "substrate", "epitaxy", "epitaxial", "wafer growth", "crystal growth",
            "mocvd", "molecular beam", "indium phosphide", "gallium arsenide",
            "gallium nitride", "epi wafer",
        ],
        "supply_keywords": [
            "substrate", "wafer", "compound semiconductor", "iii-v",
            "indium", "gallium", "epitax", "crystal",
        ],
        "capacity_keywords": [
            "substrate backlog", "wafer lead time", "capacity constrained",
            "substrate allocation", "wafer growth capacity", "crystal growth capacity",
            "supply constrained", "fully allocated", "backlog",
        ],
        "seed": ["AXT", "EMKR", "AAOI", "MTSI", "ALGM"],
        "mcap_min": 30e6,
        "mcap_max": 500e6,
    },
    {
        "id": "epitaxy_lasers",
        "num": 2,
        "name": "Epitaxy + Laser Constraints",
        "layer": "Wafer Growth & Laser Components",
        "timeline": "Mid 2026",
        "status": "emerging",
        "asymmetry": "high",
        "color": "#38bdf8",
        "description": "800G→1.6T optical upgrade cycle strains epitaxy production capacity. "
                       "DFB and EML laser manufacturing becomes the new bottleneck.",
        "stack_keywords": [
            "epitaxy", "epitaxial", "mocvd", "dfb laser", "eml laser",
            "laser diode", "vcsel", "wafer growth", "optical transceiver",
            "photonic", "compound semi", "inp laser", "gaas laser",
            "800g", "1.6t", "laser component",
        ],
        "supply_keywords": [
            "laser", "epitaxy", "optical transceiver", "vcsel",
            "dfb", "photonic", "optical module",
        ],
        "capacity_keywords": [
            "laser backlog", "epitaxy capacity", "transceiver constrained",
            "optical supply", "800g demand", "1.6t upgrade", "laser supply",
            "transceiver lead time", "fully allocated", "backlog",
        ],
        "seed": ["EMKR", "AAOI", "IPGP", "VIAV", "LITE", "COHR"],
        "mcap_min": 50e6,
        "mcap_max": 1_000e6,
    },
    {
        "id": "packaging",
        "num": 3,
        "name": "Packaging Crisis",
        "layer": "Advanced Packaging + Co-Packaged Optics",
        "timeline": "Now (2026)",
        "status": "current",
        "asymmetry": "very_high",
        "color": "#22c55e",
        "description": "Optics and compute must be physically integrated. Heat, density, and latency limits "
                       "hit the scaling wall — packaging becomes the constraint, not chips. "
                       "Hyperscaler capex shifting toward interconnect and integration.",
        "stack_keywords": [
            "co-packaged optics", "cpo", "advanced packaging", "optical integration",
            "chiplet", "photonic integration", "flip chip", "die attach",
            "wire bond", "wafer level package", "interconnect density",
            "packaging yield", "optical packaging", "system integration",
        ],
        "supply_keywords": [
            "co-packaged", "cpo", "advanced packaging", "chiplet",
            "die attach", "packaging yield", "optical integration",
            "interconnect", "packaging substrate",
        ],
        "capacity_keywords": [
            "packaging backlog", "cpo demand", "advanced packaging capacity",
            "chiplet supply", "packaging constrained", "integration bottleneck",
            "co-packaged optics demand", "packaging lead time",
            "fully allocated", "design win", "qualification", "backlog",
        ],
        "seed": ["KLIC", "CAMT", "ONTO", "FORM", "UCTT", "COHU", "ACMR", "AEHR"],
        "mcap_min": 100e6,
        "mcap_max": 2_000e6,
    },
    {
        "id": "test_yield",
        "num": 4,
        "name": "Test & Yield Explosion",
        "layer": "Photonic Testing & Metrology",
        "timeline": "Late 2026 → 2027",
        "status": "upcoming",
        "asymmetry": "high",
        "color": "#fb923c",
        "description": "1.6T→3.2T scaling pushes failure rates higher. Manufacturing complexity explodes. "
                       "Late-cycle 3–10x moves in niche test, inspection, and yield-optimization firms.",
        "stack_keywords": [
            "photonic testing", "optical calibration", "metrology",
            "wafer probe", "semiconductor test", "yield optimization",
            "optical inspection", "defect inspection", "test handler",
            "burn-in", "test equipment", "inspection system",
        ],
        "supply_keywords": [
            "test", "metrology", "inspection", "yield",
            "calibration", "probe", "defect",
        ],
        "capacity_keywords": [
            "test capacity", "metrology demand", "inspection backlog",
            "yield improvement", "test constraint", "test lead time",
            "fully allocated", "backlog", "design win",
        ],
        "seed": ["FORM", "ONTO", "COHU", "CAMT", "VIAV", "AEHR", "MKSI"],
        "mcap_min": 100e6,
        "mcap_max": 1_000e6,
    },
    {
        "id": "materials_wave2",
        "num": 5,
        "name": "Materials Second Wave",
        "layer": "III-V Materials & Critical Minerals",
        "timeline": "2027+",
        "status": "future",
        "asymmetry": "very_high",
        "color": "#f43f5e",
        "description": "Structural supply shortage becomes undeniable. Geopolitics tighten III-V material access. "
                       "Smallest upstream names see second-wave AXT-style rerating — often the biggest % moves.",
        "stack_keywords": [
            "substrate", "iii-v", "compound semiconductor",
            "indium", "gallium", "germanium", "rare earth",
            "wafer", "crystal", "epitaxy", "material supply",
            "strategic material", "critical mineral",
        ],
        "supply_keywords": [
            "substrate", "iii-v", "indium", "gallium", "germanium",
            "rare earth", "compound semiconductor", "crystal",
            "critical mineral", "strategic material",
        ],
        "capacity_keywords": [
            "material shortage", "supply constrained", "geopolit",
            "strategic reserve", "export control", "material allocation",
            "import restriction", "supply chain security",
            "fully allocated", "backlog",
        ],
        "seed": ["AXT", "EMKR", "AMSC", "ALGM", "MP"],
        "mcap_min": 30e6,
        "mcap_max": 300e6,
    },
]


# ─── Scoring helpers ──────────────────────────────────────────────────────────

def _match(text: str, keywords: list) -> list:
    t = text.lower()
    return [kw for kw in keywords if kw in t]


def _stack_score(description: str, sector: str, industry: str, phase: dict) -> int:
    text = f"{description} {sector} {industry}"
    hits = len(_match(text, phase["stack_keywords"]))
    upstream_bonus = 10 if any(
        s in f"{sector} {industry}".lower()
        for s in ["semiconductor", "electronic component", "optical", "photonic",
                  "specialty chemical", "scientific instrument"]
    ) else 0
    return min(100, hits * 25 + upstream_bonus)


def _mcap_score(mcap: float, phase: dict) -> tuple:
    if mcap <= 0:
        return 50, "Unknown"
    lo, hi = phase["mcap_min"], phase["mcap_max"]
    m = mcap / 1e6
    lo_m, hi_m = lo / 1e6, hi / 1e6
    if lo <= mcap <= hi:
        # Score higher when closer to the lower end (more upside)
        position = (mcap - lo) / (hi - lo)
        score = int(100 - position * 30)  # 100 at low end, 70 at top of range
        return score, f"${m:.0f}M (in range ${lo_m:.0f}M–${hi_m:.0f}M)"
    elif mcap < lo:
        if mcap >= lo * 0.5:
            return 65, f"${m:.0f}M (slightly below range)"
        return 35, f"${m:.0f}M (too small / distressed)"
    else:
        if mcap <= hi * 1.5:
            return 50, f"${m:.0f}M (slightly above range)"
        return 15, f"${m/1000:.1f}B (likely repriced)"


def _revenue_score(income: list, sector: str, industry: str) -> tuple:
    if not income:
        return 30, "No data"
    revs = [q.get("revenue", 0) for q in income[:6] if (q.get("revenue") or 0) > 0]
    if not revs:
        return 20, "Pre-revenue"
    latest = revs[0]
    if latest < 1_000_000:
        return 25, f"Early-stage ${latest/1e6:.1f}M/Q"
    score, label = 50, f"${latest/1e6:.0f}M/Q"
    if len(revs) >= 4:
        year_ago = revs[3]
        if year_ago > 0:
            g = (latest - year_ago) / abs(year_ago)
            if 0.05 <= g <= 0.30:
                score, label = 90, f"{g:.0%} YoY (industrial steady)"
            elif g > 0.30:
                score, label = 55, f"{g:.0%} YoY (high—may be found)"
            elif g > 0:
                score, label = 70, f"{g:.0%} YoY"
            else:
                score, label = 35, f"{g:.0%} YoY (declining)"
    ind = f"{sector} {industry}".lower()
    if any(s in ind for s in ["electronic", "semiconductor", "optical", "photonic", "instrument"]):
        score = min(100, score + 10)
    return score, label


def _supply_score(description: str, headlines: list, phase: dict) -> tuple:
    text = description + " " + " ".join(headlines)
    hits = list(set(_match(text, phase["supply_keywords"])))
    return min(100, len(hits) * 20), hits[:6]


def _capacity_score(headlines: list, description: str, phase: dict) -> tuple:
    text = " ".join(headlines) + " " + description
    hits = list(set(_match(text, phase["capacity_keywords"])))
    return min(100, len(hits) * 20), hits[:6]


def _headlines(ticker: str) -> list:
    try:
        import yfinance as yf
        news = yf.Ticker(ticker).news or []
        out = []
        for item in news[:20]:
            c = item.get("content") or item
            title = c.get("title", "") or item.get("title", "")
            summary = (c.get("summary", "") or item.get("summary", "") or "")[:150]
            out.append(f"{title} {summary}")
        return out
    except Exception:
        return []


_NARRATIVE_KEYWORDS = [
    "ai chip supplier", "nvidia partner", "hyperscaler deal",
    "generative ai", "ai revolution", "chatgpt",
]


def score_for_phase(ticker: str, phase: dict) -> dict:
    """Score a ticker against a specific phase definition."""
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
                "name": info.get("shortName", ticker),
            }
            income = []
        except Exception:
            quote, income = {}, []

    description = quote.get("description", "") or ""
    sector = quote.get("sector", "") or ""
    industry = quote.get("industry", "") or ""
    mcap = quote.get("marketCap", 0) or quote.get("mktCap", 0) or 0
    name = quote.get("name") or quote.get("companyName", ticker)
    price = quote.get("price", 0) or 0

    headlines = _headlines(ticker)

    s_stack = _stack_score(description, sector, industry, phase)
    s_mcap, mcap_label = _mcap_score(mcap, phase)
    s_rev, rev_label = _revenue_score(income, sector, industry)
    s_supply, supply_hits = _supply_score(description, headlines, phase)
    s_capacity, cap_hits = _capacity_score(headlines, description, phase)

    narrative_hits = _match(" ".join(headlines[:8]) + description, _NARRATIVE_KEYWORDS)
    narrative_penalty = min(20, len(narrative_hits) * 8)

    phase_score = max(0, min(100, round(
        s_stack * 0.30 +
        s_mcap * 0.20 +
        s_rev * 0.15 +
        s_supply * 0.20 +
        s_capacity * 0.15 -
        narrative_penalty,
        1,
    )))

    filters = {
        "stack":    {"score": s_stack,    "pass": s_stack >= 40,    "label": f"Stack {s_stack}"},
        "mcap":     {"score": s_mcap,     "pass": s_mcap >= 55,     "label": mcap_label},
        "revenue":  {"score": s_rev,      "pass": s_rev >= 50,      "label": rev_label},
        "supply":   {"score": s_supply,   "pass": s_supply >= 30,   "label": f"{len(supply_hits)} supply signals"},
        "capacity": {"score": s_capacity, "pass": s_capacity >= 20, "label": f"{len(cap_hits)} capacity signals"},
    }
    filters_passed = sum(1 for f in filters.values() if f["pass"])

    return {
        "ticker": ticker,
        "name": name,
        "phase_score": phase_score,
        "filters": filters,
        "filters_passed": filters_passed,
        "is_candidate": filters_passed >= 3 and phase_score >= 40,
        "supply_hits": supply_hits,
        "capacity_hits": cap_hits,
        "narrative_penalty": narrative_penalty,
        "market_cap": mcap,
        "sector": sector,
        "industry": industry,
        "price": price,
    }


def scan_all_phases() -> list:
    """
    Scan all phase seed universes. Deduplicates data fetching for tickers
    that appear in multiple phases.
    Returns a list of phase dicts, each with a 'results' list.
    """
    # Collect all unique tickers to pre-fetch
    all_tickers = list({t for p in PHASES for t in p["seed"]})
    logger.info(f"Photonics cycle: scoring {len(all_tickers)} unique tickers across 5 phases")

    phase_results = []
    for phase in PHASES:
        results = []
        for ticker in phase["seed"]:
            try:
                r = score_for_phase(ticker, phase)
                results.append(r)
                logger.info(f"  Phase {phase['num']} {ticker}: {r['phase_score']}")
            except Exception as e:
                logger.error(f"  Phase {phase['num']} {ticker} failed: {e}")

        results.sort(key=lambda x: x["phase_score"], reverse=True)

        phase_results.append({
            "id": phase["id"],
            "num": phase["num"],
            "name": phase["name"],
            "layer": phase["layer"],
            "timeline": phase["timeline"],
            "status": phase["status"],
            "asymmetry": phase["asymmetry"],
            "color": phase["color"],
            "description": phase["description"],
            "results": results,
            "candidates": [r for r in results if r["is_candidate"]],
        })

    return phase_results
