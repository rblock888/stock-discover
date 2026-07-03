"""Volume-delta proxies — the book's delta/orderflow read, daily-bar edition.

TRUE delta (aggressive buys-at-ask minus sells-at-bid, footprint, DOM) needs
per-trade tick data — paid feeds, not yfinance. But Institutional Intent's
underlying mechanics have standard daily-bar proxies:

  CLV (close-location value)   where the close sits in the bar's range, −1..+1.
                               A close at the high on volume = buyers were the
                               aggressors all day ≈ a positive-delta day.
  CMF (Chaikin Money Flow)     Σ(CLV×vol)/Σ(vol) over 20 bars — the pooled
                               "who's been in control" read ≈ cumulative delta.
  A/D-line divergence          price makes a higher high while the cumulative
                               CLV×volume line makes a LOWER high — the book's
                               delta divergence / "effort without result at
                               the highs": buyers print the breakout candle,
                               flow says they're being absorbed. (Close-to-
                               close OBV can't see this — closes can drift up
                               while every close sits at the bar's LOW; the
                               A/D line reads the intrabar positioning, which
                               is what delta actually measures.)
  Up/down volume ratio         within the last 20 bars, volume on up-closes vs
                               down-closes — is the base actually being
                               ACCUMULATED (quiet marking-up on volume) or
                               distributed?

All components persist per snapshot so their ICs are measured before anything
beyond a checklist factor + one bounded caution rides on them. compute() is
pure numpy and never raises.
"""

import numpy as np

UNAVAILABLE = {"available": False, "state": "UNKNOWN"}

CMF_ACCUM = 0.08       # 20-bar CMF above → flow-confirmed accumulation
CMF_DISTRIB = -0.08
UPDOWN_ACCUM = 1.3     # up-day volume 1.3x down-day volume
UPDOWN_DISTRIB = 0.8


def _clv(h, l, c):
    """Close-location value per bar, −1 (close at low) .. +1 (close at high)."""
    rng = h - l
    out = np.zeros(len(c))
    m = rng > 0
    out[m] = ((c[m] - l[m]) - (h[m] - c[m])) / rng[m]
    return out


def compute(hist) -> dict:
    """Volume-pressure read from daily OHLCV. Never raises."""
    try:
        if hist is None or len(hist) < 45:
            return dict(UNAVAILABLE)
        h = hist["High"].to_numpy(float)
        l = hist["Low"].to_numpy(float)
        c = hist["Close"].to_numpy(float)
        v = np.nan_to_num(hist["Volume"].to_numpy(float), nan=0.0)
        mask = ~(np.isnan(h) | np.isnan(l) | np.isnan(c))
        h, l, c, v = h[mask], l[mask], c[mask], v[mask]
        if len(c) < 45 or float(np.sum(v[-20:])) <= 0:
            return dict(UNAVAILABLE)

        clv = _clv(h, l, c)

        # CMF20 — pooled signed volume share (≈ cumulative delta, normalized)
        cmf = float(np.sum(clv[-20:] * v[-20:]) / np.sum(v[-20:]))

        # up/down volume ratio over 20 bars (accumulation quality)
        chg = np.diff(c[-21:])
        vol20 = v[-20:]
        up_vol = float(np.sum(vol20[chg > 0]))
        dn_vol = float(np.sum(vol20[chg < 0]))
        updown = up_vol / dn_vol if dn_vol > 0 else (3.0 if up_vol > 0 else 1.0)

        # A/D-line divergence over ~40 bars: price higher-high vs flow lower-high
        ad = np.cumsum(clv * v)
        divergence = None
        if len(c) >= 40:
            px_recent_hi = float(np.max(c[-10:]))
            px_prior_hi = float(np.max(c[-40:-10]))
            ad_recent_hi = float(np.max(ad[-10:]))
            ad_prior_hi = float(np.max(ad[-40:-10]))
            near_highs = px_recent_hi >= float(np.max(c[-40:])) * 0.98
            if px_recent_hi > px_prior_hi and ad_recent_hi < ad_prior_hi and near_highs:
                divergence = "bearish"   # the book's delta divergence at the highs
            px_recent_lo = float(np.min(c[-10:]))
            px_prior_lo = float(np.min(c[-40:-10]))
            ad_recent_lo = float(np.min(ad[-10:]))
            ad_prior_lo = float(np.min(ad[-40:-10]))
            if px_recent_lo < px_prior_lo and ad_recent_lo > ad_prior_lo:
                divergence = "bullish"   # sellers push lows, flow refuses — absorption

        if cmf >= CMF_ACCUM and updown >= UPDOWN_ACCUM:
            state = "ACCUMULATION"
        elif cmf <= CMF_DISTRIB and updown <= UPDOWN_DISTRIB:
            state = "DISTRIBUTION"
        else:
            state = "NEUTRAL"

        return {
            "available": True,
            "state": state,
            "cmf20": round(cmf, 3),
            "updown_ratio": round(updown, 2),
            "divergence": divergence,
            "summary": {
                "ACCUMULATION": f"flow-confirmed accumulation (CMF {cmf:+.2f}, up/down vol {updown:.1f}x)",
                "DISTRIBUTION": f"distribution — closes near lows on volume (CMF {cmf:+.2f})",
                "NEUTRAL": f"no clear volume pressure (CMF {cmf:+.2f})",
            }[state] + (f" · {divergence} flow divergence" if divergence else ""),
        }
    except Exception:
        return dict(UNAVAILABLE)


def session_pseudo_delta(bars) -> float | None:
    """Intraday pseudo-delta over COMPLETED 5m bars: Σ(CLV × volume). The
    watcher requires this positive at trigger — a breakout bar printing while
    session flow is net-negative is the book's delta trap shape."""
    try:
        if bars is None or len(bars) < 2:
            return None
        h = bars["High"].to_numpy(float)
        l = bars["Low"].to_numpy(float)
        c = bars["Close"].to_numpy(float)
        v = np.nan_to_num(bars["Volume"].to_numpy(float), nan=0.0)
        clv = _clv(h, l, c)
        return float(np.sum(clv * v))
    except Exception:
        return None
