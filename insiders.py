"""Insider activity and capital structure scoring."""

import requests
import yfinance as yf
from datetime import datetime, timedelta
import config


def _get_insider_transactions(ticker: str) -> list:
    """Fetch recent insider transactions from yfinance."""
    try:
        stock = yf.Ticker(ticker)
        txns = stock.insider_transactions
        if txns is None or txns.empty:
            return []
        return txns.to_dict("records")
    except Exception:
        return []


def _get_insider_from_sec(ticker: str) -> list:
    """Fetch Form 4 filings from SEC EDGAR as a fallback."""
    try:
        cik_url = f"https://efts.sec.gov/LATEST/search-index?q=%22{ticker}%22&dateRange=custom&startdt={(datetime.now() - timedelta(days=config.INSIDER_LOOKBACK_DAYS)).strftime('%Y-%m-%d')}&enddt={datetime.now().strftime('%Y-%m-%d')}&forms=4"
        headers = {"User-Agent": config.SEC_USER_AGENT}

        # Use EDGAR full-text search for Form 4s
        search_url = "https://efts.sec.gov/LATEST/search-index"
        params = {
            "q": f'"{ticker}"',
            "forms": "4",
            "dateRange": "custom",
            "startdt": (datetime.now() - timedelta(days=config.INSIDER_LOOKBACK_DAYS)).strftime("%Y-%m-%d"),
            "enddt": datetime.now().strftime("%Y-%m-%d"),
        }
        resp = requests.get(
            "https://efts.sec.gov/LATEST/search-index",
            params=params,
            headers=headers,
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            return data.get("hits", {}).get("hits", [])
    except Exception:
        pass
    return []


def score(ticker: str) -> dict:
    """Return an insider/structure score (0-100) and details."""
    components = {}
    scores = []

    try:
        stock = yf.Ticker(ticker)
        info = stock.info or {}
    except Exception:
        return {"score": 0, "details": "Failed to fetch data", "components": {}}

    # --- Insider transactions ---
    insider_score = 50  # neutral default
    txns = _get_insider_transactions(ticker)
    if txns:
        buys = 0
        sells = 0
        cutoff = datetime.now() - timedelta(days=config.INSIDER_LOOKBACK_DAYS)
        for t in txns:
            try:
                text = str(t.get("Text", "")).lower()
                shares = t.get("Shares", 0) or 0
                if "purchase" in text or "buy" in text:
                    buys += abs(shares)
                elif "sale" in text or "sell" in text:
                    sells += abs(shares)
            except Exception:
                continue

        if buys > 0 and sells == 0:
            insider_score = 100
            components["insider_txns"] = f"Net buying ({buys:,.0f} shares)"
        elif buys > sells:
            insider_score = 75
            components["insider_txns"] = f"More buying than selling"
        elif sells > buys and buys > 0:
            insider_score = 35
            components["insider_txns"] = f"Mixed, more selling"
        elif sells > 0:
            insider_score = 15
            components["insider_txns"] = f"Net selling ({sells:,.0f} shares)"
        else:
            components["insider_txns"] = "No clear buys/sells"
    else:
        components["insider_txns"] = "No recent transactions"
    scores.append(("insider_txns", insider_score, 0.35))

    # --- Insider ownership ---
    ownership_score = 50
    held_pct = info.get("heldPercentInsiders")
    if held_pct is not None:
        # Higher insider ownership = more aligned
        if held_pct > 0.20:
            ownership_score = 100
        elif held_pct > 0.10:
            ownership_score = 80
        elif held_pct > 0.05:
            ownership_score = 60
        else:
            ownership_score = 40
        components["insider_own"] = f"{held_pct:.1%}"
    scores.append(("insider_own", ownership_score, 0.20))

    # --- Float size (smaller float = bigger move potential) ---
    float_score = 50
    float_shares = info.get("floatShares")
    shares_out = info.get("sharesOutstanding")
    if float_shares:
        if float_shares < 20_000_000:
            float_score = 90
        elif float_shares < 50_000_000:
            float_score = 70
        elif float_shares < 200_000_000:
            float_score = 50
        else:
            float_score = 30
        components["float"] = f"{float_shares/1e6:.1f}M shares"
    scores.append(("float", float_score, 0.15))

    # --- Institutional ownership (moderate is best) ---
    inst_score = 50
    inst_pct = info.get("heldPercentInstitutions")
    if inst_pct is not None:
        # Sweet spot: 20-60% institutional
        if 0.20 <= inst_pct <= 0.60:
            inst_score = 80
        elif inst_pct > 0.60:
            inst_score = 60  # heavily owned, less upside surprise
        elif inst_pct < 0.10:
            inst_score = 40  # under-owned, could be risky
        else:
            inst_score = 55
        components["inst_own"] = f"{inst_pct:.1%}"
    scores.append(("inst_own", inst_score, 0.15))

    # --- Dilution risk (warrants/convertibles proxy via share count trend) ---
    dilution_risk_score = 50
    try:
        bs = stock.quarterly_balance_sheet
        if bs is not None and not bs.empty:
            for label in ["Share Issued", "Ordinary Shares Number"]:
                if label in bs.index:
                    share_row = bs.loc[label].dropna()
                    if len(share_row) >= 2:
                        recent = share_row.iloc[0]
                        older = share_row.iloc[-1]
                        if older > 0:
                            change = (recent - older) / older
                            if change <= 0:
                                dilution_risk_score = 90  # shrinking share count
                                components["dilution_risk"] = "Shares decreasing"
                            elif change < 0.05:
                                dilution_risk_score = 70
                                components["dilution_risk"] = f"{change:.1%} dilution"
                            elif change < 0.20:
                                dilution_risk_score = 40
                                components["dilution_risk"] = f"{change:.1%} dilution"
                            else:
                                dilution_risk_score = 10
                                components["dilution_risk"] = f"{change:.1%} heavy dilution"
                    break
    except Exception:
        pass
    scores.append(("dilution_risk", dilution_risk_score, 0.15))

    total = sum(s * w for _, s, w in scores)

    return {
        "score": round(total, 1),
        "components": components,
        "details": ", ".join(f"{k}: {v}" for k, v in components.items()),
    }
