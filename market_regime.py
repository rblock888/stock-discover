"""Market-level regime: mood, index trends, volatility, small-cap appetite, sector heat.

One batched yfinance download of index/ETF dailies, translated into
plain-language labels, a narrative paragraph, and actionable advice —
the hybridtrader.ai "AI Macro Desk" idea built on free data.

refresh() never raises: on failure it serves the last good payload marked
stale, so the dashboard always has something sensible to show.
"""

import logging
import threading
from datetime import datetime

import numpy as np

import db
import price_history

logger = logging.getLogger("discovery")

INDICES = ["SPY", "QQQ", "IWM"]
VIX = "^VIX"
SECTOR_NAMES = {
    "XLK": "Tech", "XLE": "Energy", "XLF": "Financials", "XLV": "Healthcare",
    "XLI": "Industrials", "XLY": "Discretionary", "XLP": "Staples",
    "XLU": "Utilities", "XLB": "Materials", "XLRE": "Real Estate",
    "XLC": "Comm Svcs", "SMH": "Semis", "XBI": "Biotech",
}
ALL_SYMBOLS = INDICES + [VIX] + list(SECTOR_NAMES)

INDEX_WEIGHTS = {"SPY": 0.5, "QQQ": 0.3, "IWM": 0.2}
INDEX_NAMES = {"SPY": "The S&P 500", "QQQ": "the Nasdaq 100", "IWM": "small caps"}

_lock = threading.Lock()
_state = {"current": None}


# ── Helpers ──────────────────────────────────────────────────────────────────

def _closes(df) -> np.ndarray | None:
    if df is None:
        return None
    try:
        c = df["Close"].to_numpy(dtype=float)
    except Exception:
        return None
    c = c[~np.isnan(c)]
    return c if len(c) >= 60 else None


def _ret(closes: np.ndarray, days: int) -> float | None:
    if len(closes) <= days:
        return None
    base = closes[-(days + 1)]
    return float(closes[-1] / base - 1.0) if base > 0 else None


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


# ── Index trend state ────────────────────────────────────────────────────────

def _trend_state(closes: np.ndarray) -> dict:
    c = float(closes[-1])
    ma20 = float(np.mean(closes[-20:]))
    ma50 = float(np.mean(closes[-50:]))
    ma20_prior = float(np.mean(closes[-30:-10]))
    slope10 = (ma20 / ma20_prior - 1.0) if ma20_prior > 0 else 0.0

    if c > ma20 and ma20 > ma50 and slope10 > 0.005:
        state, points = "UPTREND", 100
    elif c <= ma20 and c > ma50 and ma20 > ma50:
        state, points = "PULLBACK", 70
    elif c > ma20 and ma20 <= ma50:
        state, points = "RECOVERY", 55
    elif c < ma20 and ma20 < ma50 and slope10 < -0.005:
        state, points = "DOWNTREND", 10
    else:
        state, points = "CHOP", 40

    return {
        "state": state,
        "points": points,
        "close": round(c, 2),
        "vs_20ma_pct": round((c / ma20 - 1.0) * 100, 2) if ma20 > 0 else 0.0,
    }


# ── Volatility regime ────────────────────────────────────────────────────────

def _vol_regime(vix_closes: np.ndarray) -> dict:
    vix = float(vix_closes[-1])
    window = vix_closes[-253:-1] if len(vix_closes) > 253 else vix_closes[:-1]
    pctile = float(100.0 * np.sum(window < vix) / len(window)) if len(window) else 50.0
    chg5 = _ret(vix_closes, 5)

    level_score = _clamp((35.0 - vix) / (35.0 - 12.0), 0.0, 1.0) * 100.0
    vol_score = 0.5 * level_score + 0.5 * (100.0 - pctile)

    if vix >= 26 or (vix >= 21 and pctile >= 80):
        state = "WILD"
    elif vix < 14 or (vix < 17 and pctile < 30):
        state = "QUIET"
    else:
        state = "TRADABLE"

    return {
        "state": state,
        "vix": round(vix, 1),
        "percentile": round(pctile),
        "change_5d_pct": round(chg5 * 100, 1) if chg5 is not None else None,
        "score": round(vol_score, 1),
    }


# ── Small-cap appetite ───────────────────────────────────────────────────────

def _smallcap(iwm: np.ndarray | None, spy: np.ndarray) -> dict:
    if iwm is None:
        return {"state": "NEUTRAL", "score": 50.0, "rel_1m_pct": None, "rel_3m_pct": None}

    r1_i, r1_s = _ret(iwm, 21), _ret(spy, 21)
    r3_i, r3_s = _ret(iwm, 63), _ret(spy, 63)
    rel1 = (r1_i - r1_s) if (r1_i is not None and r1_s is not None) else 0.0
    rel3 = (r3_i - r3_s) if (r3_i is not None and r3_s is not None) else 0.0
    blended = 0.6 * rel1 + 0.4 * rel3
    score = _clamp(50.0 + blended * 500.0, 0.0, 100.0)

    state = "HOT" if score >= 65 else ("COLD" if score < 35 else "NEUTRAL")
    return {
        "state": state,
        "score": round(score, 1),
        "rel_1m_pct": round(rel1 * 100, 2),
        "rel_3m_pct": round(rel3 * 100, 2),
    }


# ── Narrative + advice ───────────────────────────────────────────────────────

MOOD_PHRASES = {
    "RISK-ON": "Markets are leaning risk-on",
    "NEUTRAL": "Markets are mixed",
    "RISK-OFF": "Markets are defensive",
}
INDEX_SENTENCES = {
    "UPTREND": "{name} is in a clean uptrend, {vs20:+.1f}% above its 20-day average",
    "PULLBACK": "{name} is pulling back within an uptrend",
    "RECOVERY": "{name} is recovering, back above a still-flat 20-day average",
    "DOWNTREND": "{name} is in a downtrend",
    "CHOP": "{name} is chopping sideways",
}
VOL_SENTENCES = {
    "WILD": "Volatility is elevated — VIX {vix:.0f}, higher than {pctile:.0f}% of readings this past year.",
    "TRADABLE": "Volatility is workable — VIX {vix:.0f} ({pctile_ord} percentile of the past year).",
    "QUIET": "Volatility is low — VIX {vix:.0f}, calmer than most of the past year.",
}
STATE_PHRASES = {
    "UPTREND": "in an uptrend",
    "PULLBACK": "pulling back",
    "RECOVERY": "recovering",
    "DOWNTREND": "in a downtrend",
    "CHOP": "chopping sideways",
}
INDEX_VERBS = {"SPY": "is", "QQQ": "is", "IWM": "are"}


def _ordinal(n: float) -> str:
    n = int(round(n))
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"
SMALLCAP_SENTENCES = {
    "HOT": "Small caps are outrunning large caps ({rel1m:+.1f}% vs SPY over a month) — risk appetite is reaching down the cap scale.",
    "NEUTRAL": "Small caps are tracking large caps ({rel1m:+.1f}% vs SPY over a month).",
    "COLD": "Small caps are lagging large caps ({rel1m:+.1f}% vs SPY over a month) — risk appetite is thin where you hunt.",
}

ADVICE_BY_MOOD = {
    "RISK-ON": [
        "Favor breakouts and adding on strength — this tape forgives mistakes.",
        "Run normal position sizes and let winners breathe.",
    ],
    "NEUTRAL": [
        "Mixed tape — be selective and demand confirmation before committing.",
        "Keep some powder dry; this is a stock-picker's market, not a beta market.",
    ],
    "RISK-OFF": [
        "Protect capital first: smaller size, tighter stops, more cash.",
        "Focus on the strongest names holding up — they lead when the turn comes.",
    ],
}
ADVICE_BY_VOL = {
    "WILD": ["Wide ranges: halve size or widen stops — not both legs of normal."],
    "TRADABLE": ["Normal volatility — standard stop distances have room to work."],
    "QUIET": ["Compression cuts both ways — keep alerts on for the expansion day."],
}
ADVICE_BY_SMALLCAP = {
    "HOT": ["Small caps have the wind at their back — microcap breakouts carry better odds."],
    "NEUTRAL": ["No small-cap tailwind — let each setup prove itself on volume."],
    "COLD": ["Small caps lag: expect microcap breakouts to fail more often — demand volume confirmation."],
}
COMBO_OVERRIDES = {
    ("RISK-OFF", "WILD"): [
        "Defense mode: this is a capital-preservation tape, not an opportunity tape.",
        "If you trade at all, quarter size and quick exits.",
        "Build the shopping list — the best entries come after stretches like this.",
    ],
    ("RISK-ON", "QUIET"): [
        "Calm uptrend: breakout entries beat chasing — moves develop slowly.",
        "Run normal size; add on strength while volatility stays compressed.",
    ],
}


def _narrative(label: str, mood: float, indices: dict, vol: dict, small: dict, sectors: list) -> str:
    parts = [f"{MOOD_PHRASES[label]} (mood {mood:.0f}/100)."]

    spy = indices.get("SPY")
    if spy:
        parts.append(
            INDEX_SENTENCES[spy["state"]].format(name=INDEX_NAMES["SPY"], vs20=spy["vs_20ma_pct"]) + "."
        )
    others = []
    for sym in ("QQQ", "IWM"):
        ix = indices.get(sym)
        if ix:
            others.append(f"{INDEX_NAMES[sym]} {INDEX_VERBS[sym]} {STATE_PHRASES[ix['state']]}")
    if others:
        sentence = " and ".join(others) + "."
        parts.append(sentence[0].upper() + sentence[1:])

    parts.append(VOL_SENTENCES[vol["state"]].format(
        vix=vol["vix"], pctile=vol["percentile"], pctile_ord=_ordinal(vol["percentile"]),
    ))
    if small.get("rel_1m_pct") is not None:
        parts.append(SMALLCAP_SENTENCES[small["state"]].format(rel1m=small["rel_1m_pct"]))
    if sectors:
        top = ", ".join(s["name"] for s in sectors[:3])
        bottom = sectors[-1]["name"]
        parts.append(f"Strongest groups: {top}; weakest: {bottom}.")

    return " ".join(parts)


def _advice(label: str, vol_state: str, small_state: str) -> list:
    override = COMBO_OVERRIDES.get((label, vol_state))
    if override:
        return list(override)
    bullets = [
        ADVICE_BY_MOOD[label][0],
        ADVICE_BY_VOL[vol_state][0],
        ADVICE_BY_SMALLCAP[small_state][0],
        ADVICE_BY_MOOD[label][1],
    ]
    return bullets[:4]


# ── Public API ───────────────────────────────────────────────────────────────

def compute(breadth_universe_pct: float | None = None, universe_n: int | None = None) -> dict:
    """Fetch + compute the full regime payload. Raises on missing SPY/VIX."""
    data = price_history.get_histories(ALL_SYMBOLS, period="1y")

    spy = _closes(data.get("SPY"))
    vix_closes = _closes(data.get(VIX))
    if spy is None or vix_closes is None:
        raise RuntimeError("market_regime: SPY or ^VIX data unavailable")

    # Index trends (renormalize weights over what's present)
    indices = {}
    comp, total_w = 0.0, 0.0
    for sym in INDICES:
        closes = _closes(data.get(sym))
        if closes is None:
            continue
        t = _trend_state(closes)
        r1 = _ret(closes, 21)
        t["ret_1m_pct"] = round(r1 * 100, 2) if r1 is not None else None
        indices[sym] = t
        comp += INDEX_WEIGHTS[sym] * t["points"]
        total_w += INDEX_WEIGHTS[sym]
    index_component = comp / total_w if total_w > 0 else 50.0

    vol = _vol_regime(vix_closes)
    small = _smallcap(_closes(data.get("IWM")), spy)

    # Sector heat
    sectors = []
    for etf, name in SECTOR_NAMES.items():
        closes = _closes(data.get(etf))
        if closes is None:
            continue
        r1, r5 = _ret(closes, 21), _ret(closes, 5)
        sectors.append({
            "etf": etf,
            "name": name,
            "ret_1m_pct": round(r1 * 100, 2) if r1 is not None else None,
            "ret_5d_pct": round(r5 * 100, 2) if r5 is not None else None,
            "above_20ma": bool(closes[-1] > np.mean(closes[-20:])),
        })
    sectors.sort(key=lambda s: s["ret_1m_pct"] if s["ret_1m_pct"] is not None else -999, reverse=True)
    sector_breadth = round(100.0 * sum(s["above_20ma"] for s in sectors) / len(sectors), 1) if sectors else 50.0

    mood = (
        0.35 * index_component
        + 0.25 * vol["score"]
        + 0.20 * small["score"]
        + 0.20 * sector_breadth
    )
    label = "RISK-ON" if mood >= 65 else ("RISK-OFF" if mood < 40 else "NEUTRAL")

    return {
        "available": True,
        "as_of": datetime.now().isoformat(),
        "stale": False,
        "mood": {"score": round(mood, 1), "label": label},
        "indices": indices,
        "volatility": vol,
        "smallcap": small,
        "sectors": sectors,
        "breadth": {
            "universe_pct": breadth_universe_pct,
            "universe_n": universe_n,
            "sectors_pct": sector_breadth,
        },
        "narrative": _narrative(label, mood, indices, vol, small, sectors),
        "advice": _advice(label, vol["state"], small["state"]),
        "strip": _strip_safe(),
    }


def _strip_safe() -> list:
    try:
        return db.get_regime_strip(10)
    except Exception:
        return []


def refresh(breadth_universe_pct: float | None = None, universe_n: int | None = None) -> dict:
    """Compute + cache + persist daily snapshot. Never raises."""
    try:
        payload = compute(breadth_universe_pct, universe_n)
        with _lock:
            _state["current"] = payload
        try:
            db.save_regime_snapshot({
                "mood_score": payload["mood"]["score"],
                "label": payload["mood"]["label"],
                "vix": payload["volatility"]["vix"],
                "vix_pctile": payload["volatility"]["percentile"],
                "smallcap_score": payload["smallcap"]["score"],
                "breadth_universe": breadth_universe_pct,
                "breadth_sectors": payload["breadth"]["sectors_pct"],
            })
        except Exception as e:
            logger.error(f"market_regime: snapshot save failed: {e}")
        logger.info(
            f"Market regime: {payload['mood']['label']} {payload['mood']['score']} "
            f"(VIX {payload['volatility']['vix']}, smallcap {payload['smallcap']['state']})"
        )
        return payload
    except Exception as e:
        logger.error(f"market_regime refresh failed: {e}")
        with _lock:
            current = _state.get("current")
            if current:
                current = {**current, "stale": True}
                _state["current"] = current
                return current
        return {"available": False}


def get_cached() -> dict:
    with _lock:
        return _state.get("current") or {"available": False}
