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
    # only fundamentals + momentum have data — read weights from config so this
    # tests the RENORMALIZATION logic, not a stale snapshot of the weights
    import config
    wf, wm = config.WEIGHTS["fundamentals"], config.WEIGHTS["momentum"]
    bs = {
        "fundamentals": _bucket(80),
        "momentum": _bucket(75),
        "catalyst": _bucket(50, covered=False),
        "insider": _bucket(50, covered=False),
        "sentiment": _bucket(50, covered=False),
    }
    r = scorer.composite_score(bs)
    expected = (80 * wf + 75 * wm) / (wf + wm)
    assert r["composite"] == pytest.approx(expected, abs=0.1)
    assert r["coverage"] == pytest.approx(wf + wm, abs=0.01)


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


# ── evaluation: robust statistics (quarantine, winsorize, daily IC, NW-t) ────


def test_quarantine_flags_artifact_returns():
    rows = [{"ticker": "OK", "snap_day": "2026-06-20", "fwd_return": 0.4},
            {"ticker": "BAD", "snap_day": "2026-06-20", "fwd_return": 38.1}]  # +3810%
    kept, flagged = evaluation._quarantine(rows, horizon=10)
    assert [r["ticker"] for r in kept] == ["OK"]
    assert flagged[0]["ticker"] == "BAD"
    # long horizons are exempt (a 60d 4x on a microcap is possible alpha)
    kept60, flagged60 = evaluation._quarantine(rows, horizon=60)
    assert len(kept60) == 2 and not flagged60


def test_nw_tstat_sane():
    # constant strong series → decisive t; tiny series → None
    t = evaluation._nw_tstat([0.3, 0.28, 0.32, 0.29, 0.31, 0.3, 0.27, 0.33], lag=4)
    assert t is not None and t > 5
    assert evaluation._nw_tstat([0.3, 0.2], lag=4) is None
    # sign-alternating noise around zero → |t| small
    t2 = evaluation._nw_tstat([0.3, -0.3, 0.25, -0.28, 0.31, -0.27, 0.29, -0.3], lag=4)
    assert t2 is not None and abs(t2) < 2


def test_daily_ics_groups_and_min_names(monkeypatch):
    monkeypatch.setattr(evaluation, "_trading_days", lambda: None)  # accept all dates
    rows = []
    # day 1: 10 names, perfectly monotonic (IC = 1)
    for i in range(10):
        rows.append(("2026-06-20", float(i), float(i)))
    # day 2: only 3 names — must be dropped (below MIN_NAMES_PER_DAY)
    for i in range(3):
        rows.append(("2026-06-23", float(i), float(-i)))
    out = evaluation._daily_ics(rows)
    assert len(out) == 1
    assert out[0][0] == "2026-06-20" and out[0][1] == pytest.approx(1.0, abs=1e-6)


def test_evidence_weights_never_recommends_extreme(monkeypatch):
    """Even with a wildly one-sided IC picture, the shrunk recommendation stays
    inside [0.05, 0.50] per bucket — no more 100%-catalyst off a 3-day window."""
    days = [f"2026-06-{d:02d}" for d in range(2, 28)]
    rets, feats = [], []
    for di, day in enumerate(days):
        for i in range(12):
            t = f"T{i}"
            cat = float(i * 8)
            ret = 0.002 * i + 0.001 * di          # catalyst perfectly predictive
            rets.append({"ticker": t, "snap_day": day, "horizon": 5,
                         "fwd_return": ret, "excess_return": ret})
            feats.append({"ticker": t, "scan_date": day,
                          "bucket_scores": json.dumps({
                              "fundamentals": 50.0, "momentum": 50.0, "catalyst": cat,
                              "insider": 50.0, "sentiment": 50.0}),
                          "composite_score": 50.0, "tilt_factor": None, "rank_score": None,
                          "coiled_score": None, "setup_grade": None, "setup_score": None,
                          "setup_type": None, "setup_plan": None, "regime_label": None})
    monkeypatch.setattr(db, "get_snapshot_returns", lambda h=None: rets)
    monkeypatch.setattr(db, "get_snapshot_features", lambda: feats)
    monkeypatch.setattr(evaluation, "_trading_days", lambda: None)
    out = evaluation.evidence_weights(5)
    for b, w in out["shrunk_weights"].items():
        assert 0.04 <= w <= 0.51, f"{b} weight {w} escaped the clamp"
    assert sum(out["shrunk_weights"].values()) == pytest.approx(1.0, abs=0.02)


import json


# ── evaluation: grade_scorecard — does conviction grade predict returns? ─────

import db


def _fake_snapshot_returns_and_features(monkeypatch, grade_return_pairs, horizon=20):
    """Wire db.get_snapshot_returns/get_snapshot_features to synthetic data so
    grade_scorecard() can be tested without touching sqlite."""
    rets, feats = [], []
    for i, (grade, ret) in enumerate(grade_return_pairs):
        ticker, day = f"T{i}", f"2024-01-{(i % 28) + 1:02d}"
        rets.append({"ticker": ticker, "snap_day": day, "horizon": horizon,
                     "fwd_return": ret, "excess_return": ret - 0.01})
        feats.append({"ticker": ticker, "scan_date": day, "setup_grade": grade,
                      "setup_score": None, "setup_type": None, "composite_score": None,
                      "tilt_factor": None, "rank_score": None, "bucket_scores": None,
                      "coiled_score": None})
    monkeypatch.setattr(db, "get_snapshot_returns", lambda h=None: rets if h == horizon else [])
    monkeypatch.setattr(db, "get_snapshot_features", lambda: feats)


def test_grade_scorecard_accrues_below_min_n(monkeypatch):
    pairs = [("A", 0.15)] * 10  # well under MIN_N_GRADE=120
    _fake_snapshot_returns_and_features(monkeypatch, pairs)
    out = evaluation.grade_scorecard(horizon=20)
    assert out["status"] == "accruing"
    assert out["available"] is False
    assert out["n"] == 10


def test_grade_scorecard_detects_clean_signal(monkeypatch):
    """A > B > C > AVOID on forward returns → positive grade_ic, no inversion."""
    pairs = (
        [("A", 0.30)] * 30 + [("B", 0.12)] * 30 +
        [("C", 0.02)] * 30 + [("AVOID", -0.15)] * 30
    )
    _fake_snapshot_returns_and_features(monkeypatch, pairs)
    out = evaluation.grade_scorecard(horizon=20)
    assert out["status"] == "ready"
    assert out["grade_ic"] > 0.5
    assert out["inversion"] is None
    assert out["avoid_outperforms_a"] is False
    by_grade = {g["grade"]: g for g in out["grades"]}
    assert by_grade["A"]["avg_return_pct"] > by_grade["AVOID"]["avg_return_pct"]


def test_grade_scorecard_detects_inversion(monkeypatch):
    """AVOID outperforming A → inversion flagged, mirroring the ml_score no-edge finding."""
    pairs = (
        [("A", -0.10)] * 30 + [("B", 0.02)] * 30 +
        [("C", 0.05)] * 30 + [("AVOID", 0.25)] * 30
    )
    _fake_snapshot_returns_and_features(monkeypatch, pairs)
    out = evaluation.grade_scorecard(horizon=20)
    assert out["status"] == "ready"
    assert out["grade_ic"] < 0
    assert out["avoid_outperforms_a"] is True
    assert out["inversion"] is not None


def test_grade_scorecard_excludes_no_setup_from_correlation(monkeypatch):
    """'—' rows show up in the per-grade table but must not pollute grade_ic."""
    pairs = (
        [("A", 0.30)] * 30 + [("B", 0.12)] * 30 +
        [("C", 0.02)] * 30 + [("AVOID", -0.15)] * 30 + [("—", 0.50)] * 20
    )
    _fake_snapshot_returns_and_features(monkeypatch, pairs)
    out = evaluation.grade_scorecard(horizon=20)
    by_grade = {g["grade"]: g for g in out["grades"]}
    assert "—" in by_grade
    assert out["grade_ic"] > 0.5


def test_grade_scorecard_flags_low_n_per_grade(monkeypatch):
    pairs = [("A", 0.20)] * 115 + [("AVOID", -0.10)] * 8  # AVOID under the per-bucket floor
    _fake_snapshot_returns_and_features(monkeypatch, pairs)
    out = evaluation.grade_scorecard(horizon=20)
    by_grade = {g["grade"]: g for g in out["grades"]}
    assert by_grade["AVOID"]["low_n"] is True
    assert by_grade["A"]["low_n"] is False


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


def test_prefly_rerank_favors_coiled_over_hyped_extended(monkeypatch):
    """A quiet coiling name mentioned by 1 source should out-rank an already-
    extended gainer mentioned by 5 sources — the whole point of the re-rank."""
    import pre_breakout as pb

    idx = pd.date_range("2024-01-01", periods=150, freq="B")
    quiet_hist = pd.DataFrame({"Close": np.full(150, 10.0), "High": np.full(150, 10.1),
                               "Low": np.full(150, 9.9), "Volume": np.full(150, 5e5)}, index=idx)
    hyped_hist = pd.DataFrame({"Close": np.full(150, 50.0), "High": np.full(150, 50.5),
                               "Low": np.full(150, 49.5), "Volume": np.full(150, 5e6)}, index=idx)

    def fake_get_histories(symbols, period="1y", max_age=None):
        return {"QUIET": quiet_hist, "HYPED": hyped_hist}

    def fake_compute(ticker, hist):
        if ticker == "QUIET":
            return {"available": True, "state": "COILED", "coiled_score": 82}
        return {"available": True, "state": "EXTENDED", "coiled_score": 20}

    monkeypatch.setattr("price_history.get_histories", fake_get_histories)
    monkeypatch.setattr(pb, "compute", fake_compute)

    tickers = ["HYPED", "QUIET"]  # HYPED first by attention
    source_counts = {"HYPED": 5, "QUIET": 1}
    out, meta = universe_builder._prefly_rerank(tickers, source_counts, limit=10)
    assert out.index("QUIET") < out.index("HYPED")
    assert meta["QUIET"]["prefly"] > meta["HYPED"]["prefly"]   # components persisted


def test_prefly_rerank_never_raises_on_failure(monkeypatch):
    monkeypatch.setattr("price_history.get_histories", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    out, meta = universe_builder._prefly_rerank(["A", "B"], {"A": 1, "B": 1}, limit=10)
    assert out == ["A", "B"]  # unchanged, no crash
    assert meta == {}


# ── api: discovery-quality gates (mega-cap / closed-end fund exclusion) ──────

import api


def test_is_mega_cap():
    assert api._is_mega_cap({"market_cap": 300_000_000_000}) is True   # Novo Nordisk-scale
    assert api._is_mega_cap({"market_cap": 20_000_000_000}) is False   # SOFI-scale, allowed
    assert api._is_mega_cap({}) is False


def test_is_fund_or_trust():
    # closed-end fund: Asset Management industry, no employees (no operating business)
    assert api._is_fund_or_trust({"industry": "Asset Management", "employees": None}) is True
    assert api._is_fund_or_trust({"industry": "Asset Management", "employees": 0}) is True
    # a real asset-management COMPANY (e.g. Franklin Resources) has employees
    assert api._is_fund_or_trust({"industry": "Asset Management", "employees": 9000}) is False
    assert api._is_fund_or_trust({"industry": "Biotechnology", "employees": None}) is False
    assert api._is_fund_or_trust({}) is False


# ── pre_breakout: catch coils, flag the already-flown ────────────────────────

import pre_breakout


def test_pre_breakout_flags_already_flown_as_extended():
    # flat base then a sharp run = the "flew to the roof" chart = EXTENDED
    closes = [10.0] * 90 + list(np.linspace(10, 26, 50))  # +160% sharp recent move
    out = pre_breakout.compute("X", _frame(closes))
    assert out["available"] is True
    assert out["state"] == "EXTENDED"
    assert out["coiled_score"] <= 40


def test_pre_breakout_rewards_tight_compressed_base():
    # long flat, tightly-ranging base = compressed coil, not extended
    rng = np.random.default_rng(1)
    closes = list(10 + rng.normal(0, 0.04, 140))  # very tight around 10
    out = pre_breakout.compute("X", _frame(closes))
    assert out["available"] is True
    assert out["state"] in ("COILED", "BASING")
    assert out["coiled_score"] >= 50
    assert out["ext_pct"] is not None and abs(out["ext_pct"]) < 10  # not extended


def test_pre_breakout_unavailable_on_short_history():
    assert pre_breakout.compute("X", _frame([10] * 60))["available"] is False


# ── book_signals: daily-bar detectors from the books ─────────────────────────

import book_signals


def _ohlc_frame(o, h, l, c, v):
    return pd.DataFrame({"Open": o, "High": h, "Low": l, "Close": c, "Volume": v})


def _synthetic_accumulation():
    """Down-leg then a flat base = ACCUMULATION; ends with a hammer at the low."""
    down = np.linspace(40, 20, 90)
    base = 20 + np.random.default_rng(1).normal(0, 0.2, 60)
    c = np.concatenate([down, base])
    o = c + 0.05
    h = c + 0.3
    l = c - 0.3
    v = np.full(len(c), 1_000_000.0)
    # last candle = hammer (long lower wick, close near top of range)
    o[-1], c[-1], h[-1], l[-1] = 20.0, 20.4, 20.5, 19.0
    return _ohlc_frame(o, h, l, c, v)


def test_book_market_phase_accumulation():
    bk = book_signals.compute(_synthetic_accumulation())
    assert bk["available"] is True
    assert bk["phase"]["state"] in ("ACCUMULATION", "NEUTRAL")  # base after a decline


def test_book_volume_profile_and_plan_shapes():
    bk = book_signals.compute(_synthetic_accumulation())
    prof = bk["profile"]
    assert prof and prof["val"] <= prof["poc"] <= prof["vah"]
    assert prof["position"] in ("above", "inside", "below")
    plan = bk["plan"]
    if plan:  # only when a tight structural stop exists
        assert plan["stop"] < plan["entry"] < plan["target"]
        assert plan["rr"] > 0


def test_book_reversal_hammer_detected():
    rev = book_signals.compute(_synthetic_accumulation())["reversal"]
    assert rev is not None and rev["bullish"] is True


def test_book_unavailable_on_short_history():
    arr = np.arange(10.0, 30.0)
    short = _ohlc_frame(arr, arr + 0.2, arr - 0.2, arr, np.full(20, 1e6))
    assert book_signals.compute(short).get("available") is False


def _wrap(c):
    c = np.asarray(c, dtype=float)
    return _ohlc_frame(c, c + 0.2, c - 0.2, c, np.full(len(c), 1e6))


def test_book_double_bottom_detected():
    c = np.concatenate([
        np.linspace(30, 20, 24),      # decline to bottom 1
        np.linspace(20, 26, 14),      # rise to neckline
        np.linspace(26, 20.2, 14),    # decline to bottom 2 (~ same low)
        np.linspace(20.2, 27, 12),    # break above neckline
    ])
    db = book_signals.compute(_wrap(c))["double_bottom"]
    assert db["active"] is True and db["confirmed"] is True


def test_book_reverse_hns_detected():
    c = np.concatenate([
        np.linspace(30, 24, 16),      # left shoulder low
        np.linspace(24, 27, 12),
        np.linspace(27, 21, 16),      # head (lowest)
        np.linspace(21, 27, 14),
        np.linspace(27, 24.2, 14),    # right shoulder (~ left)
        np.linspace(24.2, 28, 12),    # break neckline
    ])
    rh = book_signals.compute(_wrap(c))["reverse_hns"]
    assert rh["active"] is True


def test_book_ema_stack_bullish_on_uptrend():
    ema = book_signals.compute(_wrap(np.linspace(10, 30, 220)))["ema"]
    assert ema["stack_bullish"] is True and ema["above_200"] is True


# ── setup_backtest: trade simulation ─────────────────────────────────────────

import setup_backtest


def test_backtest_tradeable_fill_at_next_open():
    """'now' plans fill at the NEXT bar's open, not the signal close; the
    tradeable R is measured from that fill (with slippage), exact leg from plan."""
    o = np.array([10.0, 10.2, 11.0, 12.5])
    h = np.array([10.0, 10.5, 12.2, 13.0])
    l = np.array([10.0, 10.0, 11.0, 12.0])
    c = np.array([10.0, 10.2, 12.0, 12.5])
    sim = setup_backtest._simulate(o, h, l, c, 0, 10.0, 9.0, 12.0, entry_type="now", atr=0.5)
    assert sim["outcome"] == "target"
    assert sim["fill"] == pytest.approx(10.2)          # next open, not 10.0
    assert sim["r_exact"] == pytest.approx(2.0)        # idealized leg preserved
    # tradeable R < exact R: worse fill + slippage both charged
    assert sim["r"] < sim["r_exact"]


def test_backtest_skips_gapped_entries():
    """A next-open that gaps through the stop, or drifts >3% from the plan
    entry, is a skipped trade — not a fantasy fill."""
    o = np.array([10.0, 8.8, 9.0, 9.2])   # gaps below the 9.0 stop
    h = np.array([10.0, 9.5, 9.5, 9.5])
    l = np.array([10.0, 8.5, 8.8, 9.0])
    c = np.array([10.0, 9.0, 9.2, 9.3])
    sim = setup_backtest._simulate(o, h, l, c, 0, 10.0, 9.0, 12.0, entry_type="now", atr=0.5)
    assert sim["outcome"] == "skipped_gap" and sim["r"] is None
    assert sim["r_exact"] is not None                  # exact leg still recorded
    o2 = np.array([10.0, 10.5, 11.0, 12.5])            # +5% drift off plan entry
    sim2 = setup_backtest._simulate(o2, h, l, c, 0, 10.0, 9.0, 12.0, entry_type="now", atr=0.5)
    assert sim2["outcome"] == "skipped_gap"


def test_backtest_pullback_only_fills_if_touched():
    """The phantom-fill bug: a pullback limit BELOW the market must not fill
    unless price actually returns to it."""
    # price runs away — limit at 9.5 never touched
    o = np.array([10.0, 10.2, 10.8, 11.5, 12.0, 12.5, 13.0])
    h = np.array([10.0, 10.5, 11.2, 12.0, 12.5, 13.0, 13.5])
    l = np.array([10.0, 10.0, 10.5, 11.2, 11.8, 12.2, 12.8])
    c = np.array([10.0, 10.4, 11.0, 11.8, 12.3, 12.8, 13.2])
    sim = setup_backtest._simulate(o, h, l, c, 0, 9.5, 9.0, 12.0, entry_type="pullback", atr=0.5)
    assert sim["outcome"] == "unfilled" and sim["r"] is None
    # price comes back and touches the limit intrabar -> fills AT the limit
    l2 = np.array([10.0, 9.4, 10.5, 11.2, 11.8, 12.2, 12.8])
    sim2 = setup_backtest._simulate(o, h, l2, c, 0, 9.5, 9.0, 12.0, entry_type="pullback", atr=0.5)
    assert sim2["outcome"] == "target"
    assert sim2["fill"] == pytest.approx(9.5)


def test_backtest_gap_exit_at_open_not_stop():
    """An overnight gap through the stop exits at the OPEN — the real loss is
    bigger than -1R. The old simulator pretended you got the stop price."""
    o = np.array([10.0, 10.1, 8.0, 8.2])   # bar 2 gaps far below the 9.0 stop
    h = np.array([10.0, 10.3, 8.5, 8.5])
    l = np.array([10.0, 9.9, 7.8, 8.0])
    c = np.array([10.0, 10.0, 8.2, 8.3])
    sim = setup_backtest._simulate(o, h, l, c, 0, 10.0, 9.0, 12.0, entry_type="now", atr=0.5)
    assert sim["outcome"] == "stop"
    assert sim["r"] < -1.5                  # much worse than the -1R fiction


def test_backtest_wilson_ci_and_expectancy_lb():
    """Small samples get honest uncertainty: 5-of-6 wins → wide Wilson CI, and
    setups sort by lower-bound expectancy, not the raw mean."""
    trades = ([{"setup": "TinyN", "r": 1.0, "r_exact": 1.0, "outcome": "target",
                "mfe_r": 1.0, "mae_r": -0.2}] * 5 +
              [{"setup": "TinyN", "r": -1.0, "r_exact": -1.0, "outcome": "stop",
                "mfe_r": 0.1, "mae_r": -1.0}] +
              [{"setup": "BigN", "r": 0.3, "r_exact": 0.3, "outcome": "target",
                "mfe_r": 0.5, "mae_r": -0.1}] * 100)
    agg = setup_backtest._aggregate(trades)
    by = {r["setup"]: r for r in agg["by_setup"]}
    lo, hi = by["TinyN"]["win_ci"]
    assert lo < 50 and hi > 90                      # 5/6 is compatible with a coin flip
    assert by["BigN"]["expectancy_lb"] > by["TinyN"]["expectancy_lb"]
    assert agg["by_setup"][0]["setup"] == "BigN"    # lb-sort puts the real sample first


# ── news cache: dilution + event classification ─────────────────────────────

import news_cache
from datetime import datetime as _dtm, timedelta as _tdelta


def _fake_news(monkeypatch, titles_with_age):
    now = _dtm.now()
    items = [{"title": t, "summary": "", "publisher": "PRN",
              "pub_time": now - _tdelta(days=age) if age is not None else None}
             for t, age in titles_with_age]
    monkeypatch.setattr(news_cache, "get_news", lambda ticker: items)


def test_news_dilution_detected_and_completion_excluded(monkeypatch):
    _fake_news(monkeypatch, [("XYZ Announces $10M Registered Direct Offering", 2)])
    assert news_cache.fresh_dilution_headline("XYZ") is not None
    # a CLOSED offering is behind the stock, not ahead of it
    _fake_news(monkeypatch, [("XYZ Announces Closing of $10M Offering", 2)])
    assert news_cache.fresh_dilution_headline("XYZ") is None
    # stale (>7d) dilution is ignored
    _fake_news(monkeypatch, [("XYZ Announces Offering", 12)])
    assert news_cache.fresh_dilution_headline("XYZ") is None
    # undated headlines are ignored (yfinance recycles stale stories)
    _fake_news(monkeypatch, [("XYZ Announces Offering", None)])
    assert news_cache.fresh_dilution_headline("XYZ") is None


def test_news_event_classifier(monkeypatch):
    _fake_news(monkeypatch, [("XYZ Receives FDA Approval for Lead Drug", 1)])
    assert news_cache.classify_event("XYZ") == 90
    _fake_news(monkeypatch, [("XYZ Announces Reverse Split", 1)])
    assert news_cache.classify_event("XYZ") == 10
    _fake_news(monkeypatch, [("XYZ Appoints VP of Sales", 1)])
    assert news_cache.classify_event("XYZ") == 50


def test_conviction_dilution_forces_watch():
    stock = {
        "composite": 64, "quote": {"market_cap": 6e8},
        "breakdown": {"fundamentals": {"raw": 82}, "insider": {"raw": 70}, "catalyst": {"raw": 75}},
        "tilt": {"factor": 1.12},
        "news_flags": {"dilution": "Announces $50M At-The-Market Program"},
        "smad": {"available": True, "state": "DEMAND RETEST", "smad_score": 78, "demand_zone": [4.0, 4.3]},
        "coiled": {"state": "BASING"},
        "edge": {"above_20ma": True, "flow": {"state": "HEALTHY"}, "bearing": {"state": "CLEAN UP"}},
        "book": {"available": True, "phase": {"state": "ACCUMULATION"}, "rbs": {}, "reversal": {},
                 "profile": {"position": "inside"},
                 "plan": {"entry": 4.2, "stop": 3.9, "target": 4.9, "rr": 2.3, "risk_pct": 7.1}},
    }
    v = conviction.assess(stock, _RISK_ON)
    assert v["grade"] == "WATCH"
    assert any("dilution" in c for c in v["cautions"])
    assert v["plan"] is not None    # plan stays visible — "not yet", not "never"


def test_conviction_imminent_earnings_forces_watch():
    stock = {
        "composite": 64, "quote": {"market_cap": 6e8},
        "breakdown": {"fundamentals": {"raw": 82}, "insider": {"raw": 70},
                      "catalyst": {"raw": 75, "metrics": {"earnings_days": 2}}},
        "tilt": {"factor": 1.12},
        "smad": {"available": True, "state": "DEMAND RETEST", "smad_score": 78, "demand_zone": [4.0, 4.3]},
        "coiled": {"state": "BASING"},
        "edge": {"above_20ma": True, "flow": {"state": "HEALTHY"}, "bearing": {"state": "CLEAN UP"}},
        "book": {"available": True, "phase": {"state": "ACCUMULATION"}, "rbs": {}, "reversal": {},
                 "profile": {"position": "inside"},
                 "plan": {"entry": 4.2, "stop": 3.9, "target": 4.9, "rr": 2.3, "risk_pct": 7.1}},
    }
    v = conviction.assess(stock, _RISK_ON)
    assert v["grade"] == "WATCH"
    assert any("enter after the print" in c for c in v["cautions"])


# ── volume delta proxies: CMF, up/down volume, flow divergence ───────────────

import volume_delta


def _vd_frame(c, h=None, l=None, v=None):
    c = np.asarray(c, dtype=float)
    h = np.asarray(h, dtype=float) if h is not None else c * 1.01
    l = np.asarray(l, dtype=float) if l is not None else c * 0.99
    v = np.asarray(v, dtype=float) if v is not None else np.full(len(c), 1e6)
    idx = pd.date_range("2025-01-01", periods=len(c), freq="B")
    return pd.DataFrame({"Close": c, "High": h, "Low": l, "Open": c, "Volume": v}, index=idx)


def test_volume_delta_accumulation_state():
    """Closes pinned at bar highs on rising up-day volume = flow-confirmed
    accumulation (the daily-bar positive-delta signature)."""
    n = 60
    c = np.linspace(10, 11.5, n) + np.tile([0.0, -0.03], n // 2)  # up-drift, tiny dips
    h = c + 0.01          # close basically AT the high → CLV ≈ +1
    l = c - 0.30
    v = np.where(np.concatenate(([1], np.diff(c))) > 0, 2e6, 8e5)  # up days 2.5x volume
    out = volume_delta.compute(_vd_frame(c, h, l, v))
    assert out["available"] and out["state"] == "ACCUMULATION"
    assert out["cmf20"] > 0.5 and out["updown_ratio"] > 1.3


def test_volume_delta_bearish_divergence_at_highs():
    """Price pushes to a marginal higher high while signed volume flow fades —
    the book's delta divergence / effort-without-result-at-the-highs."""
    up = np.linspace(10, 14, 30)          # strong leg on close-at-high bars
    grind = np.linspace(14, 14.4, 15)     # marginal new highs...
    c = np.concatenate([up, grind])
    h = np.concatenate([up + 0.02, grind + 0.40])   # ...with closes near bar LOWS
    l = np.concatenate([up - 0.40, grind - 0.02])
    v = np.concatenate([np.full(30, 2e6), np.full(15, 2.5e6)])  # heavy volume, no result
    out = volume_delta.compute(_vd_frame(c, h, l, v))
    assert out["available"]
    assert out["divergence"] == "bearish"


def test_session_pseudo_delta_sign():
    closes = np.array([10.0, 10.1, 10.2])
    idx = pd.date_range("2026-07-02 09:30", periods=3, freq="5min")
    bullish = pd.DataFrame({"Close": closes, "High": closes, "Low": closes - 0.2,
                            "Open": closes - 0.1, "Volume": [1e5] * 3}, index=idx)
    bearish = pd.DataFrame({"Close": closes, "High": closes + 0.2, "Low": closes,
                            "Open": closes + 0.1, "Volume": [1e5] * 3}, index=idx)
    assert volume_delta.session_pseudo_delta(bullish) > 0    # closes at highs
    assert volume_delta.session_pseudo_delta(bearish) < 0    # closes at lows
    assert volume_delta.session_pseudo_delta(None) is None


def test_conviction_bearish_flow_divergence_demotes_a():
    stock = {
        "composite": 64, "calibrated_p_win": 0.42, "quote": {"market_cap": 6e8},
        "breakdown": {"fundamentals": {"raw": 82}, "insider": {"raw": 70}, "catalyst": {"raw": 75}},
        "tilt": {"factor": 1.12},
        "vol_delta": {"available": True, "state": "NEUTRAL", "cmf20": -0.02,
                      "updown_ratio": 1.0, "divergence": "bearish"},
        "smad": {"available": True, "state": "DEMAND RETEST", "smad_score": 78, "demand_zone": [4.0, 4.3]},
        "coiled": {"state": "BASING"},
        "edge": {"above_20ma": True, "flow": {"state": "HEALTHY"}, "bearing": {"state": "CLEAN UP"}},
        "book": {"available": True, "phase": {"state": "ACCUMULATION"}, "rbs": {}, "reversal": {},
                 "profile": {"position": "inside"},
                 "plan": {"entry": 4.2, "stop": 3.9, "target": 4.9, "rr": 2.3, "risk_pct": 7.1}},
    }
    v = conviction.assess(stock, _RISK_ON)
    assert v["grade"] != "A"
    assert any("flow divergence" in c for c in v["cautions"])


# ── intraday watcher: trigger rules ──────────────────────────────────────────

import intraday_watch
from zoneinfo import ZoneInfo as _ZI


def _fake_5m(closes, vols):
    idx = pd.date_range("2026-07-02 09:30", periods=len(closes), freq="5min")
    closes = np.array(closes, dtype=float)
    # bars close at their highs → CLV +1 → positive session pseudo-delta
    return pd.DataFrame({"Close": closes, "Volume": vols, "Open": closes * 0.995,
                         "High": closes, "Low": closes * 0.99}, index=idx)


def test_intraday_trigger_needs_completed_close_and_rvol(monkeypatch):
    monkeypatch.setattr(db, "alert_already_sent", lambda *a, **k: False)
    intraday_watch.set_hotlist([{"ticker": "T", "pivot_price": 10.0,
                                 "avg_vol20": 390_000, "coiled_score": 80}])
    noon = _dtm(2026, 7, 2, 12, 0, tzinfo=_ZI("America/New_York"))
    # completed bar closes through pivot on heavy volume → fires
    bars = {"T": _fake_5m([9.9, 10.05, 10.5], [400_000, 400_000, 100])}
    fired = intraday_watch.check_triggers(bars_by_ticker=bars, now=noon)
    assert len(fired) == 1 and fired[0]["ticker"] == "T"
    # only the IN-PROGRESS bar is through the pivot → no fire (wick discipline)
    bars2 = {"T": _fake_5m([9.9, 9.95, 10.5], [400_000, 400_000, 100])}
    assert intraday_watch.check_triggers(bars_by_ticker=bars2, now=noon) == []
    # thin volume → no fire
    bars3 = {"T": _fake_5m([9.9, 10.05, 10.5], [1_000, 1_000, 100])}
    assert intraday_watch.check_triggers(bars_by_ticker=bars3, now=noon) == []
    # before 10:00 ET the prorated-volume math structurally misfires → hold fire
    early = _dtm(2026, 7, 2, 9, 45, tzinfo=_ZI("America/New_York"))
    assert intraday_watch.check_triggers(bars_by_ticker=bars, now=early) == []


# ── paper ledger: sizing, fills, exit decisions ──────────────────────────────

import paper_ledger


def test_ledger_sizing_binding_constraints():
    # risk-bound: $75 risk / $0.50 per-share risk = 150 shares (pos cap 1000/10=100 binds!)
    assert paper_ledger.size_shares(fill=10.0, stop=9.5, adv_dollars=10_000_000) == 100
    # risk binds when the position cap is loose: $75 / $2 = 37 shares
    assert paper_ledger.size_shares(fill=10.0, stop=8.0, adv_dollars=10_000_000) == 37
    # ADV binds for an illiquid name: 1% of $20k ADV = $200 / $10 = 20 shares
    assert paper_ledger.size_shares(fill=10.0, stop=8.0, adv_dollars=20_000) == 20
    # invalid risk → 0
    assert paper_ledger.size_shares(fill=10.0, stop=10.5, adv_dollars=1e6) == 0


def test_ledger_fill_tolerance():
    assert paper_ledger.can_fill(quote=10.1, plan_entry=10.0, stop=9.0) is True
    assert paper_ledger.can_fill(quote=10.3, plan_entry=10.0, stop=9.0) is False  # >2% drift
    assert paper_ledger.can_fill(quote=8.9, plan_entry=10.0, stop=9.0) is False   # under stop


def test_ledger_manage_stop_first_at_quote():
    """A gap through the stop exits at the QUOTE (real slippage), the target
    exits AT the target (limit semantics), otherwise hold."""
    tr = {"fill_price": 10.0, "stop": 9.0, "target": 12.0, "opened_at": "2026-07-01T10:00:00"}
    d = paper_ledger.manage_decision(tr, quote=8.5, now_iso="2026-07-02T10:00:00")
    assert d["exit_reason"] == "stop" and d["exit_price"] == 8.5
    assert d["r_realised"] == pytest.approx(-1.5)
    d2 = paper_ledger.manage_decision(tr, quote=13.0, now_iso="2026-07-02T10:00:00")
    assert d2["exit_reason"] == "target" and d2["exit_price"] == 12.0  # no gap-up windfall
    assert paper_ledger.manage_decision(tr, quote=10.5, now_iso="2026-07-02T10:00:00") is None


def test_ledger_time_exit_after_20_trading_days():
    tr = {"fill_price": 10.0, "stop": 9.0, "target": 12.0, "opened_at": "2026-06-01T10:00:00"}
    d = paper_ledger.manage_decision(tr, quote=10.2, now_iso="2026-07-02T10:00:00")
    assert d is not None and d["exit_reason"] == "time"
    assert d["exit_price"] == pytest.approx(10.2)


# ── conviction: the synthesized verdict ──────────────────────────────────────

import conviction

_RISK_ON = {"available": True, "mood": {"label": "RISK-ON"}}


def test_conviction_grades_a_on_full_confluence():
    """Clean technical setup + fundamentals + context + a plan = grade A with R:R."""
    stock = {
        "composite": 64, "calibrated_p_win": 0.42,
        "quote": {"market_cap": 6e8},
        "breakdown": {"fundamentals": {"raw": 82}, "catalyst": {"raw": 70}, "insider": {"raw": 58}},
        "tilt": {"factor": 1.12},
        "short_squeeze": {"score": 66},
        "smad": {"available": True, "state": "DEMAND RETEST", "smad_score": 78, "demand_zone": [4.0, 4.3]},
        "coiled": {"state": "BASING"},
        "edge": {"above_20ma": True, "flow": {"state": "HEALTHY"}, "bearing": {"state": "CLEAN UP"}},
        "book": {"available": True, "phase": {"state": "ACCUMULATION"}, "rbs": {},
                 "reversal": {}, "profile": {"position": "inside"},
                 "plan": {"entry": 4.2, "stop": 3.9, "target": 4.9, "rr": 2.3, "risk_pct": 7.1}},
    }
    v = conviction.assess(stock, _RISK_ON)
    assert v["grade"] == "A"
    assert v["setup"] == "Demand-zone retest"
    assert v["confluence"]["technical"] >= 3 and v["confluence"]["fundamental"] >= 2
    assert "Buy $4.2" in v["action"] and "2.3R" in v["action"]


def test_conviction_demotes_negative_expectancy_setup():
    """A setup the historical backtest says loses money gets demoted (loop closed)."""
    stock = {
        "composite": 64, "calibrated_p_win": 0.42, "quote": {"market_cap": 6e8},
        "breakdown": {"fundamentals": {"raw": 82}, "catalyst": {"raw": 70}, "insider": {"raw": 58}},
        "tilt": {"factor": 1.12}, "short_squeeze": {"score": 66},
        "smad": {"available": True, "state": "BOS IMPULSE", "smad_score": 78, "demand_zone": [4.0, 4.3]},
        "coiled": {"state": "BASING"},
        "edge": {"above_20ma": True, "flow": {"state": "HEALTHY"}, "bearing": {"state": "CLEAN UP"}},
        "book": {"available": True, "phase": {"state": "MARKUP"}, "rbs": {}, "reversal": {},
                 "profile": {"position": "inside"},
                 "plan": {"entry": 4.2, "stop": 3.9, "target": 4.9, "rr": 2.3, "risk_pct": 7.1}},
    }
    good = conviction.assess(stock, _RISK_ON, setup_stats={"Breakout (structure)": {"avg_r": 0.4, "win_rate": 55, "n": 80}})
    bad = conviction.assess(stock, _RISK_ON, setup_stats={"Breakout (structure)": {"avg_r": -0.3, "win_rate": 30, "n": 80}})
    assert good["grade"] == "A"
    assert bad["grade"] != "A"          # demoted by the measured negative edge
    assert any("weak measured edge" in c for c in bad["cautions"])


def test_conviction_b_without_fundamentals():
    """A technical setup with no fundamental backing can't grade A — the books' rule."""
    stock = {
        "composite": 55, "calibrated_p_win": 0.33,
        "quote": {"market_cap": 6e8}, "breakdown": {"fundamentals": {"raw": 40}},
        "tilt": {"factor": 1.10},
        "smad": {"available": True, "state": "DEMAND RETEST", "smad_score": 70, "demand_zone": [4.0, 4.3]},
        "coiled": {"state": "BASING"},
        "edge": {"above_20ma": True, "flow": {"state": "HEALTHY"}, "bearing": {"state": "CLEAN UP"}},
        "book": {"available": True, "phase": {"state": "MARKUP"}, "rbs": {}, "reversal": {},
                 "profile": {"position": "above"},
                 "plan": {"entry": 4.2, "stop": 3.9, "target": 4.9, "rr": 2.3, "risk_pct": 7.1}},
    }
    v = conviction.assess(stock, _RISK_ON)
    assert v["grade"] in ("B", "C")  # never A without fundamentals (has a plan → not WATCH)


def test_conviction_no_plan_is_watch():
    """A real setup with no actionable plan is WATCH, not a tradeable grade."""
    stock = {
        "composite": 60, "quote": {"market_cap": 6e8},
        "breakdown": {"fundamentals": {"raw": 75}, "catalyst": {"raw": 65}},
        "tilt": {"factor": 1.1},
        "smad": {"available": True, "state": "ACCUMULATION"},
        "coiled": {"state": "BASING"},
        "edge": {"above_20ma": True, "flow": {"state": "HEALTHY"}, "bearing": {"state": "CLEAN UP"}},
        "book": {"available": True, "phase": {"state": "ACCUMULATION"}, "rbs": {}, "reversal": {},
                 "profile": {"position": "inside"}, "plan": None, "context": {"ret_20d": 3}},
    }
    assert conviction.assess(stock, _RISK_ON)["grade"] == "WATCH"


def test_conviction_a_requires_live_driver_and_ignores_sentiment():
    """v2 A-gate: sentiment (measured IC -0.19) no longer counts toward n_fund,
    and grade A needs a live catalyst>=60 or squeeze>=60 driver."""
    base = {
        "composite": 64, "calibrated_p_win": 0.42, "quote": {"market_cap": 6e8},
        "tilt": {"factor": 1.12},
        "smad": {"available": True, "state": "DEMAND RETEST", "smad_score": 78, "demand_zone": [4.0, 4.3]},
        "coiled": {"state": "BASING"},
        "edge": {"above_20ma": True, "flow": {"state": "HEALTHY"}, "bearing": {"state": "CLEAN UP"}},
        "book": {"available": True, "phase": {"state": "ACCUMULATION"}, "rbs": {}, "reversal": {},
                 "profile": {"position": "inside"},
                 "plan": {"entry": 4.2, "stop": 3.9, "target": 4.9, "rr": 2.3, "risk_pct": 7.1}},
    }
    # fundamentals + insider pass n_fund>=2, but NO catalyst/squeeze driver → not A
    no_driver = {**base, "breakdown": {"fundamentals": {"raw": 82}, "insider": {"raw": 70},
                                       "catalyst": {"raw": 40}, "sentiment": {"raw": 90}}}
    v1 = conviction.assess(no_driver, _RISK_ON)
    assert v1["grade"] != "A"
    # same setup WITH a live catalyst → A allowed
    with_driver = {**base, "breakdown": {"fundamentals": {"raw": 82}, "insider": {"raw": 70},
                                         "catalyst": {"raw": 75}, "sentiment": {"raw": 10}}}
    v2 = conviction.assess(with_driver, _RISK_ON)
    assert v2["grade"] == "A"
    # sentiment 90 must not be counted in the fundamental confluence group
    sent_fac = next(f for f in v1["confluence"]["factors"] if f["label"] == "Positive sentiment")
    assert sent_fac["group"] == "info"


def test_conviction_earnings_proximity_caution():
    """4-10d earnings window: caution always; A demotes to B only when the
    reward doesn't justify holding through the event (rr < 2.5)."""
    stock = {
        "composite": 64, "calibrated_p_win": 0.42, "quote": {"market_cap": 6e8},
        "breakdown": {"fundamentals": {"raw": 82}, "insider": {"raw": 70},
                      "catalyst": {"raw": 75, "metrics": {"earnings_days": 6}}},
        "tilt": {"factor": 1.12},
        "smad": {"available": True, "state": "DEMAND RETEST", "smad_score": 78, "demand_zone": [4.0, 4.3]},
        "coiled": {"state": "BASING"},
        "edge": {"above_20ma": True, "flow": {"state": "HEALTHY"}, "bearing": {"state": "CLEAN UP"}},
        "book": {"available": True, "phase": {"state": "ACCUMULATION"}, "rbs": {}, "reversal": {},
                 "profile": {"position": "inside"},
                 "plan": {"entry": 4.2, "stop": 3.9, "target": 4.9, "rr": 2.3, "risk_pct": 7.1}},
    }
    v = conviction.assess(stock, _RISK_ON)
    assert any("earnings in 6d" in c for c in v["cautions"])
    assert v["grade"] != "A"    # rr 2.3 < 2.5 → an A here demotes to B


def test_conviction_no_bottoming_label_on_active_markup():
    """IOVA-class false positive: a double-bottom neckline broke weeks ago and the
    stock already rallied +21%/60d in MARKUP — that's not a 'pre-confirm bottom'."""
    stock = {
        "composite": 55, "quote": {"market_cap": 1.8e9},
        "breakdown": {"fundamentals": {"raw": 60}},
        "smad": {"available": True, "state": "NONE"},
        "coiled": {"state": "NO SETUP"},
        "edge": {"above_20ma": True, "flow": {"state": "HEALTHY"}, "bearing": {"state": "CLEAN UP"}},
        "book": {"available": True, "phase": {"state": "MARKUP"}, "rbs": {}, "reversal": {},
                 "profile": {"position": "above"},
                 "double_bottom": {"active": True, "confirmed": False, "neckline": 4.0},
                 "plan": None, "context": {"ret_20d": 5, "ret_60d": 21, "pct_off_high": -26}},
    }
    v = conviction.assess(stock, _RISK_ON)
    assert v["setup"] != "Bottoming (pre-confirm)"


def test_conviction_phase_smad_conflict_caps_at_b():
    """SMA-class case: book.phase says MARKUP, smad says ACCUMULATION for the same
    ticker — an internal contradiction, not a clean signal; cap conviction."""
    stock = {
        "composite": 64, "quote": {"market_cap": 1.8e9},
        "breakdown": {"fundamentals": {"raw": 82}, "catalyst": {"raw": 70}, "insider": {"raw": 58}},
        "tilt": {"factor": 1.12},
        "smad": {"available": True, "state": "ACCUMULATION"},
        "coiled": {"state": "BASING"},
        "edge": {"above_20ma": True, "flow": {"state": "HEALTHY"}, "bearing": {"state": "CLEAN UP"}},
        "book": {"available": True, "phase": {"state": "MARKUP"}, "rbs": {"active": True, "level": 31.82},
                 "reversal": {}, "profile": {"position": "above"},
                 "plan": {"entry": 32.5, "stop": 31.7, "target": 34.1, "rr": 2.1, "risk_pct": 2.5}},
    }
    v = conviction.assess(stock, _RISK_ON)
    assert v["grade"] != "A"
    assert any("conflict" in c for c in v["cautions"])


def test_conviction_avoids_bull_trap_and_extended():
    trap = {"composite": 60, "smad": {"available": True, "state": "BULL TRAP"}, "coiled": {}, "edge": {}}
    assert conviction.assess(trap, _RISK_ON)["grade"] == "AVOID"
    ext = {"composite": 70, "smad": {"available": True, "state": "BOS IMPULSE"},
           "coiled": {"state": "EXTENDED", "ret_3m_pct": 90}, "edge": {}}
    assert conviction.assess(ext, _RISK_ON)["grade"] == "AVOID"


def test_conviction_no_setup_is_dash():
    plain = {"composite": 38, "smad": {"available": True, "state": "NONE"}, "coiled": {"state": "NO SETUP"}, "edge": {}}
    assert conviction.assess(plain, _RISK_ON)["grade"] == "—"


# ── alerts: multi-channel dispatch (Pushover + Telegram) ─────────────────────

import alerts


def test_alerts_dispatch_to_pushover(monkeypatch):
    monkeypatch.setattr(alerts, "PUSHOVER_TOKEN", "tok")
    monkeypatch.setattr(alerts, "PUSHOVER_USER", "usr")
    monkeypatch.setattr(alerts, "BOT_TOKEN", "")
    monkeypatch.setattr(alerts, "CHAT_ID", "")
    calls = {}

    class _R:
        status_code = 200

    def _post(url, **kw):
        calls["url"] = url
        calls["data"] = kw.get("data")
        return _R()

    monkeypatch.setattr(alerts.requests, "post", _post)
    assert alerts.is_configured() is True
    ok = alerts._send("🚀 *BREAKOUT*\n\n*$ABCD* up *11%*")
    assert ok is True
    assert calls["url"] == "https://api.pushover.net/1/messages.json"
    assert calls["data"]["title"] == "🚀 BREAKOUT"           # markdown stripped
    assert "<b>$ABCD</b>" in calls["data"]["message"]        # *bold* -> <b>
    assert calls["data"]["html"] == 1


def test_econ_calendar_upcoming_and_today():
    import econ_calendar
    from datetime import date
    # 2026-07-14 is a CPI day (verified vs BLS); 2026-07-29 an FOMC decision
    ev = econ_calendar.upcoming(days=30, today=date(2026, 7, 3))
    names = {(e["date"], e["name"]) for e in ev}
    assert ("2026-07-14", "CPI") in names
    assert ("2026-07-29", "FOMC decision") in names
    assert ("2026-07-03", "Jobs report (NFP)") in names   # first Friday of July
    today = econ_calendar.today_events(today=date(2026, 7, 14))
    assert any(e["name"] == "CPI" and e["days_away"] == 0 for e in today)
    assert econ_calendar.today_events(today=date(2026, 7, 15)) == []


def test_preopen_brief_flags_premarket_gaps():
    ranked = [{"ticker": "GKOS", "setup": {"grade": "A", "setup": "Breakout",
                                           "plan": {"entry": 148.3, "stop": 133.2, "target": 178.6, "rr": 2.0},
                                           "cautions": []}}]
    body = alerts.format_preopen_brief(ranked, "RISK-ON", day="Jul 06",
                                       gaps={"GKOS": 12.4})
    assert "gapping +12.4% pre-market" in body and "plan is stale" in body
    # no gap dict -> no annotation, no crash
    body2 = alerts.format_preopen_brief(ranked, "RISK-ON", day="Jul 06")
    assert "gapping" not in body2


def test_preopen_brief_includes_macro_and_events():
    ranked = [{"ticker": "GKOS", "setup": {"grade": "A", "setup": "Breakout",
                                           "plan": {"entry": 148.3, "stop": 133.2, "target": 178.6, "rr": 2.0},
                                           "cautions": []}}]
    body = alerts.format_preopen_brief(
        ranked, "RISK-ON", day="Jul 14",
        macro_line="ES▲ NQ▲ Gold▼ Oil· EUR· GBP· JPY▼ BTC▲",
        events=[{"date": "2026-07-14", "name": "CPI", "time_et": "08:30", "days_away": 0}])
    assert "🌍 ES▲" in body
    assert "CPI today 08:30 ET" in body and "size down" in body


def test_preopen_brief_formatting():
    ranked = [
        {"ticker": "GKOS", "setup": {"grade": "A", "setup": "Spring reclaim",
                                     "plan": {"entry": 25.1, "stop": 24.2, "target": 27.3, "rr": 2.4},
                                     "cautions": ["earnings in 6d"]}},
        {"ticker": "ATAI", "setup": {"grade": "B", "setup": "Coiled spring",
                                     "plan": {"entry": 3.1, "stop": 2.9, "target": 3.6, "rr": 2.5},
                                     "cautions": []}},
        {"ticker": "RXRX", "setup": {"grade": "WATCH", "setup": "Accumulation base", "score": 50}},
        {"ticker": "BAD", "setup": {"grade": "AVOID"}},
    ]
    body = alerts.format_preopen_brief(ranked, "RISK-ON",
                                       open_trades=[{"ticker": "SOFI", "mfe_r": 0.4}],
                                       day="Jul 03")
    assert "PRE-OPEN BRIEF" in body and "RISK-ON" in body
    assert "$GKOS" in body and "buy 25.1" in body and "2.4R" in body
    assert "⚠ earnings in 6d" in body
    assert "$RXRX" in body            # watch line
    assert "$BAD" not in body         # AVOID never makes the brief
    assert "$SOFI +0.4R" in body      # ledger book
    assert len(body) < 1024           # Pushover message cap
    # nothing actionable → None (caller sends the honest "nothing today" note)
    assert alerts.format_preopen_brief([{"ticker": "X", "setup": {"grade": "AVOID"}}], "NEUTRAL") is None


def test_alerts_not_configured_when_no_channel(monkeypatch):
    monkeypatch.setattr(alerts, "PUSHOVER_TOKEN", "")
    monkeypatch.setattr(alerts, "PUSHOVER_USER", "")
    monkeypatch.setattr(alerts, "BOT_TOKEN", "")
    monkeypatch.setattr(alerts, "CHAT_ID", "")
    assert alerts.is_configured() is False
    assert alerts._send("x") is False


# ── smad: smart-money accumulation / demand-zone states ──────────────────────

import smad


def _ohlc(o, h, l, c, v):
    idx = pd.date_range("2024-01-01", periods=len(c), freq="D")
    return pd.DataFrame({"Open": o, "High": h, "Low": l, "Close": c, "Volume": v}, index=idx)


def test_smad_spring_on_sweep_and_reclaim():
    rng = np.random.default_rng(1)
    n = 125
    c = np.concatenate([np.full(124, 20.0) + rng.normal(0, 0.12, 124), [19.9]])
    o = c.copy(); h = c + 0.08; l = c - 0.08; v = np.full(n, 1e6)
    o[-1] = 20.0; h[-1] = 20.05; l[-1] = 18.5; c[-1] = 19.9; v[-1] = 1.9e6  # wick below base, reclaimed
    assert smad.compute("X", _ohlc(o, h, l, c, v))["state"] == "SPRING"


def test_smad_bull_trap_on_effort_without_result():
    rng = np.random.default_rng(1)
    n = 125
    c = np.concatenate([np.full(124, 20.0) + rng.normal(0, 0.12, 124), [20.15]])
    o = c.copy(); h = c + 0.08; l = c - 0.08; v = np.full(n, 1e6)
    o[-1] = 20.2; h[-1] = 22.0; l[-1] = 20.0; c[-1] = 20.15; v[-1] = 2.6e6  # spike, tiny body, rejected
    out = smad.compute("X", _ohlc(o, h, l, c, v))
    assert out["state"] == "BULL TRAP" and out["trap"] == "hard"


def test_smad_bos_impulse_clears_swing_high_on_volume():
    rng = np.random.default_rng(2)
    base = np.full(120, 20.0) + rng.normal(0, 0.15, 120)
    base[60] = 21.5  # prior swing high
    c = np.concatenate([base, [20.2, 22.2]])
    n = len(c)
    o = c.copy(); h = c + 0.1; l = c - 0.1; v = np.full(n, 1e6)
    o[-1] = 20.3; h[-1] = 22.3; l[-1] = 20.25; c[-1] = 22.2; v[-1] = 2.2e6  # wide top-close breakout
    assert smad.compute("X", _ohlc(o, h, l, c, v))["state"] == "BOS IMPULSE"


def test_smad_unavailable_on_short_history():
    assert smad.compute("X", _ohlc(*([np.full(60, 10.0)] * 4 + [np.full(60, 1e6)])))["available"] is False


def test_pre_breakout_detects_breakout_on_volume():
    # ~120d tight base near 10, then a fresh pop above the pivot on heavy volume
    n = 124
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    base = list(10 + np.random.default_rng(2).normal(0, 0.08, n - 3))  # tight base
    closes = np.array(base + [10.6, 11.0, 11.4])  # clears base on last 3 days
    highs = closes * 1.01
    lows = closes * 0.99
    vol = np.full(n, 1_000_000.0)
    vol[-3:] = 3_000_000.0  # volume surge on the breakout
    f = pd.DataFrame({"Open": closes, "High": highs, "Low": lows, "Close": closes, "Volume": vol}, index=idx)
    out = pre_breakout.compute("X", f)
    assert out["available"] is True
    assert out["state"] == "BREAKING"
