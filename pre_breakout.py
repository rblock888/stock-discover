"""Pre-breakout / coiled-spring detector — catch them BEFORE they fly.

The opposite of momentum. Momentum rewards stocks that already launched;
this rewards the coiled spring right before it does, and explicitly PENALIZES
already-extended charts ("flew to the roof" = EXTENDED, demoted).

Signals (pure price/volume from a daily OHLCV frame — yfinance-reliable):
  1. Volatility compression — Bollinger/ATR width squeezed to multi-month lows
  2. Tight, contracting base — narrow range getting narrower (VCP)
  3. Not extended — penalizes far-above-MA / multi-month blow-off moves
  4. Volume dry-up → turn — quiet accumulation, then the first volume uptick
  5. Coiled near the pivot — sitting just under a breakout level

compute() is pure numpy and never raises. The score is persisted so the
evaluation engine can measure whether high coiled-scores actually precede
big forward moves.
"""

import numpy as np

from ticker_edge import _percentile_of_last, _piecewise

UNAVAILABLE = {"available": False, "state": "UNKNOWN", "coiled_score": 0}

COILED_SUMMARY = {
    "COILED": "Compressed and basing — loaded for a breakout, hasn't moved yet",
    "BASING": "Building a base — setup forming but not fully coiled",
    "EXTENDED": "Already extended — the move largely happened (chase risk)",
    "NO SETUP": "No pre-breakout structure — trending down or too loose",
}


def _bbw_series(closes: np.ndarray) -> np.ndarray:
    n = len(closes)
    out = np.full(n, np.nan)
    for i in range(19, n):
        w = closes[i - 19:i + 1]
        m = np.mean(w)
        if m > 0:
            out[i] = 4.0 * np.std(w) / m * 100.0
    return out


def _atr_pct_series(closes, highs, lows) -> np.ndarray:
    prev = np.concatenate(([closes[0]], closes[:-1]))
    tr = np.maximum(highs - lows, np.maximum(np.abs(highs - prev), np.abs(lows - prev)))
    n = len(closes)
    out = np.full(n, np.nan)
    for i in range(13, n):
        atr = np.mean(tr[i - 13:i + 1])
        if closes[i] > 0:
            out[i] = atr / closes[i] * 100.0
    return out


def compute(ticker: str, hist) -> dict:
    """Coiled-spring / pre-breakout score (0-100) + state. Never raises."""
    try:
        if hist is None or len(hist) < 120:
            return dict(UNAVAILABLE)

        closes = hist["Close"].to_numpy(dtype=float)
        highs = hist["High"].to_numpy(dtype=float)
        lows = hist["Low"].to_numpy(dtype=float)
        volumes = np.nan_to_num(hist["Volume"].to_numpy(dtype=float), nan=0.0)

        mask = ~(np.isnan(closes) | np.isnan(highs) | np.isnan(lows))
        closes, highs, lows, volumes = closes[mask], highs[mask], lows[mask], volumes[mask]
        if len(closes) < 120:
            return dict(UNAVAILABLE)

        c = float(closes[-1])
        ma20 = float(np.mean(closes[-20:]))
        ma50 = float(np.mean(closes[-50:]))

        # 1. Volatility compression — squeeze percentile vs the trailing year
        bbw = _bbw_series(closes)
        atrp = _atr_pct_series(closes, highs, lows)
        squeeze_pctile = 0.5 * _percentile_of_last(bbw) + 0.5 * _percentile_of_last(atrp)
        compression = _piecewise(squeeze_pctile, [(0, 100), (20, 85), (35, 62), (55, 32), (80, 8), (100, 0)])

        # 2. Tight, contracting base (20-day range as % of price)
        rng20 = (float(np.max(highs[-20:])) - float(np.min(lows[-20:]))) / c * 100 if c > 0 else 100
        tight = _piecewise(rng20, [(5, 100), (12, 85), (20, 60), (32, 30), (50, 8), (100, 0)])
        rng_recent = float(np.max(highs[-10:]) - np.min(lows[-10:]))
        rng_prior = float(np.max(highs[-20:-10]) - np.min(lows[-20:-10]))
        contracting = rng_recent < rng_prior
        if contracting:
            tight = min(100.0, tight + 8)

        # 3. NOT extended — the anti-chase guard
        ext = (c / ma50 - 1.0) if ma50 > 0 else 0.0
        ret_3m = (c / closes[-63] - 1.0) if len(closes) > 63 and closes[-63] > 0 else 0.0
        ret_1m = (c / closes[-21] - 1.0) if len(closes) > 21 and closes[-21] > 0 else 0.0
        not_extended = _piecewise(ext, [(-0.20, 45), (-0.05, 78), (0.05, 100), (0.15, 80), (0.30, 35), (0.60, 5), (3.0, 0)])
        blowoff = ret_3m > 0.55 or ret_1m > 0.40

        # 4. Volume dry-up → first turn
        avg10 = float(np.mean(volumes[-10:]))
        avg50 = float(np.mean(volumes[-50:]))
        dry = (avg10 / avg50) if avg50 > 0 else 1.0
        rvol = (volumes[-1] / np.mean(volumes[-21:-1])) if np.mean(volumes[-21:-1]) > 0 else 1.0
        vol_score = _piecewise(dry, [(0.4, 92), (0.85, 80), (1.0, 55), (1.5, 32), (3.0, 12)])
        if rvol > 1.5 and dry < 1.15:
            vol_score = min(100.0, vol_score + 12)  # spring loading

        # 5. Coiled near the pivot (top of the recent base = ready to break)
        hi50 = float(np.max(highs[-50:]))
        prox = (c / hi50) if hi50 > 0 else 0.0
        pivot = _piecewise(prox, [(0.55, 12), (0.75, 38), (0.88, 68), (0.95, 92), (1.0, 100)])

        coiled = (0.35 * compression + 0.20 * tight + 0.20 * not_extended
                  + 0.15 * vol_score + 0.10 * pivot)

        # Downtrend guard: a falling, below-50MA chart is not a base
        downtrend = c < ma50 and ma20 < ma50 and ret_1m < -0.05

        if blowoff or ext > 0.35:
            state = "EXTENDED"
            coiled = min(coiled, 32)
        elif downtrend:
            state = "NO SETUP"
            coiled = min(coiled, 38)
        elif coiled >= 68 and squeeze_pctile < 38 and ext < 0.22:
            state = "COILED"
        elif coiled >= 46:
            state = "BASING"
        else:
            state = "NO SETUP"

        reasons = []
        if squeeze_pctile < 35:
            reasons.append(f"volatility compressed ({squeeze_pctile:.0f}th pctile)")
        if rng20 < 20:
            reasons.append(f"tight {rng20:.0f}% base" + (", contracting" if contracting else ""))
        if state == "EXTENDED":
            reasons.append(f"already +{ret_3m * 100:.0f}% in 3m" if ret_3m > 0.3 else f"{ext * 100:.0f}% above 50-day")
        elif -0.05 <= ext <= 0.15:
            reasons.append("not yet extended")
        if dry < 0.85:
            reasons.append("volume dried up (quiet)")
        if rvol > 1.5 and dry < 1.15:
            reasons.append(f"volume turning up ({rvol:.1f}x)")
        if prox >= 0.9 and state != "EXTENDED":
            reasons.append("coiled near pivot")

        return {
            "available": True,
            "coiled_score": round(coiled, 1),
            "state": state,
            "summary": COILED_SUMMARY[state],
            "squeeze_pctile": round(squeeze_pctile),
            "range_pct": round(rng20, 1),
            "ext_pct": round(ext * 100, 1),
            "ret_3m_pct": round(ret_3m * 100, 1),
            "pivot_prox": round(prox, 3),
            "reasons": reasons,
        }
    except Exception:
        return dict(UNAVAILABLE)
