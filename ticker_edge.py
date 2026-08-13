"""Per-ticker trading-regime gauges: FLOW / BEARING / PULSE.

Translates raw price/volume state into plain-language labels with concrete
advice, in the spirit of hybridtrader.ai's per-asset gauges:

  FLOW    — participation:  THIN / HEALTHY / CROWDED   (relative volume)
  BEARING — trend quality:  CLEAN UP / CHOPPY UP / FLAT / CHOPPY DOWN / DOWN
  PULSE   — volatility:     QUIET / TRADABLE / WILD    (ATR% + BB width)

Pure pandas/numpy on an already-fetched daily history frame — no network.
compute() never raises; callers get {"available": False} on any problem.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np

import config

ET = ZoneInfo("America/New_York")


def _piecewise(x: float, points: list) -> float:
    """Linear interpolation over [(x0,y0), ...]; clamps outside the range."""
    if x <= points[0][0]:
        return points[0][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return points[-1][1]


def _percentile_of_last(series: np.ndarray) -> float:
    """% of trailing values strictly below the last value (0-100)."""
    valid = series[~np.isnan(series)]
    if len(valid) < 2:
        return 50.0
    window = valid[-253:-1] if len(valid) > 253 else valid[:-1]
    if len(window) == 0:
        return 50.0
    return float(100.0 * np.sum(window < valid[-1]) / len(window))


# ── FLOW ─────────────────────────────────────────────────────────────────────

FLOW_SUMMARY = {
    "THIN": "Low participation — price can drift on little volume",
    "HEALTHY": "Normal participation — orderly two-way trade",
    "CROWDED": "Very high participation — move may be extended",
}
FLOW_ADVICE = {
    "THIN": [
        "Volume is {rvol:.1f}x the 20-day average — moves here reverse easily.",
        "Use limit orders; spreads eat market orders in thin tape.",
    ],
    "HEALTHY": [
        "Participation is normal ({rvol:.1f}x average) — signals carry their usual weight.",
        "Standard entries and exits apply.",
    ],
    "CROWDED": [
        "Volume is {rvol:.1f}x average — everyone is watching this right now.",
        "Good for momentum, bad for chasing: late entries get the worst prices.",
    ],
}


def _session_factor(last_bar_ts) -> float:
    """Scale today's partial-session volume up to a full-day estimate.

    Linear in elapsed session minutes — understates the U-shaped open
    profile, but plenty for 3-way banding.
    """
    try:
        now = datetime.now(ET)
        ts_date = last_bar_ts.date() if hasattr(last_bar_ts, "date") else None
        if ts_date != now.date() or now.hour >= 16:
            return 1.0
        open_t = now.replace(hour=9, minute=30, second=0, microsecond=0)
        minutes = (now - open_t).total_seconds() / 60.0
        return 390.0 / min(max(minutes, 30.0), 390.0)
    except Exception:
        return 1.0


def _flow(volumes: np.ndarray, last_bar_ts) -> dict:
    avg20 = float(np.mean(volumes[-21:-1])) if len(volumes) >= 21 else 0.0
    rvol = 0.0
    if avg20 > 0:
        rvol = float(volumes[-1]) / avg20 * _session_factor(last_bar_ts)

    if rvol < config.RVOL_THIN:
        state = "THIN"
    elif rvol < config.RVOL_CROWDED:
        state = "HEALTHY"
    else:
        state = "CROWDED"

    score = _piecewise(rvol, [(0, 10), (0.6, 45), (1.0, 65), (1.5, 80), (2.5, 90), (5.0, 75), (10.0, 60)])
    return {
        "state": state,
        "score": round(score),
        "rvol": round(rvol, 2),
        "summary": FLOW_SUMMARY[state],
        "advice": [a.format(rvol=rvol) for a in FLOW_ADVICE[state]],
    }


# ── BEARING ──────────────────────────────────────────────────────────────────

BEARING_SUMMARY = {
    "CLEAN UP": "Efficient uptrend — dips are getting bought",
    "CHOPPY UP": "Upward bias with a whippy, inefficient path",
    "FLAT": "Rangebound — no directional edge",
    "CHOPPY DOWN": "Downward bias with indecision — exercise caution",
    "DOWN": "Efficient downtrend — sellers in control",
}
BEARING_ADVICE = {
    "CLEAN UP": [
        "Trend is doing the work — pullbacks to the 20-day MA are the highest-odds entries.",
        "Let winners run; trail stops under the 20-day rather than taking quick profits.",
    ],
    "CHOPPY UP": [
        "Upward bias but a noisy path — expect more frequent stop-outs.",
        "Size down and wait for cleaner impulses before adding.",
    ],
    "FLAT": [
        "No trend to trade — watch, don't touch, until it picks a direction.",
        "A volume-backed break of the range is the signal to act.",
    ],
    "CHOPPY DOWN": [
        "Downward drift but choppy — rallies fade and breakdowns whip back.",
        "If you must trade it, take quick exits; better setups exist elsewhere.",
    ],
    "DOWN": [
        "Clean downtrend — don't knife-catch.",
        "First sign of life is a close back above the 20-day MA.",
    ],
}
BEARING_BASE = {"CLEAN UP": 90, "CHOPPY UP": 65, "FLAT": 45, "CHOPPY DOWN": 30, "DOWN": 10}


def _bearing(closes: np.ndarray) -> dict:
    c = float(closes[-1])
    ma20 = float(np.mean(closes[-20:]))
    ma50 = float(np.mean(closes[-50:]))
    ma20_prior = float(np.mean(closes[-30:-10]))  # 20MA as of 10 sessions ago
    slope10 = (ma20 / ma20_prior - 1.0) if ma20_prior > 0 else 0.0

    # Kaufman efficiency ratio over 20 days: net move / sum of daily moves
    window = closes[-21:]
    deltas = np.abs(np.diff(window))
    denom = float(np.sum(deltas))
    er = float(abs(window[-1] - window[0]) / denom) if denom > 0 else 0.0

    up_votes = int(c > ma20) + int(ma20 > ma50) + int(slope10 > 0.01)
    down_votes = int(c < ma20) + int(ma20 < ma50) + int(slope10 < -0.01)

    if up_votes >= 2 and slope10 > 0:
        state = "CLEAN UP" if er >= config.ER_CLEAN else "CHOPPY UP"
    elif down_votes >= 2 and slope10 < 0:
        state = "DOWN" if er >= config.ER_CLEAN else "CHOPPY DOWN"
    else:
        state = "FLAT"

    score = BEARING_BASE[state] + max(-8.0, min(8.0, slope10 * 200.0))
    return {
        "state": state,
        "score": round(max(0.0, min(100.0, score))),
        "er": round(er, 2),
        "slope10_pct": round(slope10 * 100, 1),
        "summary": BEARING_SUMMARY[state],
        "advice": list(BEARING_ADVICE[state]),
    }


# ── PULSE ────────────────────────────────────────────────────────────────────

PULSE_SUMMARY = {
    "QUIET": "Compressed volatility — coiled-spring conditions",
    "TRADABLE": "Normal volatility — standard risk-reward achievable",
    "WILD": "Elevated volatility — wide ranges and violent swings",
}
PULSE_ADVICE = {
    "QUIET": [
        "Volatility is compressed ({atr_pctile:.0f}th percentile) — big moves often follow stretches like this.",
        "Watch for the volume day that breaks the calm.",
    ],
    "TRADABLE": [
        "Volatility in its normal range — setups have room to breathe.",
        "Standard stop sizing applies (~{stop:.0f}% gives a normal day's room).",
    ],
    "WILD": [
        "This moves {atr_pct:.1f}% on a normal day — a stop closer than ~{stop:.0f}% is a coin flip.",
        "Cut share count so dollar risk stays constant.",
    ],
}


def _pulse(closes: np.ndarray, highs: np.ndarray, lows: np.ndarray) -> dict:
    prev_close = np.concatenate(([closes[0]], closes[:-1]))
    tr = np.maximum(highs - lows, np.maximum(np.abs(highs - prev_close), np.abs(lows - prev_close)))

    n = len(closes)
    atr_pct = np.full(n, np.nan)
    for i in range(13, n):
        atr = np.mean(tr[i - 13:i + 1])
        if closes[i] > 0:
            atr_pct[i] = atr / closes[i] * 100.0

    bbw = np.full(n, np.nan)
    for i in range(19, n):
        w = closes[i - 19:i + 1]
        m = np.mean(w)
        if m > 0:
            bbw[i] = 4.0 * np.std(w) / m * 100.0

    cur_atr_pct = float(atr_pct[-1]) if not np.isnan(atr_pct[-1]) else 0.0
    atr_pctile = _percentile_of_last(atr_pct)
    bbw_pctile = _percentile_of_last(bbw)
    blended = 0.7 * atr_pctile + 0.3 * bbw_pctile

    if cur_atr_pct >= config.ATR_PCT_WILD or blended >= 85:
        state = "WILD"
    elif cur_atr_pct < config.ATR_PCT_QUIET and blended < 40:
        state = "QUIET"
    else:
        state = "TRADABLE"

    score = _piecewise(cur_atr_pct, [(0.5, 30), (2, 55), (3.5, 85), (5, 75), (8, 45), (12, 20)])
    stop = 1.5 * cur_atr_pct
    return {
        "state": state,
        "score": round(score),
        "atr_pct": round(cur_atr_pct, 1),
        "atr_pctile": round(blended),
        "summary": PULSE_SUMMARY[state],
        "advice": [a.format(atr_pct=cur_atr_pct, atr_pctile=blended, stop=stop) for a in PULSE_ADVICE[state]],
    }


# ── Public API ───────────────────────────────────────────────────────────────

UNAVAILABLE = {"available": False, "above_20ma": None}


def compute(ticker: str, hist) -> dict:
    """Compute all three gauges from a daily OHLCV frame. Never raises."""
    try:
        if hist is None or len(hist) < 60:
            return dict(UNAVAILABLE)

        closes = hist["Close"].to_numpy(dtype=float)
        volumes = hist["Volume"].to_numpy(dtype=float)
        highs = hist["High"].to_numpy(dtype=float)
        lows = hist["Low"].to_numpy(dtype=float)

        mask = ~(np.isnan(closes) | np.isnan(highs) | np.isnan(lows))
        closes, volumes, highs, lows = closes[mask], volumes[mask], highs[mask], lows[mask]
        if len(closes) < 60:
            return dict(UNAVAILABLE)
        volumes = np.nan_to_num(volumes, nan=0.0)

        return {
            "available": True,
            "above_20ma": bool(closes[-1] > np.mean(closes[-20:])),
            "flow": _flow(volumes, hist.index[-1]),
            "bearing": _bearing(closes),
            "pulse": _pulse(closes, highs, lows),
        }
    except Exception:
        return dict(UNAVAILABLE)
