"""Daily-OHLCV detectors distilled from Supply & Demand Mastery + Institutional
Intent (the parts that actually transfer from Forex/order-flow to daily stock bars).

The audit of the books found these computable-from-daily-bars concepts that the
technical kernel (smad/pre_breakout/ticker_edge) didn't yet cover:

  market_phase   Wyckoff/Dow phase — ACCUMULATION / MARKUP / DISTRIBUTION / MARKDOWN
  rbs            "Resistance Becomes Support" — a broken level reclaimed & held (a buy)
  reversal       named bullish reversal candle at a low (hammer, engulfing, star, tweezer)
  profile        volume profile — POC / value-area low+high (Institutional Intent)
  plan           concrete trade plan: entry / stop / target / R:R (the risk chapter)

Everything is pure numpy on the OHLCV frame, never raises, degrades to
{available: False} on short history. Forex-only material (sessions, NFP/FOMC
news-avoidance, pip stops, DOM/footprint/delta) is intentionally excluded.
"""

import numpy as np


def _slope_frac(arr):
    """Linear-fit slope over the window, as a fraction of mean price (≈ % move)."""
    n = len(arr)
    if n < 5:
        return 0.0
    x = np.arange(n, dtype=float)
    m = np.polyfit(x, arr, 1)[0]
    mean = float(np.mean(arr))
    return (m * n) / mean if mean else 0.0


def _atr(h, l, c, n=14):
    if len(c) < 2:
        return float(np.mean(h - l)) if len(c) else 0.0
    tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    n = min(n, len(tr))
    return float(np.mean(tr[-n:])) if n else 0.0


def _swing_highs(h, k=3):
    idx = []
    for i in range(k, len(h) - k):
        if h[i] == max(h[i - k:i + k + 1]) and h[i] > h[i - 1]:
            idx.append(i)
    return idx


def _swing_lows(l, k=3):
    idx = []
    for i in range(k, len(l) - k):
        if l[i] == min(l[i - k:i + k + 1]) and l[i] < l[i - 1]:
            idx.append(i)
    return idx


def _market_phase(c, h, l, atr):
    """Wyckoff/Dow phase from trend structure: the current leg, and what preceded a
    sideways base (down→flat = accumulation, up→flat = distribution)."""
    n = len(c)
    recent = c[-40:] if n >= 40 else c
    prior = c[-90:-40] if n >= 90 else None
    s_recent = _slope_frac(recent)
    s_prior = _slope_frac(prior) if prior is not None and len(prior) >= 20 else 0.0

    rng = max(float(np.max(h[-60:]) - np.min(l[-60:])), 1e-9) if n >= 5 else 1.0
    pos = (c[-1] - np.min(l[-60:])) / rng if n >= 5 else 0.5  # 0=at lows, 1=at highs

    UP, DN = 0.06, -0.06  # ~6% drift over the window = a real leg
    if s_recent >= UP:
        return {"state": "MARKUP", "detail": "uptrend — higher highs & higher lows", "pos": round(float(pos), 2)}
    if s_recent <= DN:
        return {"state": "MARKDOWN", "detail": "downtrend — lower highs & lower lows", "pos": round(float(pos), 2)}
    # sideways now — classify by the prior leg
    if s_prior <= DN:
        return {"state": "ACCUMULATION", "detail": "basing after a decline — the pre-markup phase", "pos": round(float(pos), 2)}
    if s_prior >= UP:
        return {"state": "DISTRIBUTION", "detail": "stalling near highs after a run — supply overhead", "pos": round(float(pos), 2)}
    return {"state": "NEUTRAL", "detail": "no clear phase", "pos": round(float(pos), 2)}


def _rbs(c, h, l, atr):
    """Resistance-Becomes-Support: a prior swing-high level that price recently
    closed above and is RIGHT NOW retesting from above and holding. Strict — price
    must actually be sitting on the reclaimed level, not merely somewhere above it."""
    n = len(c)
    if n < 40 or atr <= 0:
        return {"active": False}
    px = float(c[-1])
    recent_lo = float(np.min(l[-3:]))
    # candidate resistance: swing highs in the mid window (recent enough to matter,
    # old enough to have been broken)
    sh = [i for i in _swing_highs(h, 3) if 5 <= (n - 1 - i) <= 70]
    best = None
    for i in sh:
        level = float(h[i])
        if level >= px:
            continue
        # decisively reclaimed in the last ~25 bars
        if not np.any(c[max(i + 1, n - 25):] > level + 0.3 * atr):
            continue
        # price is now PINNED to the level: a recent low tagged it and we still hold above
        if recent_lo <= level + 0.4 * atr and (level - 0.2 * atr) <= px <= level + 0.8 * atr:
            if best is None or level > best:
                best = level
    if best is not None:
        return {"active": True, "level": round(best, 4), "detail": f"holding reclaimed ${best:.2f}"}
    return {"active": False}


def _reversal_candle(o, h, l, c, atr):
    """Name a bullish reversal candle in the last 1–3 bars, and whether it printed
    at a low (the only place the book lets you act on one)."""
    n = len(c)
    if n < 5 or atr <= 0:
        return None
    rng20 = max(float(np.max(h[-20:]) - np.min(l[-20:])), 1e-9)
    at_low = (c[-1] - float(np.min(l[-20:]))) / rng20 < 0.5

    o1, h1, l1, c1 = o[-1], h[-1], l[-1], c[-1]
    body = abs(c1 - o1)
    lower = min(o1, c1) - l1
    upper = h1 - max(o1, c1)
    name = None

    # Hammer / Pin bar
    if body > 0 and lower >= 2 * body and upper <= body:
        name = "Hammer / pin bar"
    # Bullish engulfing
    elif c1 > o1 and o[-2] > c[-2] and c1 >= o[-2] and o1 <= c[-2]:
        name = "Bullish engulfing"
    # Tweezer bottom
    elif abs(l1 - l[-2]) <= 0.1 * atr and c[-2] < o[-2] and c1 > o1:
        name = "Tweezer bottom"
    # Morning star (3-candle)
    elif n >= 3 and o[-3] > c[-3] and abs(c[-2] - o[-2]) < 0.5 * abs(c[-3] - o[-3]) and c1 > o1 \
            and c1 >= c[-3] + 0.4 * (o[-3] - c[-3]):
        name = "Morning star"

    if name:
        return {"name": name, "bullish": True, "at_low": bool(at_low)}
    return None


def _volume_profile(h, l, c, v, bins=24):
    """Volume-by-price → POC and the 70% value area (VAL/VAH). Institutional Intent's
    structural map: zones near the POC carry real acceptance; thin levels are traps."""
    n = len(c)
    if n < 20 or float(np.sum(v)) <= 0:
        return None
    win = min(n, 120)
    typ = (h[-win:] + l[-win:] + c[-win:]) / 3.0
    vol = v[-win:]
    lo, hi = float(np.min(typ)), float(np.max(typ))
    if hi <= lo:
        return None
    edges = np.linspace(lo, hi, bins + 1)
    centers = (edges[:-1] + edges[1:]) / 2.0
    hist = np.zeros(bins)
    idx = np.clip(((typ - lo) / (hi - lo) * bins).astype(int), 0, bins - 1)
    for j, vv in zip(idx, vol):
        hist[j] += vv
    poc = float(centers[int(np.argmax(hist))])
    # value area = highest-volume bins accumulating to 70%
    order = np.argsort(hist)[::-1]
    total = hist.sum()
    chosen, acc = [], 0.0
    for j in order:
        chosen.append(j)
        acc += hist[j]
        if acc >= 0.70 * total:
            break
    val = float(centers[min(chosen)])
    vah = float(centers[max(chosen)])
    px = c[-1]
    position = "above" if px > vah else ("below" if px < val else "inside")
    return {"poc": round(poc, 4), "val": round(val, 4), "vah": round(vah, 4), "position": position}


def _trade_plan(h, l, c, atr, zone, profile, extra_support=None):
    """Concrete plan: enter at current price, stop below the NEAREST structural
    support (zone low, recent swing low, or a held reclaimed level), target the
    next real resistance. The book's risk rule applies — if the nearest support is
    too far (>~10% / wide risk), there's no tight entry here, so return None rather
    than a junk R:R."""
    n = len(c)
    if n < 15 or atr <= 0:
        return None
    px = float(c[-1])

    # nearest support BELOW price: swing lows + demand-zone low + reclaimed level
    supports = [float(l[i]) for i in _swing_lows(l, 3) if (n - 1 - i) <= 60 and l[i] < px]
    if zone and len(zone) == 2 and zone[0] and zone[1]:
        zlo = float(min(zone))
        if zlo < px:
            supports.append(zlo)
    if extra_support and extra_support < px:
        supports.append(float(extra_support))
    supports = [s for s in supports if s < px]
    if not supports:
        return None
    support = max(supports)              # the closest support beneath price
    stop = support - 0.4 * atr
    risk = px - stop
    if risk <= 0:
        return None
    if risk / px > 0.10:                  # support too far → no tight entry (book: skip wide risk)
        return None

    # target: next meaningful resistance ≥ ~1 ATR (or 4%) above, else value-area
    # high, else a 2R measured move
    floor = px + max(1.0 * atr, 0.04 * px)
    sh = sorted([float(h[i]) for i in _swing_highs(h, 3) if h[i] >= floor])
    if sh:
        target = sh[0]
    elif profile and profile.get("vah", 0) >= floor:
        target = profile["vah"]
    else:
        target = px + 2.0 * risk
    reward = target - px
    if reward <= 0:
        return None
    return {
        "entry": round(px, 4), "stop": round(stop, 4), "target": round(target, 4),
        "rr": round(reward / risk, 2), "risk_pct": round(risk / px * 100, 1),
    }


def compute(hist, zone=None):
    """Run all daily-bar book detectors on one OHLCV frame. Never raises."""
    try:
        o = hist["Open"].to_numpy(dtype=float)
        h = hist["High"].to_numpy(dtype=float)
        l = hist["Low"].to_numpy(dtype=float)
        c = hist["Close"].to_numpy(dtype=float)
        v = np.nan_to_num(hist["Volume"].to_numpy(dtype=float), nan=0.0)
        if len(c) < 30:
            return {"available": False}
        atr = _atr(h, l, c, 14)
        profile = _volume_profile(h, l, c, v)
        rbs = _rbs(c, h, l, atr)
        return {
            "available": True,
            "phase": _market_phase(c, h, l, atr),
            "rbs": rbs,
            "reversal": _reversal_candle(o, h, l, c, atr),
            "profile": profile,
            "plan": _trade_plan(h, l, c, atr, zone, profile, extra_support=rbs.get("level")),
        }
    except Exception:
        return {"available": False}
