"""Fundamentals scoring: revenue growth, margins, cash, debt, dilution."""

import config
import fmp


def _yf_score(ticker: str) -> dict:
    """Fallback to yfinance for local development."""
    try:
        import yfinance as yf
        stock = yf.Ticker(ticker)
        info = stock.info or {}
        financials = stock.quarterly_financials
        bs = stock.quarterly_balance_sheet
    except Exception:
        return {"score": 0, "details": "Failed to fetch data", "components": {}}

    components = {}
    scores = []

    # Revenue growth
    rev_score = 0
    try:
        if financials is not None and not financials.empty:
            for label in ["Total Revenue", "Revenue"]:
                if label in financials.index:
                    rev_row = financials.loc[label]
                    if len(rev_row) >= 4:
                        recent, year_ago = rev_row.iloc[0], rev_row.iloc[3]
                        if year_ago and year_ago > 0 and recent and recent > 0:
                            growth = (recent - year_ago) / abs(year_ago)
                            rev_score = min(100, max(0, (growth / config.REVENUE_GROWTH_STRONG) * 100))
                            components["revenue_growth"] = f"{growth:.1%}"
                    break
    except Exception:
        pass
    scores.append(rev_score * 0.35)

    # Gross margin
    margin_score = 0
    gm = info.get("grossMargins")
    if gm and gm > 0:
        margin_score = min(100, (gm / config.GROSS_MARGIN_GOOD) * 100)
        components["gross_margin"] = f"{gm:.1%}"
    scores.append(margin_score * 0.20)

    # Cash
    cash_score = 0
    total_cash = info.get("totalCash", 0) or 0
    op_cf = info.get("operatingCashflow", 0) or 0
    if total_cash > 0:
        if op_cf > 0:
            cash_score = 100
            components["cash"] = f"CF positive, ${total_cash/1e6:.0f}M"
        elif op_cf < 0:
            burn = abs(op_cf) / 4
            runway_q = total_cash / burn if burn > 0 else 99
            cash_score = min(100, (runway_q / config.CASH_RUNWAY_SAFE_QUARTERS) * 100)
            components["cash"] = f"${total_cash/1e6:.0f}M, ~{runway_q:.0f}Q runway"
    scores.append(cash_score * 0.20)

    # Debt
    debt_score = 50
    total_debt = info.get("totalDebt", 0) or 0
    mcap = info.get("marketCap", 0) or 0
    if mcap > 0:
        if not total_debt:
            debt_score = 100
            components["debt"] = "No debt"
        else:
            ratio = total_debt / mcap
            debt_score = max(0, 100 - ratio * 200)
            components["debt"] = f"Debt/MCap {ratio:.1%}"
    scores.append(debt_score * 0.10)

    # Dilution
    dilution_score = 50
    shares = info.get("sharesOutstanding")
    if bs is not None and not bs.empty and shares:
        for label in ["Share Issued", "Ordinary Shares Number"]:
            if label in bs.index:
                share_row = bs.loc[label].dropna()
                if len(share_row) >= 2:
                    oldest = share_row.iloc[-1]
                    if oldest and oldest > 0:
                        dilution = (shares - oldest) / oldest
                        if dilution <= 0: dilution_score = 100
                        elif dilution < 0.05: dilution_score = 80
                        elif dilution < 0.15: dilution_score = 50
                        elif dilution < 0.30: dilution_score = 25
                        else: dilution_score = 0
                        components["dilution"] = f"{dilution:.1%} share growth"
                break
    scores.append(dilution_score * 0.15)

    total = sum(scores)
    # Hand the already-fetched statements back to the caller. factors.py needs
    # these same three objects for asset-growth/ROA/accruals/size; re-fetching
    # them there would mean ~180 extra Yahoo calls per scan and would re-trigger
    # the rate-limit starvation that once emptied a whole pre-open brief.
    return {"score": round(total, 1), "components": components,
            "raw": {"info": info, "financials": financials, "balance_sheet": bs},
            "details": ", ".join(f"{k}: {v}" for k, v in components.items())}


def _fmp_score(ticker: str) -> dict:
    """Score using Financial Modeling Prep API."""
    components = {}
    scores = []

    profile = fmp.get_profile(ticker)
    income = fmp.get_income_statement(ticker, limit=5)
    balance = fmp.get_balance_sheet(ticker, limit=4)
    quote = fmp.get_quote(ticker)

    # Revenue growth YoY
    rev_score = 0
    if len(income) >= 4:
        recent_rev = income[0].get("revenue", 0)
        year_ago_rev = income[3].get("revenue", 0)  # 4 quarters back
        if year_ago_rev and year_ago_rev > 0 and recent_rev:
            growth = (recent_rev - year_ago_rev) / abs(year_ago_rev)
            rev_score = min(100, max(0, (growth / config.REVENUE_GROWTH_STRONG) * 100))
            components["revenue_growth"] = f"{growth:.1%}"

    # Revenue acceleration
    if len(income) >= 3:
        r0 = income[0].get("revenue", 0)
        r1 = income[1].get("revenue", 0)
        r2 = income[2].get("revenue", 0)
        if r1 and r1 > 0 and r2 and r2 > 0:
            g1 = (r0 - r1) / abs(r1)
            g2 = (r1 - r2) / abs(r2)
            if g1 > g2:
                rev_score = min(100, rev_score + 15)
                components["revenue_accel"] = f"QoQ {g1:.1%} vs {g2:.1%}"
    scores.append(rev_score * 0.35)

    # Gross margin
    margin_score = 0
    if income:
        gp = income[0].get("grossProfit", 0) or 0
        rev = income[0].get("revenue", 0) or 0
        gm = gp / rev if rev > 0 else income[0].get("grossProfitRatio", 0) or 0
    else:
        gm = 0
    if gm and gm > 0:
        margin_score = min(100, (gm / config.GROSS_MARGIN_GOOD) * 100)
        components["gross_margin"] = f"{gm:.1%}"
    scores.append(margin_score * 0.20)

    # Cash position
    cash_score = 0
    if balance:
        total_cash = balance[0].get("cashAndCashEquivalents", 0) or 0
        if total_cash > 0:
            # Check operating cash flow from income
            op_cf = income[0].get("operatingIncome", 0) if income else 0
            if op_cf and op_cf > 0:
                cash_score = 100
                components["cash"] = f"Operating profitable, ${total_cash/1e6:.0f}M cash"
            else:
                net_income = income[0].get("netIncome", 0) if income else 0
                if net_income and net_income < 0:
                    burn = abs(net_income)
                    runway_q = total_cash / burn if burn > 0 else 99
                    cash_score = min(100, (runway_q / config.CASH_RUNWAY_SAFE_QUARTERS) * 100)
                    components["cash"] = f"${total_cash/1e6:.0f}M, ~{runway_q:.0f}Q runway"
                else:
                    cash_score = 60
                    components["cash"] = f"${total_cash/1e6:.0f}M cash"
    scores.append(cash_score * 0.20)

    # Debt
    debt_score = 50
    mcap = quote.get("marketCap", 0) or profile.get("mktCap", 0) or 0
    if balance and mcap > 0:
        total_debt = balance[0].get("totalDebt", 0) or 0
        if not total_debt:
            debt_score = 100
            components["debt"] = "No debt"
        else:
            ratio = total_debt / mcap
            debt_score = max(0, 100 - ratio * 200)
            components["debt"] = f"Debt/MCap {ratio:.1%}"
    scores.append(debt_score * 0.10)

    # Dilution
    dilution_score = 50
    if len(balance) >= 2:
        recent_shares = balance[0].get("commonStock", 0) or balance[0].get("totalStockholdersEquity", 0)
        older_shares = balance[-1].get("commonStock", 0) or balance[-1].get("totalStockholdersEquity", 0)
        shares_out = quote.get("sharesOutstanding", 0)
        if shares_out and older_shares and older_shares > 0:
            # Use shares outstanding vs historical
            pass  # FMP commonStock is sometimes equity not share count
        # Fallback: check profile
        if profile.get("lastDiv", 0):
            components["dividend"] = f"${profile['lastDiv']:.2f} div"

    scores.append(dilution_score * 0.15)

    total = sum(scores)
    return {"score": round(total, 1), "components": components,
            "details": ", ".join(f"{k}: {v}" for k, v in components.items())}


def score(ticker: str) -> dict:
    """Return a fundamentals score (0-100). Uses FMP if configured, else yfinance."""
    if fmp.is_configured():
        return _fmp_score(ticker)
    return _yf_score(ticker)
