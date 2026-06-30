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


def _ema(arr, span):
    a = 2.0 / (span + 1.0)
    e = float(arr[0])
    out = np.empty(len(arr))
    out[0] = e
    for i in range(1, len(arr)):
        e = a * float(arr[i]) + (1 - a) * e
        out[i] = e
    return out


def _ema_structure(c):
    """EMA 20/50/200 stack — the book demotes EMAs to 'confluence only', so this is
    a supporting factor, not a trigger. Bullish stack = price>50>200, 20>50."""
    n = len(c)
    e20, e50 = _ema(c, 20), _ema(c, 50)
    e200 = _ema(c, 200) if n >= 200 else None
    px = float(c[-1])
    stack = px > e50[-1] and e20[-1] > e50[-1] and (e200 is None or e50[-1] > e200[-1])
    reclaim = px > e50[-1] and bool(np.any(c[-12:-1] < e50[-12:-1]))  # crossed back above 50 lately
    return {
        "stack_bullish": bool(stack),
        "above_50": bool(px > e50[-1]),
        "above_200": bool(e200 is not None and px > e200[-1]),
        "reclaim": bool(reclaim),
    }


def _double_bottom(h, l, c, atr):
    """W reversal: two swing lows at ~the same price, a neckline peak between them,
    price now holding/breaking the neckline. A classic early-upside bottoming."""
    n = len(c)
    if n < 40 or atr <= 0:
        return {"active": False}
    sl = [i for i in _swing_lows(l, 3) if (n - 1 - i) <= 70]
    if len(sl) < 2:
        return {"active": False}
    i1, i2 = sl[-2], sl[-1]
    L1, L2 = float(l[i1]), float(l[i2])
    if abs(L1 - L2) > max(0.5 * atr, 0.03 * L1):       # the two bottoms must match
        return {"active": False}
    # a real double bottom is in the LOWER part of the range after a decline, not a
    # dip near parabolic highs (audit finding)
    rng = max(float(np.max(h[-90:]) - np.min(l[-90:])), 1e-9) if n >= 90 else max(float(np.max(h) - np.min(l)), 1e-9)
    if (L1 - float(np.min(l[-90:] if n >= 90 else l))) / rng > 0.4:
        return {"active": False}
    neck = float(np.max(h[i1:i2 + 1]))
    px = float(c[-1])
    if px < L2:
        return {"active": False}
    return {"active": True, "low": round((L1 + L2) / 2, 4), "neckline": round(neck, 4),
            "confirmed": bool(px > neck * 0.99)}


def _reverse_hns(h, l, c, atr):
    """Reverse head-and-shoulders: three swing lows, middle (head) lowest, outer
    shoulders similar & higher; bullish on a neckline break."""
    n = len(c)
    if n < 60 or atr <= 0:
        return {"active": False}
    sl = [i for i in _swing_lows(l, 3) if (n - 1 - i) <= 90]
    if len(sl) < 3:
        return {"active": False}
    a, b, d = sl[-3], sl[-2], sl[-1]
    La, Lb, Ld = float(l[a]), float(l[b]), float(l[d])
    if not (Lb < La and Lb < Ld):                       # head below both shoulders
        return {"active": False}
    if abs(La - Ld) > max(0.8 * atr, 0.05 * La):        # shoulders roughly level
        return {"active": False}
    neck = float(np.max(h[a:d + 1]))
    px = float(c[-1])
    if px < Ld:
        return {"active": False}
    return {"active": True, "neckline": round(neck, 4), "confirmed": bool(px > neck * 0.99)}


def _market_phase(c, h, l, atr):
    """Wyckoff/Dow phase from trend structure. A 40-bar slope alone lags badly — a
    fresh breakout off a base still reads 'flat' for weeks — so recent RETURNS
    override first: a stock up 8%+ over 20 days is in MARKUP, never accumulation,
    and DISTRIBUTION only fires when price is actually rolling over near highs."""
    n = len(c)
    recent = c[-40:] if n >= 40 else c
    prior = c[-90:-40] if n >= 90 else None
    s_recent = _slope_frac(recent)
    s_prior = _slope_frac(prior) if prior is not None and len(prior) >= 20 else 0.0

    rng = max(float(np.max(h[-60:]) - np.min(l[-60:])), 1e-9) if n >= 5 else 1.0
    pos = float((c[-1] - np.min(l[-60:])) / rng) if n >= 5 else 0.5  # 0=at lows, 1=at highs
    ret20 = float(c[-1] / c[-21] - 1) if n > 21 else 0.0
    ret60 = float(c[-1] / c[-61] - 1) if n > 61 else 0.0
    p = round(pos, 2)

    # ── return-based overrides (a strong directional move is never "sideways") ──
    if ret20 >= 0.08 and pos >= 0.45:
        return {"state": "MARKUP", "detail": f"marking up — +{ret20*100:.0f}% in 20d", "pos": p}
    if ret20 <= -0.08 and pos <= 0.55:
        return {"state": "MARKDOWN", "detail": f"marking down — {ret20*100:.0f}% in 20d", "pos": p}

    UP, DN = 0.05, -0.05
    if s_recent >= UP and pos >= 0.5:
        return {"state": "MARKUP", "detail": "uptrend — higher highs & higher lows", "pos": p}
    if s_recent <= DN:
        return {"state": "MARKDOWN", "detail": "downtrend — lower highs & lower lows", "pos": p}
    # genuinely sideways — classify by the prior leg + where we sit in the range
    if s_prior <= DN and pos <= 0.55 and ret20 < 0.05:
        return {"state": "ACCUMULATION", "detail": "basing in the lower range after a decline", "pos": p}
    if (s_prior >= UP or ret60 >= 0.15) and pos >= 0.7 and s_recent < 0:
        return {"state": "DISTRIBUTION", "detail": "rolling over near highs — supply overhead", "pos": p}
    return {"state": "NEUTRAL", "detail": "no clear phase", "pos": p}


def _rbs(c, h, l, atr):
    """Resistance-Becomes-Support: a prior swing-high level that price has broken
    above and is now HOLDING (not a one-bar poke). Hardened against the failure the
    audit found — a single spike close above a twice-rejected resistance was being
    called 'reclaimed'. Now requires sustained holding, rejects spike-bar reclaims
    and chop-through levels."""
    n = len(c)
    if n < 40 or atr <= 0:
        return {"active": False}
    px = float(c[-1])
    last5 = c[-5:]
    sh = [i for i in _swing_highs(h, 3) if 5 <= (n - 1 - i) <= 70]
    best = None
    for i in sh:
        level = float(h[i])
        if level >= px:
            continue
        # decisively reclaimed in the last ~25 bars
        if not np.any(c[max(i + 1, n - 25):] > level + 0.3 * atr):
            continue
        # HOLDING: at least 3 of the last 5 closes sit above the level (not a 1-bar poke)
        if np.sum(last5 > level) < 3:
            continue
        # not a chop-through, range-middle level: reject if the close crossed it >3x
        crossings = int(np.sum(np.diff(np.sign(c[max(i + 1, n - 40):] - level)) != 0))
        if crossings > 3:
            continue
        # don't chase a spike reclaim (a single >15% up day that vaulted the level)
        if float(np.max(np.abs(np.diff(c[-3:]) / c[-3:-1]))) > 0.15 and px > level + atr:
            continue
        # still a retest, not extended far above the shelf
        if (level - 0.2 * atr) <= px <= level + 1.2 * atr:
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

    # nearest support BELOW price: swing lows + demand-zone low + reclaimed level.
    # k=3 pivots can't see a low printed in the last 3 bars, so include the raw
    # recent extremes too — else the stop lands ABOVE real support (audit finding).
    supports = [float(l[i]) for i in _swing_lows(l, 3) if (n - 1 - i) <= 60 and l[i] < px]
    recent_low = float(np.min(l[-5:]))
    if recent_low < px:
        supports.append(recent_low)
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
    # never leave the stop above the most recent lows — clamp below the 3-bar low
    stop = min(stop, float(np.min(l[-3:])) - 0.1 * atr)
    risk = px - stop
    if risk <= 0:
        return None
    if risk / px > 0.12:                  # support too far → no tight entry (book: skip wide risk)
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
        hi = float(np.max(h))
        lo = float(np.min(l))
        px = float(c[-1])
        context = {
            "pct_off_high": round((px / hi - 1) * 100, 1) if hi else 0.0,
            "range_pos": round((px - lo) / (hi - lo), 2) if hi > lo else 0.5,  # 0=at lows, 1=at highs
        }
        return {
            "available": True,
            "phase": _market_phase(c, h, l, atr),
            "rbs": rbs,
            "reversal": _reversal_candle(o, h, l, c, atr),
            "profile": profile,
            "ema": _ema_structure(c),
            "double_bottom": _double_bottom(h, l, c, atr),
            "reverse_hns": _reverse_hns(h, l, c, atr),
            "context": context,
            "plan": _trade_plan(h, l, c, atr, zone, profile, extra_support=rbs.get("level")),
        }
    except Exception:
        return {"available": False}
