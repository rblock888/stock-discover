"""Sanity tests for the decision-math — pure logic, no network.

Covers the pieces a trader actually relies on: composite scoring + coverage,
the edge gauges, regime tilt bounds, evaluation statistics (Spearman/isotonic),
SPY-relative momentum, and the junk-ticker filter.

Run: python -m pytest tests/ -q
"""

import math

import numpy as np
import pandas as pd
import pytest


# ── scorer: coverage renormalization, NaN, alert gating ──────────────────────

import scorer


def _bucket(score, covered=True):
    return {"score": score, "components": ({"x": "y"} if covered else {})}


def test_composite_all_covered_is_weighted_average():
    bs = {k: _bucket(60) for k in ("fundamentals", "momentum", "catalyst", "insider", "sentiment")}
    r = scorer.composite_score(bs)
    assert r["composite"] == pytest.approx(60.0, abs=0.1)
    assert r["coverage"] == pytest.approx(1.0)


def test_composite_renormalizes_over_covered_buckets():
    # only fundamentals (0.30) + momentum (0.25) have data
    bs = {
        "fundamentals": _bucket(80),
        "momentum": _bucket(75),
        "catalyst": _bucket(50, covered=False),
        "insider": _bucket(50, covered=False),
        "sentiment": _bucket(50, covered=False),
    }
    r = scorer.composite_score(bs)
    expected = (80 * 0.30 + 75 * 0.25) / (0.30 + 0.25)
    assert r["composite"] == pytest.approx(expected, abs=0.1)
    assert r["coverage"] == pytest.approx(0.55, abs=0.01)


def test_composite_nan_score_does_not_poison():
    bs = {k: _bucket(60) for k in ("fundamentals", "momentum", "catalyst", "insider", "sentiment")}
    bs["momentum"]["score"] = float("nan")
    r = scorer.composite_score(bs)
    assert math.isfinite(r["composite"])


def test_multi_signal_alert_ignores_uncovered_placeholders():
    # four buckets >=60 but uncovered (no data) → must NOT trigger the alert
    bs = {k: _bucket(80, covered=False) for k in ("fundamentals", "momentum", "catalyst", "insider")}
    bs["sentiment"] = _bucket(80, covered=True)
    r = scorer.composite_score(bs)
    assert r["multi_signal_alert"] is False


def test_per_call_weights_do_not_mutate_global():
    import config
    before = dict(config.WEIGHTS)
    bs = {k: _bucket(60) for k in before}
    scorer.composite_score(bs, weights={**before, "momentum": 0.9})
    assert config.WEIGHTS == before  # global untouched


# ── ticker_edge: gauges from synthetic OHLCV ─────────────────────────────────

import ticker_edge


def _frame(closes, vol=1_000_000):
    n = len(closes)
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    c = np.array(closes, dtype=float)
    return pd.DataFrame({
        "Open": c, "High": c * 1.01, "Low": c * 0.99, "Close": c,
        "Volume": np.full(n, vol, dtype=float),
    }, index=idx)


def test_edge_unavailable_on_short_history():
    out = ticker_edge.compute("X", _frame([10] * 30))
    assert out["available"] is False


def test_edge_clean_uptrend():
    closes = list(np.linspace(10, 20, 90))  # smooth steady rise
    out = ticker_edge.compute("X", _frame(closes))
    assert out["available"] is True
    assert out["above_20ma"] is True
    assert out["bearing"]["state"] in ("CLEAN UP", "CHOPPY UP")
    assert out["bearing"]["state"] == "CLEAN UP"  # high efficiency ratio


def test_edge_flat_market_is_not_trending():
    rng = np.random.default_rng(0)
    closes = 10 + rng.normal(0, 0.05, 90).cumsum() * 0  # ~flat
    closes = [10.0] * 90
    out = ticker_edge.compute("X", _frame(closes))
    assert out["bearing"]["state"] == "FLAT"


def test_edge_flow_bands():
    closes = list(np.linspace(10, 12, 90))
    f = _frame(closes)
    f.iloc[-1, f.columns.get_loc("Volume")] = 5_000_000  # 5x volume today
    out = ticker_edge.compute("X", f)
    assert out["flow"]["rvol"] > 2.5
    assert out["flow"]["state"] == "CROWDED"


def test_piecewise_interpolates_and_clamps():
    pts = [(0, 10), (1, 20), (2, 0)]
    assert ticker_edge._piecewise(-5, pts) == 10   # clamp low
    assert ticker_edge._piecewise(5, pts) == 0     # clamp high
    assert ticker_edge._piecewise(0.5, pts) == pytest.approx(15)


# ── regime_tilt: bounds, neutrality, direction ───────────────────────────────

import regime_tilt

_REGIME = {
    "available": True, "mood": {"label": "RISK-ON"},
    "volatility": {"state": "TRADABLE"}, "smallcap": {"state": "HOT"},
    "sectors": [{"name": "Semis"}, {"name": "Tech"}, {"name": "Energy"},
                {"name": "Staples"}, {"name": "Utilities"}, {"name": "Discretionary"}],
}


def _stock(**kw):
    base = {
        "composite": 60,
        "quote": {"market_cap": 5e8, "sector": "Technology", "industry": "Semiconductors"},
        "edge": {"flow": {"state": "HEALTHY"}, "bearing": {"state": "CLEAN UP"}, "pulse": {"state": "TRADABLE"}},
        "short_squeeze": {"score": 40},
    }
    base.update(kw)
    return base


def test_tilt_neutral_without_regime():
    assert regime_tilt.compute_tilt(_stock(), {"available": False})["factor"] == 1.0


def test_tilt_bounds():
    for s in (_stock(), _stock(edge={"flow": {"state": "THIN"}, "bearing": {"state": "DOWN"}, "pulse": {"state": "WILD"}})):
        for reg in (_REGIME, {**_REGIME, "mood": {"label": "RISK-OFF"}, "volatility": {"state": "WILD"}, "smallcap": {"state": "COLD"}}):
            f = regime_tilt.compute_tilt(s, reg)["factor"]
            assert 0.7 <= f <= 1.3


def test_tilt_boosts_ideal_breakout_and_logs_reasons():
    out = regime_tilt.compute_tilt(_stock(), _REGIME)
    assert out["factor"] > 1.0
    assert out["reasons"]  # explanations present


# ── evaluation: statistics ───────────────────────────────────────────────────

import evaluation


def test_spearman_monotonic_relationships():
    x = np.arange(50.0)
    assert evaluation._spearman(x, x) == pytest.approx(1.0, abs=1e-6)
    assert evaluation._spearman(x, x[::-1]) == pytest.approx(-1.0, abs=1e-6)


def test_isotonic_is_monotonic_nondecreasing():
    x = np.arange(20.0)
    y = np.array([0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 1, 0, 1, 1, 1, 0, 1, 1, 1, 1], dtype=float)
    _, fit = evaluation._isotonic(x, y)
    assert all(fit[i] <= fit[i + 1] + 1e-9 for i in range(len(fit) - 1))


def test_rankdata_handles_ties():
    r = evaluation._rankdata(np.array([10.0, 10.0, 20.0]))
    assert r[0] == pytest.approx(1.5) and r[1] == pytest.approx(1.5)
    assert r[2] == pytest.approx(3.0)


def test_entry_exit_horizon_and_out_of_range():
    days = np.array([f"2024-01-{d:02d}" for d in range(1, 11)])
    closes = np.arange(10, 20, dtype=float)
    e, x = evaluation._entry_exit(days, closes, "2024-01-02", 3)
    assert e == 11.0 and x == 14.0   # idx1 → idx4
    assert evaluation._entry_exit(days, closes, "2024-01-09", 5) == (None, None)  # past the end


# ── momentum: SPY-relative strength ──────────────────────────────────────────

import momentum


def test_momentum_relative_strength_uses_spy_excess():
    n = 120
    # stock and SPY both up the same amount → RS should be ~neutral (not high)
    stock = list(np.linspace(10, 13, n))           # +30%
    spy = list(np.linspace(400, 520, n))           # +30%
    newest_first = list(reversed(stock))
    vols = [1_000_000] * n
    r_match = momentum._calc_momentum(newest_first, list(reversed(vols)), spy_closes=spy)
    # a stock beating SPY strongly should score higher RS than one matching it
    stock_strong = list(np.linspace(10, 20, n))    # +100% vs SPY +30%
    r_strong = momentum._calc_momentum(list(reversed(stock_strong)), list(reversed(vols)), spy_closes=spy)
    assert r_strong["score"] > r_match["score"]
    assert "vs SPY" in r_match["components"].get("rel_strength", "")


# ── universe_builder: junk-ticker filter ─────────────────────────────────────

import universe_builder


@pytest.mark.parametrize("junk", ["FDA", "GPU", "CLASS", "NCAA", "PCAOB", "ETF", "CEO", "THE", "AI"])
def test_junk_tickers_rejected(junk):
    assert not universe_builder._looks_like_ticker(junk)


@pytest.mark.parametrize("real", ["NVDA", "LWLG", "IONQ", "TGTX", "MU", "AMD"])
def test_real_tickers_kept(real):
    assert universe_builder._looks_like_ticker(real)
