"""Academic factor signals, as MEASURED CANDIDATES — not as beliefs.

Sourced from paperswithbacktest/awesome-systematic-trading, which publishes a
backtested Sharpe for each anomaly. Those Sharpes were measured on large, liquid,
long-short portfolios rebalanced monthly/yearly. This app is a long-only,
single-name discovery tool on micro/small caps with day-to-week holds. So the
published Sharpe is a PRIOR about direction, never evidence that the factor works
HERE. Every factor below is computed, persisted per snapshot, and scored by
evaluation.factor_scorecard() against this app's own forward returns. None of
them touch ranking until their own IC clears the pre-registered bar.

Why bother, given the app already measures its own buckets? Two reasons:
  1. Falsification. The list reports Momentum Factor Effect at Sharpe -0.008 and
     Momentum + Style Rotation at -0.056; this app independently measured its
     momentum bucket at IC -0.09. Two unrelated methods agreeing that classic
     momentum is dead is worth far more than either alone. `mom12_1` is carried
     here specifically as the control — if it ever prints a positive IC on this
     microcap universe, that disagreement is itself the discovery.
  2. Short-term reversal is the #2 equity strategy on the list (Sharpe 0.816,
     weekly) and Reversal During Earnings-Announcements is #3 (0.785, daily).
     Both are the same mean-reversion family as the 1h-RSI<30 oversold scan, on
     a longer clock. If `streversal` shows real IC, the oversold lane has an
     independent, published leg to stand on.

SIGN CONVENTION — the thing that makes results readable:
every factor is oriented so that HIGHER = the paper predicts a BETTER forward
return. A positive measured IC therefore means "the anomaly reproduces here"; a
negative IC means it inverts. No factor needs its sign remembered at read time.

COST: zero extra network calls. Price factors reuse the 1y daily frame already
cached by price_history; fundamental factors reuse the `info` /
quarterly_financials / quarterly_balance_sheet that fundamentals._yf_score
already fetches for the same ticker in the same scan. Adding independent fetches
here would have meant ~180 extra Yahoo calls per scan and re-triggered the
rate-limit quote-starvation that already broke a brief once.

MISSING DATA IS None, NEVER 0. A fabricated zero is a real number to a rank
correlation — it would quietly drag every IC toward noise. Factors that cannot
be computed are absent from the output dict.
"""

import logging
import math

import numpy as np

logger = logging.getLogger("discovery")

UNAVAILABLE = {"available": False}

# Published backtest Sharpe from the awesome-systematic-trading equity tables.
# Carried in-code so a measured IC can be reported next to the prior it is
# testing, and so a sign flip is visible rather than buried in a commit message.
FACTORS = {
    "fac_assetgrowth": {"paper": "Asset Growth Effect", "sharpe": 0.835,
                        "rebalance": "yearly", "kind": "fundamental",
                        "thesis": "firms growing assets fastest subsequently underperform"},
    "fac_streversal": {"paper": "Short Term Reversal Effect in Stocks", "sharpe": 0.816,
                       "rebalance": "weekly", "kind": "price",
                       "thesis": "last week's losers outperform next week"},
    "fac_size": {"paper": "Size Factor - Small Cap Premium", "sharpe": 0.747,
                 "rebalance": "yearly", "kind": "fundamental",
                 "thesis": "smaller caps earn a premium"},
    "fac_lowvol": {"paper": "Low Volatility Factor Effect in Stocks", "sharpe": 0.717,
                   "rebalance": "monthly", "kind": "price",
                   "thesis": "low realized vol outperforms high"},
    "fac_betaneg": {"paper": "Betting Against Beta Factor in Stocks", "sharpe": 0.594,
                    "rebalance": "monthly", "kind": "price",
                    "thesis": "low-beta names outperform per unit of risk"},
    "fac_trend": {"paper": "Trend-following Effect in Stocks", "sharpe": 0.569,
                  "rebalance": "daily", "kind": "price",
                  "thesis": "price above long trend keeps working"},
    "fac_roa": {"paper": "ROA Effect within Stocks", "sharpe": 0.155,
                "rebalance": "monthly", "kind": "fundamental",
                "thesis": "profitable firms outperform"},
    "fac_high52": {"paper": "52-Weeks High Effect in Stocks", "sharpe": 0.153,
                   "rebalance": "monthly", "kind": "price",
                   "thesis": "names near their 52w high keep climbing"},
    "fac_mom12_1": {"paper": "Momentum Factor Effect in Stocks", "sharpe": -0.008,
                    "rebalance": "monthly", "kind": "price",
                    "thesis": "CONTROL: classic 12-1 momentum, published as dead"},
    "fac_accrual": {"paper": "Accrual Anomaly", "sharpe": -0.272,
                    "rebalance": "yearly", "kind": "fundamental",
                    "thesis": "CONTROL: low-accrual premium, published as inverted"},
}

# Factors whose published Sharpe is <= 0. Their value is falsification, not
# alpha — evaluation reports them separately so a weak positive IC on a control
# is read as "the prior was wrong", not as "we found an edge".
CONTROLS = {k for k, v in FACTORS.items() if v["sharpe"] <= 0}

MIN_BARS_SHORT = 8      # 5d reversal needs a week plus slack
MIN_BARS_VOL = 65       # 60d realized vol
MIN_BARS_BETA = 120     # beta on a half-year-plus of overlap
MIN_BARS_TREND = 205    # 200-DMA
MIN_BARS_YEAR = 250     # 52w high, 12-1 momentum


def _closes(hist) -> np.ndarray | None:
    """Ascending float close series from a yfinance frame, or None."""
    if hist is None or len(hist) == 0 or "Close" not in hist:
        return None
    c = np.asarray(hist["Close"], dtype=float)
    c = c[~np.isnan(c)]
    return c if len(c) else None


def _row(df, labels):
    """First matching statement row across label spellings, NaNs dropped."""
    if df is None or getattr(df, "empty", True):
        return None
    for label in labels:
        try:
            if label in df.index:
                r = df.loc[label].dropna()
                if len(r):
                    return r
        except Exception:
            continue
    return None


def _pct_change(new, old):
    """Growth rate, or None when the base is unusable (zero/negative/missing)."""
    try:
        if new is None or old is None:
            return None
        new, old = float(new), float(old)
        if old <= 0 or math.isnan(new) or math.isnan(old):
            return None
        return (new - old) / old
    except Exception:
        return None


# --- price factors: reuse the already-cached daily frame -------------------

def _streversal(c):
    """Short-Term Reversal (Sharpe 0.816). Negated 5-day return: last week's
    biggest losers score highest, which is the paper's long leg."""
    if len(c) < MIN_BARS_SHORT:
        return None
    r = _pct_change(c[-1], c[-6])
    return None if r is None else -r


MOM_SKIP = 21        # ~1 month of sessions excluded from the momentum window
MOM_LOOKBACK = 252   # ~12 months


def _mom12_1(c):
    """Momentum 12-1 (Sharpe -0.008, CONTROL). 12-month return skipping the most
    recent month — the skip is what separates momentum from short-term reversal;
    without it the two factors partly cancel and both read as noise.

    The window ENDS at the last close before the skipped month, i.e. index
    -(MOM_SKIP + 1). Off-by-one here is not cosmetic: at -MOM_SKIP the most
    recent session leaks in and the factor starts absorbing exactly the
    short-term reversal it is supposed to exclude."""
    if len(c) < MIN_BARS_YEAR:
        return None
    return _pct_change(c[-(MOM_SKIP + 1)], c[-MOM_LOOKBACK])


def _lowvol(c):
    """Low Volatility (Sharpe 0.717). Negated annualized 60-day realized vol."""
    if len(c) < MIN_BARS_VOL:
        return None
    rets = np.diff(c[-61:]) / c[-61:-1]
    rets = rets[np.isfinite(rets)]
    if len(rets) < 20:
        return None
    return -float(np.std(rets, ddof=1) * math.sqrt(252))


def _trend(c):
    """Trend-following (Sharpe 0.569). Distance above the 200-DMA."""
    if len(c) < MIN_BARS_TREND:
        return None
    sma = float(np.mean(c[-200:]))
    return None if sma <= 0 else float(c[-1] / sma - 1.0)


def _high52(hist, c):
    """52-Week High Effect (Sharpe 0.153). Close as a fraction of the 52w high —
    1.0 means sitting on the high. Uses intraday highs, not closes: the effect is
    defined against the actual high the stock printed."""
    if len(c) < MIN_BARS_YEAR:
        return None
    try:
        highs = np.asarray(hist["High"], dtype=float)
        highs = highs[~np.isnan(highs)][-252:]
        hi = float(np.max(highs)) if len(highs) else None
    except Exception:
        hi = None
    if hi is None or hi <= 0:
        return None
    return float(c[-1] / hi)


def _beta(hist, bench):
    """Betting Against Beta (Sharpe 0.594). Negated beta vs the benchmark.

    Aligns on the shared DatetimeIndex before differencing — two frames of equal
    length can still cover different sessions (halts, late listings), and
    zipping them positionally would silently correlate mismatched days."""
    if hist is None or bench is None:
        return None
    try:
        import pandas as pd
        a = pd.Series(hist["Close"]).dropna()
        b = pd.Series(bench["Close"]).dropna()
        joined = pd.concat([a, b], axis=1, join="inner").dropna()
        if len(joined) < MIN_BARS_BETA:
            return None
        joined = joined.iloc[-252:]
        ra = joined.iloc[:, 0].pct_change().dropna().to_numpy(dtype=float)
        rb = joined.iloc[:, 1].pct_change().dropna().to_numpy(dtype=float)
        n = min(len(ra), len(rb))
        if n < 60:
            return None
        ra, rb = ra[-n:], rb[-n:]
        var_b = float(np.var(rb, ddof=1))
        if var_b <= 0:
            return None
        beta = float(np.cov(ra, rb, ddof=1)[0][1] / var_b)
        return -beta
    except Exception:
        return None


# --- fundamental factors: reuse statements fundamentals.py already fetched ---

def _total_assets(bs):
    return _row(bs, ["Total Assets", "TotalAssets"])


def _assetgrowth(bs):
    """Asset Growth Effect (Sharpe 0.835). Negated YoY total-asset growth —
    the paper's long leg is the SLOWEST asset growers."""
    r = _total_assets(bs)
    if r is None or len(r) < 4:
        return None
    g = _pct_change(r.iloc[0], r.iloc[3])
    return None if g is None else -g


def _roa(financials, bs, info):
    """ROA Effect (Sharpe 0.155). Net income over total assets."""
    r = _total_assets(bs)
    if r is None or len(r) == 0:
        return None
    try:
        assets = float(r.iloc[0])
    except Exception:
        return None
    if assets <= 0:
        return None
    ni_row = _row(financials, ["Net Income", "NetIncome",
                               "Net Income Common Stockholders"])
    ni = None
    if ni_row is not None and len(ni_row) >= 4:
        try:
            ni = float(np.sum(np.asarray(ni_row.iloc[:4], dtype=float)))  # TTM
        except Exception:
            ni = None
    if ni is None:
        ni = (info or {}).get("netIncomeToCommon")
    if ni is None:
        return None
    try:
        return float(ni) / assets
    except Exception:
        return None


def _accrual(financials, bs, info):
    """Accrual Anomaly (Sharpe -0.272, CONTROL). Negated (earnings - cash flow)
    scaled by assets: Sloan's low-accrual long leg scores highest.

    Uses info['operatingCashflow'] (TTM, already fetched by fundamentals) rather
    than pulling quarterly_cashflow, which would be an extra call per ticker."""
    r = _total_assets(bs)
    if r is None or len(r) == 0:
        return None
    try:
        assets = float(r.iloc[0])
    except Exception:
        return None
    if assets <= 0:
        return None
    ni_row = _row(financials, ["Net Income", "NetIncome",
                               "Net Income Common Stockholders"])
    ni = None
    if ni_row is not None and len(ni_row) >= 4:
        try:
            ni = float(np.sum(np.asarray(ni_row.iloc[:4], dtype=float)))
        except Exception:
            ni = None
    if ni is None:
        ni = (info or {}).get("netIncomeToCommon")
    ocf = (info or {}).get("operatingCashflow")
    if ni is None or ocf is None:
        return None
    try:
        return -((float(ni) - float(ocf)) / assets)
    except Exception:
        return None


def _size(info):
    """Size Premium (Sharpe 0.747). Negated log10 market cap — smallest highest.
    Log because market cap spans four orders of magnitude across this universe;
    raw dollars would make the rank correlation a proxy for a handful of names."""
    mcap = (info or {}).get("marketCap")
    try:
        mcap = float(mcap) if mcap else 0.0
    except Exception:
        return None
    if mcap <= 0:
        return None
    return -math.log10(mcap)


def compute(hist, info: dict = None, financials=None, balance_sheet=None,
            bench=None) -> dict:
    """All computable academic factors for one ticker.

    hist          — cached 1y daily OHLCV frame (price_history.get_history)
    info          — yfinance .info dict already fetched by fundamentals
    financials    — quarterly_financials frame already fetched by fundamentals
    balance_sheet — quarterly_balance_sheet frame already fetched by fundamentals
    bench         — benchmark daily frame (SPY) for beta; optional

    Returns {"available": bool, "values": {name: float}, "n_available": int}.
    Absent factors are simply missing from `values` — never zero-filled.
    """
    c = _closes(hist)
    values = {}

    if c is not None:
        for name, fn in (
            ("fac_streversal", lambda: _streversal(c)),
            ("fac_mom12_1", lambda: _mom12_1(c)),
            ("fac_lowvol", lambda: _lowvol(c)),
            ("fac_trend", lambda: _trend(c)),
            ("fac_high52", lambda: _high52(hist, c)),
        ):
            try:
                v = fn()
            except Exception:
                v = None
            if v is not None and math.isfinite(v):
                values[name] = round(float(v), 6)
        try:
            b = _beta(hist, bench)
        except Exception:
            b = None
        if b is not None and math.isfinite(b):
            values["fac_betaneg"] = round(float(b), 6)

    for name, fn in (
        ("fac_assetgrowth", lambda: _assetgrowth(balance_sheet)),
        ("fac_roa", lambda: _roa(financials, balance_sheet, info)),
        ("fac_accrual", lambda: _accrual(financials, balance_sheet, info)),
        ("fac_size", lambda: _size(info)),
    ):
        try:
            v = fn()
        except Exception:
            v = None
        if v is not None and math.isfinite(v):
            values[name] = round(float(v), 6)

    return {"available": bool(values), "values": values,
            "n_available": len(values)}
