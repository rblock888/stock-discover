"""Insider activity and capital structure scoring."""

import fmp
import config
from datetime import datetime, timedelta


def _fmp_score(ticker: str) -> dict:
    """Score using FMP insider trading data."""
    components = {}
    scores = []

    quote = fmp.get_quote(ticker)
    profile = fmp.get_profile(ticker)
    insider_txns = fmp.get_insider_trading(ticker)

    # Insider transactions
    insider_score = 50
    if insider_txns:
        buys = 0
        sells = 0
        cutoff = datetime.now() - timedelta(days=config.INSIDER_LOOKBACK_DAYS)
        for t in insider_txns:
            try:
                txn_date = datetime.strptime(t.get("transactionDate", ""), "%Y-%m-%d")
                if txn_date < cutoff:
                    continue
                txn_type = t.get("transactionType", "").lower()
                shares = abs(t.get("securitiesTransacted", 0) or 0)
                if "purchase" in txn_type or "buy" in txn_type or txn_type == "p-purchase":
                    buys += shares
                elif "sale" in txn_type or "sell" in txn_type or txn_type == "s-sale":
                    sells += shares
            except Exception:
                continue

        if buys > 0 and sells == 0:
            insider_score = 100
            components["insider_txns"] = f"Net buying ({buys:,.0f} shares)"
        elif buys > sells:
            insider_score = 75
            components["insider_txns"] = "More buying than selling"
        elif sells > buys and buys > 0:
            insider_score = 35
            components["insider_txns"] = "Mixed, more selling"
        elif sells > 0:
            insider_score = 15
            components["insider_txns"] = f"Net selling ({sells:,.0f} shares)"
        else:
            components["insider_txns"] = "No clear buys/sells"
    else:
        components["insider_txns"] = "No recent transactions"
    scores.append(insider_score * 0.35)

    # Float / shares
    float_score = 50
    shares_float = quote.get("sharesOutstanding", 0) or 0
    if shares_float:
        if shares_float < 20_000_000:
            float_score = 90
        elif shares_float < 50_000_000:
            float_score = 70
        elif shares_float < 200_000_000:
            float_score = 50
        else:
            float_score = 30
        components["shares"] = f"{shares_float/1e6:.1f}M outstanding"
    scores.append(float_score * 0.20)

    # Market cap tier
    mcap_score = 50
    mcap = quote.get("marketCap", 0) or 0
    if mcap:
        if mcap < 500_000_000:
            mcap_score = 80  # small cap = bigger move potential
        elif mcap < 2_000_000_000:
            mcap_score = 65
        else:
            mcap_score = 45
        components["mcap"] = f"${mcap/1e6:.0f}M"
    scores.append(mcap_score * 0.15)

    # Beta (volatility)
    beta_score = 50
    beta = profile.get("beta", 0) or quote.get("beta", 0) or 0
    if beta:
        if 1.2 <= beta <= 2.5:
            beta_score = 75  # good volatility for rerating
        elif beta > 2.5:
            beta_score = 50
        elif beta < 0.8:
            beta_score = 30
        components["beta"] = f"{beta:.1f}"
    scores.append(beta_score * 0.15)

    # Sector
    sector = profile.get("sector", "")
    if sector:
        components["sector"] = sector
    scores.append(50 * 0.15)  # neutral for sector

    total = sum(scores)
    return {"score": round(total, 1), "components": components,
            "details": ", ".join(f"{k}: {v}" for k, v in components.items())}


def _yf_score(ticker: str) -> dict:
    """Fallback to yfinance."""
    try:
        import yfinance as yf
        stock = yf.Ticker(ticker)
        info = stock.info or {}
    except Exception:
        return {"score": 0, "details": "Failed to fetch data", "components": {}}

    components = {}
    scores = []

    # Insider transactions
    insider_score = 50
    try:
        txns = stock.insider_transactions
        if txns is not None and not txns.empty:
            buys, sells = 0, 0
            for _, t in txns.iterrows():
                text = str(t.get("Text", "")).lower()
                shares = t.get("Shares", 0) or 0
                if "purchase" in text or "buy" in text:
                    buys += abs(shares)
                elif "sale" in text or "sell" in text:
                    sells += abs(shares)
            if buys > 0 and sells == 0:
                insider_score = 100
                components["insider_txns"] = f"Net buying ({buys:,.0f})"
            elif buys > sells:
                insider_score = 75
                components["insider_txns"] = "More buying"
            elif sells > 0:
                insider_score = 15
                components["insider_txns"] = f"Net selling ({sells:,.0f})"
    except Exception:
        pass
    scores.append(insider_score * 0.35)

    # Ownership
    own_score = 50
    held = info.get("heldPercentInsiders")
    if held:
        if held > 0.20: own_score = 100
        elif held > 0.10: own_score = 80
        elif held > 0.05: own_score = 60
        components["insider_own"] = f"{held:.1%}"
    scores.append(own_score * 0.20)

    # Float
    float_score = 50
    fs = info.get("floatShares")
    if fs:
        if fs < 20_000_000: float_score = 90
        elif fs < 50_000_000: float_score = 70
        elif fs < 200_000_000: float_score = 50
        else: float_score = 30
        components["float"] = f"{fs/1e6:.1f}M"
    scores.append(float_score * 0.20)

    scores.append(50 * 0.25)  # neutral for remaining

    total = sum(scores)
    return {"score": round(total, 1), "components": components,
            "details": ", ".join(f"{k}: {v}" for k, v in components.items())}


def score(ticker: str) -> dict:
    if fmp.is_configured():
        return _fmp_score(ticker)
    return _yf_score(ticker)
