"""Relative strength against a SECTOR benchmark — not SPY.

The gap this closes: every relative measure in this app benchmarks to SPY
(momentum.py's 63d SPY-excess, evaluation's SPY-excess forward returns). A
semiconductor-equipment name beating SPY during a semis bull tape is not
information — it is the sector's beta wearing the stock's name. Measuring the
same name against SMH asks the only question that matters for stock selection:
is this name beating the group it will move with anyway?

COST: zero extra network calls. market_regime already downloads 1y frames for
every symbol here (SPY/QQQ/IWM + the 13 sector ETFs) on a 15-minute cycle via
price_history.get_histories, and price_history caches by "TICKER:period". This
module reads the same "…:1y" keys, so in a live process it is pure cache hits.

TWO RS DEFINITIONS, BOTH PERSISTED. They disagree, and which one is right here
is an empirical question this app is built to answer:
  • EXCESS   — stock return minus benchmark return over the window, in
               percentage points. Simple and interpretable, but it scales with
               the move: a name that ran +46% in 20 sessions shows a huge excess.
  • MANSFIELD — (ratio / SMA(ratio) - 1) * 100, where ratio = stock/benchmark.
               Normalized, so it measures whether outperformance is ACCELERATING
               rather than how big the move was. This is almost certainly what
               published screens mean when they print "RS vs SOXX +5.2" for a
               name that just doubled — a raw excess could never be that small.
Excess is the primary (it is the one a human can verify by hand); Mansfield is
carried alongside so their ICs can be compared and the better one promoted.

THE BENCHMARK IS ALWAYS NAMED IN THE OUTPUT. A silent fallback to SPY would make
a sector-relative claim that is quietly market-relative — the exact kind of
almost-true number that makes a brief read as rubbish. `mapped` says whether the
sector was actually resolved, and `benchmark` says what was really used.
"""

import logging

import numpy as np

import price_history

logger = logging.getLogger("discovery")

# Sector display name -> benchmark ETF. Names match regime_tilt._map_sector's
# output vocabulary (which already special-cases Semis and Biotech by industry).
BENCH_BY_SECTOR = {
    "Tech": "XLK", "Energy": "XLE", "Financials": "XLF", "Healthcare": "XLV",
    "Industrials": "XLI", "Discretionary": "XLY", "Staples": "XLP",
    "Utilities": "XLU", "Materials": "XLB", "Real Estate": "XLRE",
    "Comm Svcs": "XLC", "Semis": "SMH", "Biotech": "XBI",
}

# Used when the sector is unknown. IWM (small-cap) rather than SPY: an unmapped
# name in THIS universe is far more likely to be a microcap than a mega cap, and
# benchmarking a $200M name to the S&P flatters it for simply being small.
FALLBACK_SMALLCAP = "IWM"
FALLBACK_BROAD = "SPY"
SMALLCAP_MAX_MCAP = 2_000_000_000

WINDOWS = (20, 40)
MANSFIELD_SMA = 20
MIN_OVERLAP = 60      # shared sessions required before any RS is reported


def pick_benchmark(sector: str = None, industry: str = None,
                   market_cap: float = None) -> tuple:
    """(etf, mapped) — mapped=False means the sector could not be resolved."""
    try:
        import regime_tilt
        name = regime_tilt._map_sector(sector or "", industry or "")
    except Exception:
        name = None
    etf = BENCH_BY_SECTOR.get(name) if name else None
    if etf:
        return etf, True
    try:
        mc = float(market_cap or 0)
    except (TypeError, ValueError):
        mc = 0.0
    return (FALLBACK_SMALLCAP if 0 < mc <= SMALLCAP_MAX_MCAP
            else FALLBACK_BROAD), False


def _aligned(hist, bench):
    """Close series for stock and benchmark on their SHARED sessions.

    Aligning on dates rather than position is not pedantry: halts, late listings
    and holiday mismatches routinely leave two frames of equal length covering
    different days, and a positional zip would silently compare Tuesday's stock
    to Wednesday's index for the whole window."""
    try:
        import pandas as pd
        a = pd.Series(hist["Close"]).dropna()
        b = pd.Series(bench["Close"]).dropna()
        j = pd.concat([a, b], axis=1, join="inner").dropna()
        if len(j) < MIN_OVERLAP:
            return None, None
        return (j.iloc[:, 0].to_numpy(dtype=float),
                j.iloc[:, 1].to_numpy(dtype=float))
    except Exception:
        return None, None


def _excess(s, b, n):
    """Stock return minus benchmark return over n sessions, in percentage points."""
    if len(s) < n + 1 or s[-(n + 1)] <= 0 or b[-(n + 1)] <= 0:
        return None
    sr = s[-1] / s[-(n + 1)] - 1.0
    br = b[-1] / b[-(n + 1)] - 1.0
    return float((sr - br) * 100.0)


def _mansfield(s, b, n):
    """Normalized RS: how far the stock/benchmark ratio sits above its own
    n-period SMA. Measures whether outperformance is ACCELERATING, independent
    of how big the underlying move was.

    The SMA window is n — it must scale with the horizon. An earlier version
    averaged a fixed 20 periods regardless of n, which made the 20d and 40d
    readings numerically IDENTICAL (both reduced to ratio[-1] vs the same
    trailing mean) while still being reported under two different names. Two
    columns that can never disagree are worse than one: they look like
    corroboration and carry no extra information."""
    if len(s) < n + 1 or len(b) < n + 1:
        return None
    ratio = s / b
    ratio = ratio[np.isfinite(ratio)]
    if len(ratio) < n + 1:
        return None
    sma = float(np.mean(ratio[-n:]))
    if sma <= 0:
        return None
    return float((ratio[-1] / sma - 1.0) * 100.0)


def compute(hist, sector: str = None, industry: str = None,
            market_cap: float = None) -> dict:
    """Sector-relative strength for one name at 20d and 40d.

    Returns available=False rather than a fabricated zero when the benchmark or
    the overlap is missing — a 0.0 RS reads as "exactly in line with its sector",
    which is a real and quite different claim from "we could not measure it"."""
    etf, mapped = pick_benchmark(sector, industry, market_cap)
    out = {"available": False, "benchmark": etf, "mapped": mapped,
           "rs_20d": None, "rs_40d": None, "both_positive": False,
           "mansfield_20d": None, "mansfield_40d": None, "detail": ""}
    if hist is None or len(hist) == 0:
        return out

    bench = price_history.get_history(etf, period="1y")
    if bench is None or len(bench) == 0:
        out["detail"] = f"{etf} unavailable"
        return out

    s, b = _aligned(hist, bench)
    if s is None:
        out["detail"] = f"insufficient overlap with {etf}"
        return out

    for n in WINDOWS:
        out[f"rs_{n}d"] = _excess(s, b, n)
        out[f"mansfield_{n}d"] = _mansfield(s, b, n)

    vals = [out["rs_20d"], out["rs_40d"]]
    out["available"] = any(v is not None for v in vals)
    out["both_positive"] = all(v is not None and v > 0 for v in vals)

    if out["available"]:
        parts = [f"{n}d {out[f'rs_{n}d']:+.1f}pp" for n in WINDOWS
                 if out[f"rs_{n}d"] is not None]
        tag = "" if mapped else " (no sector map)"
        out["detail"] = f"RS vs {etf}{tag}: " + " / ".join(parts)
    return out
