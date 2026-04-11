"""Fundamentals scoring: revenue growth, margins, cash, debt, dilution."""

import yfinance as yf
import numpy as np
import config


def _safe_get(info: dict, key: str, default=None):
    v = info.get(key)
    return default if v is None else v


def score(ticker: str) -> dict:
    """Return a fundamentals score (0-100) and component details."""
    try:
        stock = yf.Ticker(ticker)
        info = stock.info or {}
        financials = stock.quarterly_financials
        bs = stock.quarterly_balance_sheet
    except Exception:
        return {"score": 0, "details": "Failed to fetch data", "components": {}}

    components = {}
    scores = []

    # --- Revenue growth (YoY from quarterly data) ---
    rev_score = 0
    try:
        if financials is not None and not financials.empty:
            rev_row = None
            for label in ["Total Revenue", "Revenue"]:
                if label in financials.index:
                    rev_row = financials.loc[label]
                    break
            if rev_row is not None and len(rev_row) >= 4:
                recent = rev_row.iloc[0]
                year_ago = rev_row.iloc[3]  # 4 quarters back
                if year_ago and year_ago > 0 and recent and recent > 0:
                    growth = (recent - year_ago) / abs(year_ago)
                    rev_score = min(100, max(0, (growth / config.REVENUE_GROWTH_STRONG) * 100))
                    components["revenue_growth"] = f"{growth:.1%}"
    except Exception:
        pass
    scores.append(("revenue_growth", rev_score, 0.30))

    # --- Revenue acceleration (QoQ growth accelerating) ---
    accel_score = 0
    try:
        if financials is not None and not financials.empty:
            rev_row = None
            for label in ["Total Revenue", "Revenue"]:
                if label in financials.index:
                    rev_row = financials.loc[label]
                    break
            if rev_row is not None and len(rev_row) >= 3:
                vals = [v for v in rev_row.iloc[:3] if v and v > 0]
                if len(vals) == 3:
                    g1 = (vals[0] - vals[1]) / abs(vals[1])
                    g2 = (vals[1] - vals[2]) / abs(vals[2])
                    if g1 > g2:
                        accel_score = min(100, (g1 - g2) * 500)
                    components["revenue_accel"] = f"latest QoQ {g1:.1%} vs prior {g2:.1%}"
    except Exception:
        pass
    scores.append(("revenue_accel", accel_score, 0.15))

    # --- Gross margin ---
    margin_score = 0
    gm = _safe_get(info, "grossMargins")
    if gm is not None and gm > 0:
        margin_score = min(100, (gm / config.GROSS_MARGIN_GOOD) * 100)
        components["gross_margin"] = f"{gm:.1%}"
    scores.append(("gross_margin", margin_score, 0.15))

    # --- Cash runway ---
    cash_score = 0
    try:
        total_cash = _safe_get(info, "totalCash", 0)
        op_cf = _safe_get(info, "operatingCashflow", 0)
        if total_cash and total_cash > 0:
            if op_cf and op_cf > 0:
                # Cash-flow positive = great
                cash_score = 100
                components["cash"] = f"CF positive, ${total_cash/1e6:.0f}M cash"
            elif op_cf and op_cf < 0:
                burn = abs(op_cf) / 4  # quarterly burn
                runway_q = total_cash / burn if burn > 0 else 99
                cash_score = min(100, (runway_q / config.CASH_RUNWAY_SAFE_QUARTERS) * 100)
                components["cash"] = f"${total_cash/1e6:.0f}M cash, ~{runway_q:.0f}Q runway"
            else:
                cash_score = 50
                components["cash"] = f"${total_cash/1e6:.0f}M cash"
    except Exception:
        pass
    scores.append(("cash", cash_score, 0.15))

    # --- Debt burden ---
    debt_score = 50  # neutral default
    try:
        total_debt = _safe_get(info, "totalDebt", 0)
        market_cap = _safe_get(info, "marketCap", 0)
        if market_cap and market_cap > 0:
            if not total_debt or total_debt == 0:
                debt_score = 100
                components["debt"] = "No debt"
            else:
                ratio = total_debt / market_cap
                debt_score = max(0, 100 - ratio * 200)
                components["debt"] = f"Debt/MCap {ratio:.1%}"
    except Exception:
        pass
    scores.append(("debt", debt_score, 0.10))

    # --- Dilution (shares outstanding growth) ---
    dilution_score = 50
    try:
        shares = _safe_get(info, "sharesOutstanding")
        if bs is not None and not bs.empty:
            for label in ["Share Issued", "Ordinary Shares Number", "Common Stock"]:
                if label in bs.index:
                    share_row = bs.loc[label].dropna()
                    if len(share_row) >= 2 and shares:
                        oldest = share_row.iloc[-1]
                        if oldest and oldest > 0:
                            dilution = (shares - oldest) / oldest
                            if dilution <= 0:
                                dilution_score = 100  # buybacks
                            elif dilution < 0.05:
                                dilution_score = 80
                            elif dilution < 0.15:
                                dilution_score = 50
                            elif dilution < 0.30:
                                dilution_score = 25
                            else:
                                dilution_score = 0
                            components["dilution"] = f"{dilution:.1%} share growth"
                    break
    except Exception:
        pass
    scores.append(("dilution", dilution_score, 0.15))

    # --- Weighted total ---
    total = sum(s * w for _, s, w in scores)

    return {
        "score": round(total, 1),
        "components": components,
        "details": ", ".join(f"{k}: {v}" for k, v in components.items()),
    }
