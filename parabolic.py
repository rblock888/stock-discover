"""Parabolic-candidate criteria engine — a ledger, not a letter.

The problem this fixes: conviction.py already counts 18 named factors and then
prints only the grade. A reader sees "B" and cannot tell which four things
failed. This module keeps the vector — every criterion with its measured value,
its verdict, and the benchmark or window it was measured against — so the output
can lead with what FAILED and still show the name.

THREE RULES THAT MAKE IT HONEST, each guarding a specific way this kind of
screen lies to its owner:

1. THE DENOMINATOR NEVER SHRINKS SILENTLY. The template has 15 criteria; five of
   them (raised guidance, non-decelerating guide, orders/backlog growth, and
   sector read-through) need filing or transcript text this app does not parse
   yet. Reporting "10/10" by quietly dropping them would be the single easiest
   way to make this read as rubbish. Output is always n_pass / n_computable with
   the uncomputable criteria NAMED. An uncomputable criterion never passes.

2. CORRELATED EVIDENCE IS COLLAPSED. A sharp V-recovery MECHANICALLY produces a
   rising 50-DMA, a rising 100-DMA, positive relative strength and a rising OBV.
   Counting those as four independent confirmations is counting one fact four
   times, and it is exactly how a screen talks itself into a name that has
   already run. When the V-recovery gate fires, those four collapse into a
   single cluster worth 1, and the word "base" becomes unusable for that name.

3. RANGES USE THE PERIOD LOW AS DENOMINATOR. pre_breakout.py divides by the
   close; this module divides by the low, which is the convention that
   reproduces published figures (a $39.20-$74.60 12-week range is quoted as
   +90%, which is 74.60/39.20-1, not the close-relative number). The two
   conventions must never share a field name — half the ledger would silently
   disagree with the other half.

Report-only. Nothing here reaches composite_score, rank_score, the conviction
grade, tilt or alert selection until par_* clears its pre-registered bar.
"""

import logging

import numpy as np

from pre_breakout import _atr_pct_series, _bbw_series

logger = logging.getLogger("discovery")

UNAVAILABLE = {"available": False, "criteria": [], "n_pass": 0,
               "n_computable": 0, "n_total": 15}

CRITERIA_VERSION = 1

BASE_WINDOW = 25          # sessions the base is measured over
BASE_RANGE_MAX = 0.25     # ...within which price must stay
BASE_RANGE_MAX_MICRO = 0.35   # microcaps are structurally wider
MICRO_MCAP = 300_000_000
BASE_DRIFT_MAX = 0.15     # a base goes sideways; it does not travel
COMPRESSION_PCTILE = 35.0
VOLUME_DRYUP_MAX = 1.05

V_LOOKBACK = 60           # window whose low defines a V-recovery
V_RECENT = 30             # ...if that low printed this recently
V_BOUNCE = 1.30           # ...and price is now this far above it

RANGE_12W_MAX = 0.40
RANGE_20D_MAX = 0.20
SLOPE_MIN = 0.005         # +0.5% over 10 sessions — "flat" is never "rising"
SLOPE_LOOKBACK = 10
CHASE_LIMIT = 0.15        # max distance above the 20-DMA
REV_GROWTH_MIN = 0.25
GROSS_MARGIN_MIN = 0.40
EARNINGS_WINDOW = (7, 42)  # a company catalyst must be this many days out

# The four criteria a V-recovery produces mechanically. Collapsed to one when
# the V-recovery gate fires.
V_ARTIFACTS = ("T4", "T5", "T6", "T7")


def _pctile(series, value):
    """Percentile rank of `value` within `series` (NaNs dropped)."""
    s = np.asarray(series, dtype=float)
    s = s[np.isfinite(s)]
    if len(s) < 30 or value is None or not np.isfinite(value):
        return None
    return float((s <= value).mean() * 100.0)


def _sma(c, n):
    return float(np.mean(c[-n:])) if len(c) >= n else None


def _slope(c, n):
    """Fractional change in the n-period SMA over SLOPE_LOOKBACK sessions."""
    if len(c) < n + SLOPE_LOOKBACK + 1:
        return None
    now = float(np.mean(c[-n:]))
    then = float(np.mean(c[-(n + SLOPE_LOOKBACK):-SLOPE_LOOKBACK]))
    if then <= 0:
        return None
    return now / then - 1.0


def _range_pct(highs, lows, n):
    """(high - low) / low over the last n sessions. LOW denominator — see docstring."""
    if len(highs) < n or len(lows) < n:
        return None
    hi = float(np.max(highs[-n:]))
    lo = float(np.min(lows[-n:]))
    return None if lo <= 0 else (hi - lo) / lo


def _obv(c, v):
    sign = np.sign(np.diff(c))
    return np.concatenate(([0.0], np.cumsum(sign * v[1:])))


def _v_recovery(c, lows):
    """Did the 60-session low print recently, with price now far above it?

    This is the gate that separates a quiet base from a violent bounce. Both
    leave price above rising averages; only one is a base."""
    if len(c) < V_LOOKBACK or len(lows) < V_LOOKBACK:
        return False, None
    window = lows[-V_LOOKBACK:]
    lo = float(np.min(window))
    idx_from_end = len(window) - 1 - int(np.argmin(window))
    if lo <= 0:
        return False, None
    recent = idx_from_end <= V_RECENT
    bounced = c[-1] >= V_BOUNCE * lo
    return bool(recent and bounced), {
        "low": round(lo, 4), "sessions_ago": idx_from_end,
        "off_low_pct": round((c[-1] / lo - 1.0) * 100.0, 1),
    }


def _base(c, highs, lows, vols, market_cap, v_fired):
    """Base-present test. Returns (present, failed_reasons, detail)."""
    fails = []
    W = BASE_WINDOW
    if len(c) < max(W + 10, V_LOOKBACK):
        return None, ["insufficient history"], ""

    cap = BASE_RANGE_MAX_MICRO if (market_cap or 0) and market_cap < MICRO_MCAP else BASE_RANGE_MAX
    rng = _range_pct(highs, lows, W)
    if rng is None or rng > cap:
        fails.append(f"{W}d range {rng*100:.0f}% > {cap*100:.0f}%" if rng is not None
                     else "range unavailable")

    recent = _range_pct(highs, lows, 10)
    prior_h, prior_l = highs[-W:-10], lows[-W:-10]
    prior = None
    if len(prior_h) and float(np.min(prior_l)) > 0:
        prior = (float(np.max(prior_h)) - float(np.min(prior_l))) / float(np.min(prior_l))
    if recent is None or prior is None or not (recent < 0.75 * prior):
        fails.append("range not contracting")

    atr = _atr_pct_series(c, highs, lows)
    bbw = _bbw_series(c)
    atr_p = _pctile(atr[-252:], atr[-1] if len(atr) else None)
    bbw_p = _pctile(bbw[-252:], bbw[-1] if len(bbw) else None)
    if atr_p is None or bbw_p is None or atr_p > COMPRESSION_PCTILE or bbw_p > COMPRESSION_PCTILE:
        fails.append("not compressed (ATR/BBW percentile high)")

    drift = abs(c[-1] / c[-W] - 1.0) if c[-W] > 0 else None
    if drift is None or drift > BASE_DRIFT_MAX:
        fails.append(f"drifted {drift*100:.0f}% over {W}d" if drift is not None else "drift unavailable")

    if v_fired:
        fails.append("V-recovery, not consolidation")

    if len(vols) >= 50:
        dry = float(np.mean(vols[-10:])) / float(np.mean(vols[-50:])) if float(np.mean(vols[-50:])) > 0 else None
        if dry is None or dry > VOLUME_DRYUP_MAX:
            fails.append("no volume dry-up")
    else:
        fails.append("volume history short")

    # third element is NUMERIC (the base-window range %), not a label: it is
    # persisted as par_T1_val and rank-correlated, and a string there would
    # blow up the IC the first time that column was measured.
    return (len(fails) == 0), fails, (round(rng * 100, 1) if rng is not None else None)


# Phone-length labels. The full `name` and `detail` are for the dashboard; a
# pre-open brief that prints "fails: 90%, 52%" tells the reader nothing about
# WHAT is 90%, which is worse than printing nothing.
SHORT_LABELS = {
    "T1": "base", "T2": "12w range", "T3": "20d range", "T4": "50-DMA",
    "T5": "100-DMA", "T6": "sector RS", "T7": "OBV", "T8": "chase limit",
    "F1": "rev growth", "F2": "guidance", "F3": "guide trend",
    "F4": "gross margin", "F5": "orders", "C1": "catalyst", "C2": "read-through",
}


def _crit(key, name, category, passed, computable=True, value=None, detail=""):
    return {"key": key, "name": name, "short": SHORT_LABELS.get(key, name),
            "category": category,
            "passed": bool(passed) if computable else False,
            "computable": bool(computable), "value": value, "detail": detail}


def compute(hist, rs: dict = None, market_cap: float = None,
            earnings_days=None, financials=None, info: dict = None) -> dict:
    """Score one name against the 15-criterion parabolic template."""
    if hist is None or len(hist) == 0 or "Close" not in hist:
        return dict(UNAVAILABLE)
    try:
        c = np.asarray(hist["Close"], dtype=float)
        highs = np.asarray(hist["High"], dtype=float)
        lows = np.asarray(hist["Low"], dtype=float)
        vols = np.asarray(hist["Volume"], dtype=float)
        ok = np.isfinite(c) & np.isfinite(highs) & np.isfinite(lows)
        c, highs, lows, vols = c[ok], highs[ok], lows[ok], np.nan_to_num(vols[ok])
    except Exception:
        return dict(UNAVAILABLE)
    if len(c) < 30:
        return dict(UNAVAILABLE)

    v_fired, v_detail = _v_recovery(c, lows)
    base_present, base_fails, base_range = _base(c, highs, lows, vols, market_cap, v_fired)
    base_detail = f"{BASE_WINDOW}d range {base_range:.0f}%" if base_range is not None else ""

    crits = []

    # ── T1 base: the structural gate the output must lead with ──
    crits.append(_crit("T1", "Base present", "technical",
                       bool(base_present), base_present is not None,
                       value=base_range,
                       detail="; ".join(base_fails) if base_fails else base_detail))

    r12 = _range_pct(highs, lows, 60)
    crits.append(_crit("T2", "12-week range contained", "technical",
                       r12 is not None and r12 <= RANGE_12W_MAX, r12 is not None,
                       value=None if r12 is None else round(r12 * 100, 1),
                       detail="" if r12 is None else f"{r12*100:.0f}% (max {RANGE_12W_MAX*100:.0f}%)"))

    r20 = _range_pct(highs, lows, 20)
    crits.append(_crit("T3", "20-day range contained", "technical",
                       r20 is not None and r20 <= RANGE_20D_MAX, r20 is not None,
                       value=None if r20 is None else round(r20 * 100, 1),
                       detail="" if r20 is None else f"{r20*100:.0f}% (max {RANGE_20D_MAX*100:.0f}%)"))

    for key, n in (("T4", 50), ("T5", 100)):
        sma = _sma(c, n)
        slope = _slope(c, n)
        comp = sma is not None and slope is not None
        above = comp and c[-1] > sma
        rising = comp and slope >= SLOPE_MIN
        dist = (c[-1] / sma - 1.0) * 100 if (sma and sma > 0) else None
        crits.append(_crit(key, f"Above a rising {n}-DMA", "technical",
                           above and rising, comp,
                           value=None if dist is None else round(dist, 1),
                           detail="" if not comp else
                           f"{dist:+.1f}% vs {n}-DMA, slope {slope*100:+.1f}%/10d"
                           + ("" if rising else " — NOT rising")))

    rs = rs or {}
    rs_ok = bool(rs.get("available"))
    crits.append(_crit("T6", "Sector RS positive (20d & 40d)", "technical",
                       rs.get("both_positive"), rs_ok,
                       value=rs.get("rs_20d"),
                       detail=rs.get("detail", "") if rs_ok else "no benchmark"))

    obv_ok = len(c) >= 61
    obv_rising = False
    obv_detail = ""
    if obv_ok:
        o = _obv(c, vols)
        sma20 = float(np.mean(o[-20:]))
        slope_ok = bool(np.polyfit(np.arange(20), o[-20:], 1)[0] > 0)
        near_high = o[-1] >= float(np.max(o[-60:])) * 0.97 if float(np.max(o[-60:])) > 0 else o[-1] > 0
        obv_rising = bool(o[-1] > sma20 and slope_ok and near_high)
        obv_detail = "OBV rising" if obv_rising else "OBV not confirming"
    crits.append(_crit("T7", "OBV rising", "technical", obv_rising, obv_ok,
                       detail=obv_detail))

    sma20 = _sma(c, 20)
    chase = (c[-1] / sma20 - 1.0) if (sma20 and sma20 > 0) else None
    crits.append(_crit("T8", "Within chase limit of 20-DMA", "technical",
                       chase is not None and chase <= CHASE_LIMIT, chase is not None,
                       value=None if chase is None else round(chase * 100, 1),
                       detail="" if chase is None else
                       f"{chase*100:+.1f}% above 20-DMA (limit {CHASE_LIMIT*100:.0f}%)"))

    # ── fundamentals: only the two that free data actually supports ──
    growth = None
    try:
        if financials is not None and not financials.empty:
            for label in ("Total Revenue", "Revenue"):
                if label in financials.index:
                    row = financials.loc[label].dropna()
                    if len(row) >= 4 and float(row.iloc[3]) > 0:
                        growth = (float(row.iloc[0]) - float(row.iloc[3])) / abs(float(row.iloc[3]))
                    break
    except Exception:
        growth = None
    crits.append(_crit("F1", "Revenue growth >= 25% YoY", "fundamental",
                       growth is not None and growth >= REV_GROWTH_MIN, growth is not None,
                       value=None if growth is None else round(growth * 100, 1),
                       detail="" if growth is None else f"{growth*100:+.0f}% YoY"))

    gm = (info or {}).get("grossMargins")
    try:
        gm = float(gm) if gm else None
    except (TypeError, ValueError):
        gm = None
    crits.append(_crit("F4", "Gross margin >= 40%", "fundamental",
                       gm is not None and gm >= GROSS_MARGIN_MIN, gm is not None,
                       value=None if gm is None else round(gm * 100, 1),
                       detail="" if gm is None else f"{gm*100:.1f}% (trailing, GAAP)"))

    # Not parseable from free structured data — they need 8-K / EX-99.1 text.
    # Carried explicitly so the denominator stays honest.
    crits.append(_crit("F2", "Guidance raised", "fundamental", False, False,
                       detail="needs filing text (not parsed yet)"))
    crits.append(_crit("F3", "Guide not decelerating", "fundamental", False, False,
                       detail="needs filing text (not parsed yet)"))
    crits.append(_crit("F5", "Orders / backlog growth", "fundamental", False, False,
                       detail="needs filing text (not parsed yet)"))

    ed = None
    try:
        ed = int(earnings_days) if earnings_days is not None else None
    except (TypeError, ValueError):
        ed = None
    crits.append(_crit("C1", "Company catalyst in window", "catalyst",
                       ed is not None and EARNINGS_WINDOW[0] <= ed <= EARNINGS_WINDOW[1],
                       ed is not None,
                       value=ed,
                       detail="" if ed is None else f"earnings in {ed}d "
                       f"(window {EARNINGS_WINDOW[0]}-{EARNINGS_WINDOW[1]}d)"))
    crits.append(_crit("C2", "Sector read-through catalyst", "catalyst", False, False,
                       detail="peer event calendar not built yet"))

    # ── correlated-evidence collapse ──
    clusters = []
    n_pass = sum(1 for x in crits if x["passed"])
    n_pass_adj = n_pass
    if v_fired:
        fired = [x["key"] for x in crits if x["key"] in V_ARTIFACTS and x["passed"]]
        if len(fired) > 1:
            n_pass_adj = n_pass - (len(fired) - 1)
            clusters.append({
                "name": "V-recovery artifacts",
                "members": fired,
                "raw_count": len(fired),
                "counted_as": 1,
                "detail": f"a {v_detail['off_low_pct']:.0f}% bounce off a low "
                          f"{v_detail['sessions_ago']}d ago mechanically produces these — "
                          "one fact, not " + str(len(fired)) + " confirmations",
            })

    n_computable = sum(1 for x in crits if x["computable"])
    uncomputable = [x["key"] for x in crits if not x["computable"]]

    if base_present is False:
        verdict = "No base."
        if v_fired:
            verdict += f" V-recovery — +{v_detail['off_low_pct']:.0f}% off a low " \
                       f"{v_detail['sessions_ago']} sessions ago."
    elif base_present:
        verdict = "Base present."
    else:
        verdict = "Base undetermined (short history)."

    return {
        "available": True,
        "version": CRITERIA_VERSION,
        "criteria": crits,
        "n_pass": n_pass,
        "n_pass_adjusted": n_pass_adj,
        "n_computable": n_computable,
        "n_total": len(crits),
        "uncomputable": uncomputable,
        "headline": f"{n_pass_adj}/{n_computable} computable "
                    f"({len(uncomputable)} need filing text)",
        "base": {"present": base_present, "failed": base_fails, "detail": base_detail},
        "gates": {"v_recovery": v_fired, "v_detail": v_detail},
        "clusters": clusters,
        "benchmark": rs.get("benchmark"),
        "benchmark_mapped": rs.get("mapped"),
        "verdict": verdict,
    }
