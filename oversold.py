"""Oversold bounce watch — DAY-TRADING timeframes only (1h + 15m).

Ruben's spec (2026-07-22): "only look at day trading levels — 1hr, 15 min —
and only highlight targets where the 1h RSI is below 30, so we have potential
to go to the upside being oversold."

Mechanics:
  • Wilder RSI(14) on 1-HOUR bars — the selection gate: keep ONLY RSI < 30.
  • RSI(14) on 15-MINUTE bars — the timing read: shown alongside, with a
    "turning up" flag when the 15m RSI has curled off its low (the earliest
    sign the bounce is starting rather than the knife still falling).
  • Candidates first pass the day-mover exclusions (no AVOID-graded names —
    a dilution/trap veto doesn't care how oversold the chart is — no
    earnings-today coin flips, no illiquid/sub-$1 names) and keep the
    day-move CAPABILITY score for ranking context (a 6%/day-range name can
    actually deliver the bounce; a 1.5%/day large cap can't).
  • Sorted MOST oversold first.

Honesty: oversold-bounce is mean-reversion — the opposite bet from the
breakout lane — and "oversold can stay oversold". Every published list is
logged with previous closes, so day_movers_scorecard box-scores it (+5%/+10%
same-day hit rates) exactly like the momentum list it replaces. The data will
say whether 1h-RSI<30 earns its spot.

yfinance intraday limits: 60m bars ≤730 days, 15m bars ≤60 days — both far
more than the ~1 month fetched here. One batched download per interval.
"""

import logging

import numpy as np

import day_movers

logger = logging.getLogger("discovery")

RSI_PERIOD = 14
OVERSOLD = 30.0
MAX_PICKS = 5


def rsi(closes, period: int = RSI_PERIOD) -> float | None:
    """Wilder-smoothed RSI on a close series. None if not enough bars."""
    c = np.asarray(closes, dtype=float)
    c = c[~np.isnan(c)]
    if len(c) < period + 2:
        return None
    deltas = np.diff(c)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_g = float(np.mean(gains[:period]))
    avg_l = float(np.mean(losses[:period]))
    for g, l in zip(gains[period:], losses[period:]):
        avg_g = (avg_g * (period - 1) + g) / period
        avg_l = (avg_l * (period - 1) + l) / period
    if avg_l == 0:
        return 100.0
    rs = avg_g / avg_l
    return float(100.0 - 100.0 / (1.0 + rs))


def _fetch_closes(tickers: list, period: str, interval: str) -> dict:
    """{ticker: np.array(closes)} via one batched yfinance download."""
    out = {}
    if not tickers:
        return out
    try:
        import yfinance as yf
        raw = yf.download(tickers, period=period, interval=interval,
                          group_by="ticker", progress=False, threads=False)
        for t in tickers:
            try:
                df = raw[t] if len(tickers) > 1 else raw
                closes = df["Close"].dropna().to_numpy(dtype=float)
                if len(closes):
                    out[t] = closes
            except Exception:
                continue
    except Exception as e:
        logger.warning(f"oversold: intraday fetch failed: {e}")
    return out


def scan(ranked: list) -> list:
    """1h-oversold bounce candidates from a scan's ranked list.

    Returns mover-shaped dicts (score/prev_close/reasons/...) so the pre-open
    brief formatting and the hit-rate scorecard work unchanged."""
    candidates = []
    for s in ranked:
        try:
            m = day_movers.score_one(s)   # exclusions + capability ranking
        except Exception:
            continue
        if m:
            candidates.append(m)
    if not candidates:
        return []

    tickers = [m["ticker"] for m in candidates]
    h1 = _fetch_closes(tickers, period="1mo", interval="60m")
    m15 = _fetch_closes(tickers, period="5d", interval="15m")

    picks = []
    for m in candidates:
        t = m["ticker"]
        closes_1h = h1.get(t)
        if closes_1h is None:
            continue
        rsi_1h = rsi(closes_1h)
        if rsi_1h is None or rsi_1h >= OVERSOLD:
            continue   # the gate: 1h RSI must be BELOW 30

        rsi_15 = None
        turning = False
        closes_15 = m15.get(t)
        if closes_15 is not None and len(closes_15) > RSI_PERIOD + 5:
            rsi_15 = rsi(closes_15)
            rsi_15_prior = rsi(closes_15[:-3])
            turning = (rsi_15 is not None and rsi_15_prior is not None
                       and rsi_15 > rsi_15_prior + 2)

        reasons = [f"1h RSI {rsi_1h:.0f} — oversold"]
        if rsi_15 is not None:
            reasons.append(f"15m RSI {rsi_15:.0f}" + (" ↑ turning" if turning else ""))
        reasons.append(f"{m['atr_pct']:.1f}%/day range")
        # carry the strongest non-range context from the day-mover read
        extra = next((r for r in m["reasons"]
                      if "catalyst" in r or "squeeze" in r or "news" in r or "flow" in r), None)
        if extra:
            reasons.append(extra)

        picks.append({
            **m,
            "score": m["score"],            # capability ranking retained for context
            "rsi_1h": round(rsi_1h, 1),
            "rsi_15m": round(rsi_15, 1) if rsi_15 is not None else None,
            "turning": turning,
            "trigger_px": None,             # the trigger here is the RSI turn, not a pivot
            "reasons": reasons[:4],
        })

    picks.sort(key=lambda p: p["rsi_1h"])   # most oversold first
    return picks[:MAX_PICKS]
