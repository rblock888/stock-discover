"""SMAD — Smart-Money Accumulation & Demand-zone detector.

Distilled from the supply/demand + institutional-intent books (Willemsen,
"Institutional Intent" / "Supply & Demand Mastery") into mechanical rules on
daily OHLCV — the computable kernel after discarding order-flow/delta/DOM and
intraday content that daily bars can't carry.

The accumulation sequence, catching the upside push EARLY:
  ACCUMULATION  — tight boring base (institutions building)
  SPRING        — wick below the base low that closes back inside (stop-hunt
                  reclaim) → the earliest long, fires before any breakout
  BOS IMPULSE   — wide-range top-close candle breaks structure off the base
  DEMAND RETEST — pullback into the fresh demand zone (the primary early entry)
  BULL TRAP     — effort-without-result fakeout → veto (don't chase)

Pure numpy, never raises. COMPLEMENTS pre_breakout (compression) — it measures
the accumulation / sweep / zone sequence, not the squeeze.

NB: thresholds are reasonable ATR-relative defaults re-parameterized from the
books' pip-based forex rules — NOT yet validated on US daily stock data. The
smad_score is persisted so evaluation.py can measure its real forward edge.
"""

import numpy as np

from ticker_edge import _piecewise

UNAVAILABLE = {"available": False, "state": "NONE", "smad_score": 0}

STATE_SUMMARY = {
    "SPRING": "Stop-hunt reclaim — wicked below the base low and closed back inside (earliest long)",
    "BOS IMPULSE": "Breakout of structure off a base — buyers just revealed intent",
    "DEMAND RETEST": "Pulling back into a fresh demand zone — the highest-odds early entry",
    "ACCUMULATION": "Tight boring base — quiet accumulation, watch for the spring",
    "BULL TRAP": "Effort without result — fakeout/absorption, do NOT chase",
    "NONE": "No accumulation / demand-zone sequence",
}


# ── primitives ───────────────────────────────────────────────────────────────

def _atr(closes, highs, lows, n=20):
    prev = np.concatenate(([closes[0]], closes[:-1]))
    tr = np.maximum(highs - lows, np.maximum(np.abs(highs - prev), np.abs(lows - prev)))
    return tr, float(np.mean(tr[-n:]))


def _swings(highs, lows, k=3):
    """Confirmed local pivots (k bars each side). Returns (swing_high_idxs, swing_low_idxs)."""
    sh, sl = [], []
    for i in range(k, len(highs) - k):
        if highs[i] == max(highs[i - k:i + k + 1]):
            sh.append(i)
        if lows[i] == min(lows[i - k:i + k + 1]):
            sl.append(i)
    return sh, sl


def _lower_wick_frac(o, h, l, c):
    rng = h - l
    return (min(o, c) - l) / rng if rng > 0 else 0.0


def _close_pos(o, h, l, c):
    rng = h - l
    return (c - l) / rng if rng > 0 else 0.5


def _body_frac(o, h, l, c):
    rng = h - l
    return abs(c - o) / rng if rng > 0 else 0.0


# ── component detectors ──────────────────────────────────────────────────────

def _base(highs, lows, closes, vols, atr20, avgv60):
    """Tightest recent balance range → (strength 0-1, base_lo, base_hi).

    Range CONTRACTION: the current N-bar band is tighter than most N-bar bands
    over the trailing ~100 bars (percentile), not tight vs its own ATR.
    """
    n = len(closes)
    best = (0.0, None, None)
    for N in (7, 10, 15):
        if n <= N + 30:
            continue
        cur_band = float(np.max(highs[-N:]) - np.min(lows[-N:]))
        hist = [float(np.max(highs[j - N + 1:j + 1]) - np.min(lows[j - N + 1:j + 1]))
                for j in range(max(N - 1, n - 100), n - 1)]
        if len(hist) < 20:
            continue
        pct = 100.0 * np.mean(np.array(hist) < cur_band)  # % of recent bands tighter than now
        net = abs(closes[-1] / closes[-N] - 1.0) if closes[-N] > 0 else 1.0
        vol_ok = np.mean(vols[-N:]) >= 0.6 * avgv60 if avgv60 > 0 else True
        if pct <= 35 and net <= 0.08 and vol_ok:
            s = _piecewise(pct, [(0, 1.0), (15, 0.85), (25, 0.65), (35, 0.45), (50, 0.0)])
            if s > best[0]:
                best = (s, float(np.min(lows[-N:])), float(np.max(highs[-N:])))
    return best


def _sweep_reclaim(o, h, l, c, vols, swing_lows, avgv20):
    """Liquidity sweep below a swing low that closed back inside, then up-confirm. 0-1."""
    n = len(c)
    if not swing_lows:
        return 0.0
    # reference swing low from before the recent window
    ref_idx = next((s for s in reversed(swing_lows) if s <= n - 3), swing_lows[-1])
    swing_low = float(l[ref_idx])
    best = 0.0
    for s in range(n - 5, n):  # last 5 bars
        if s < 1 or s >= n:
            continue
        if l[s] <= swing_low * 0.995 and c[s] > swing_low:  # swept and reclaimed
            wick = _lower_wick_frac(o[s], h[s], l[s], c[s])
            vol_x = vols[s] / avgv20 if avgv20 > 0 else 1.0
            # confirmation: a later bar closed up and above the swept low
            confirmed = any(c[j] > o[j] and c[j] > swing_low for j in range(s + 1, n))
            if wick >= 0.5 and vol_x >= 1.3 and (confirmed or s == n - 1):
                strength = _piecewise(wick, [(0.5, 0.55), (0.65, 0.8), (0.8, 1.0)])
                strength *= _piecewise(vol_x, [(1.3, 0.7), (1.8, 0.9), (2.5, 1.0)])
                if confirmed:
                    strength = min(1.0, strength + 0.1)
                best = max(best, strength)
    return best


def _impulse_bos(o, h, l, c, vols, swing_highs, atr20, avgv20):
    """First break-of-structure impulse (clears prior swing high) → (strength 0-1, demand_zone|None).

    Independent of any *current* base — the impulse breaks the structure (prior
    swing high) and its origin (the 1-3 candles before it) becomes the demand zone.
    """
    n = len(c)
    best = 0.0
    zone = None
    for i in range(max(4, n - 8), n):  # recent impulse
        rng = h[i] - l[i]
        if rng <= 0:
            continue
        tr_x = rng / atr20 if atr20 > 0 else 0.0
        cpos = _close_pos(o[i], h[i], l[i], c[i])
        prior_sh = [s for s in swing_highs if s < i - 1]
        if not prior_sh:
            continue
        swing_high = float(h[prior_sh[-1]])  # most recent confirmed swing high before the impulse
        vol_x = vols[i] / avgv20 if avgv20 > 0 else 1.0
        clears = c[i] > swing_high  # break of structure
        if tr_x >= 1.5 and cpos >= 0.75 and c[i] > o[i] and clears and vol_x >= 1.0:
            body = _body_frac(o[i], h[i], l[i], c[i])
            strength = _piecewise(tr_x, [(1.5, 0.6), (2.2, 0.85), (3.5, 1.0)]) * _piecewise(vol_x, [(1.0, 0.7), (1.6, 0.9), (2.5, 1.0)])
            if body >= 0.85:
                strength = min(1.0, strength + 0.1)  # near-Marubozu
            if strength > best:
                best = strength
                base_slice = slice(max(0, i - 3), i)
                zone = (round(float(np.min(l[base_slice])), 4), round(float(np.max(h[base_slice])), 4), i)
    return best, zone


def _zone_retest(o, h, l, c, vols, zone, atr20, avgv20):
    """Fresh-zone pullback with a bullish rejection. → (strength 0-1, present bool)."""
    if not zone:
        return 0.0, False
    z_lo, z_hi, imp_i = zone
    n = len(c)
    if z_hi - z_lo > 1.2 * atr20:  # zone too tall = bad risk
        return 0.0, False
    # freshness: count bars since impulse that overlapped the zone
    touches = sum(1 for j in range(imp_i + 1, n) if l[j] <= z_hi and h[j] >= z_lo)
    if touches > 2:
        return 0.0, False
    j = n - 1  # current bar
    in_zone = l[j] <= z_hi and l[j] >= z_lo * 0.97 and c[j] > z_lo
    if not in_zone:
        return 0.0, False
    body = abs(c[j] - o[j])
    lower_wick = min(o[j], c[j]) - l[j]
    bull_engulf = j >= 1 and o[j] <= c[j - 1] and c[j] >= o[j - 1] and c[j - 1] < o[j - 1]
    rejection = (lower_wick >= 2 * body and body > 0) or bull_engulf or c[j] > o[j]
    if not rejection:
        return 0.0, False
    strength = 0.7 + (0.3 if touches <= 1 else 0.0)
    if avgv20 > 0 and vols[j] < np.mean(vols[-10:]):  # volume dried into the zone
        strength = min(1.0, strength + 0.1)
    return strength, True


def _trap_veto(o, h, l, c, vols, base_hi, swing_highs, avgv20):
    """Effort-without-result / failed-breakout → 'hard' | 'soft' | None."""
    n = len(c)
    # absorption candle in the last 2 bars: high volume, small body, rejected high
    for i in (n - 1, n - 2):
        if i < 1:
            continue
        rng = h[i] - l[i]
        if rng <= 0:
            continue
        vol_x = vols[i] / avgv20 if avgv20 > 0 else 1.0
        body = _body_frac(o[i], h[i], l[i], c[i])
        cpos = _close_pos(o[i], h[i], l[i], c[i])
        made_high = h[i] >= np.max(h[max(0, i - 10):i]) if i > 0 else False
        if vol_x >= 1.5 and body < 0.30 and made_high and cpos <= 0.33:
            return "hard"
    # failed breakout: closed above base_hi then back below within 1-2 bars
    if base_hi is not None and n >= 3:
        for i in range(n - 3, n - 1):
            if i >= 1 and c[i] > base_hi and c[n - 1] < base_hi:
                return "hard"
    # soft: new high on lower volume than the prior swing-high bar (divergence)
    if len(swing_highs) >= 1 and h[n - 1] >= np.max(h[-20:]):
        psh = swing_highs[-1]
        if vols[n - 1] < vols[psh] * 0.8:
            return "soft"
    return None


# ── public API ───────────────────────────────────────────────────────────────

def compute(ticker, hist):
    """Smart-money accumulation / demand-zone state from daily OHLCV. Never raises."""
    try:
        if hist is None or len(hist) < 120:
            return dict(UNAVAILABLE)
        o = hist["Open"].to_numpy(dtype=float)
        h = hist["High"].to_numpy(dtype=float)
        l = hist["Low"].to_numpy(dtype=float)
        c = hist["Close"].to_numpy(dtype=float)
        v = np.nan_to_num(hist["Volume"].to_numpy(dtype=float), nan=0.0)
        m = ~(np.isnan(o) | np.isnan(h) | np.isnan(l) | np.isnan(c))
        o, h, l, c, v = o[m], h[m], l[m], c[m], v[m]
        if len(c) < 120:
            return dict(UNAVAILABLE)

        _, atr20 = _atr(c, h, l, 20)
        avgv20 = float(np.mean(v[-20:]))
        avgv60 = float(np.mean(v[-60:]))
        sh, sl = _swings(h, l, 3)

        # Structure gate: up/flat (last two swing lows non-descending)
        up_or_flat = (len(sl) < 2) or (l[sl[-1]] >= l[sl[-2]] * 0.98)

        base_s, base_lo, base_hi = _base(h, l, c, v, atr20, avgv60)
        sweep_s = _sweep_reclaim(o, h, l, c, v, sl, avgv20)
        impulse_s, zone = _impulse_bos(o, h, l, c, v, sh, atr20, avgv20)
        retest_s, retest_present = _zone_retest(o, h, l, c, v, zone, atr20, avgv20)
        veto = _trap_veto(o, h, l, c, v, base_hi, sh, avgv20)

        trap_penalty = 0.0 if veto == "hard" else (0.35 if veto == "soft" else 1.0)
        raw = 0.15 * base_s + 0.25 * sweep_s + 0.20 * impulse_s + 0.20 * retest_s
        score = round(100.0 * raw * trap_penalty, 1)

        # State by priority
        if veto == "hard":
            state = "BULL TRAP"
        elif sweep_s >= 0.5 and up_or_flat:
            state = "SPRING"
        elif impulse_s >= 0.5:
            state = "BOS IMPULSE"
        elif retest_present and retest_s >= 0.5:
            state = "DEMAND RETEST"
        elif base_s >= 0.5:
            state = "ACCUMULATION"
        else:
            state = "NONE"

        reasons = []
        if state == "SPRING":
            reasons.append("swept below base low & reclaimed")
        if state == "BOS IMPULSE":
            reasons.append("impulse cleared base + swing high on volume")
        if state == "DEMAND RETEST" and zone:
            reasons.append(f"retest of fresh demand zone {zone[0]}-{zone[1]}")
        if state == "ACCUMULATION":
            reasons.append("tight balance range, accumulating")
        if veto == "hard":
            reasons.append("effort without result — fakeout")
        elif veto == "soft":
            reasons.append("new high on lower volume (divergence)")
        if base_lo is not None and state not in ("BULL TRAP", "NONE"):
            reasons.append(f"base {base_lo}-{base_hi}")

        return {
            "available": True,
            "smad_score": score,
            "state": state,
            "summary": STATE_SUMMARY[state],
            "components": {
                "base": round(base_s, 2),
                "sweep_reclaim": round(sweep_s, 2),
                "impulse_bos": round(impulse_s, 2),
                "zone_retest": round(retest_s, 2),
            },
            "trap": veto,
            "demand_zone": ([zone[0], zone[1]] if zone else None),
            "base_zone": ([base_lo, base_hi] if base_lo is not None else None),
            "reasons": reasons,
        }
    except Exception:
        return dict(UNAVAILABLE)
