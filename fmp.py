"""Financial Modeling Prep API wrapper — uses /stable/ endpoints (new API)."""

import os
import requests
from datetime import datetime, timedelta

API_KEY = os.environ.get("FMP_API_KEY", "")
BASE = "https://financialmodelingprep.com/stable"


def _get(endpoint: str, params: dict = None) -> dict | list | None:
    if not API_KEY:
        return None
    p = {"apikey": API_KEY, **(params or {})}
    try:
        resp = requests.get(f"{BASE}/{endpoint}", params=p, timeout=15)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


def get_quote(ticker: str) -> dict:
    """Get current quote — uses profile endpoint on stable API.
    Maps fields to match what scoring modules expect."""
    data = _get("profile", {"symbol": ticker})
    if data and isinstance(data, list) and len(data) > 0:
        d = data[0]
        # Parse 52w range "189.81-288.62"
        year_low, year_high = 0, 0
        if d.get("range"):
            try:
                parts = d["range"].split("-")
                year_low = float(parts[0])
                year_high = float(parts[1])
            except Exception:
                pass
        d["yearLow"] = year_low
        d["yearHigh"] = year_high
        d["avgVolume"] = d.get("averageVolume", 0)
        d["changesPercentage"] = d.get("changePercentage", 0)
        d["sharesOutstanding"] = int(d["marketCap"] / d["price"]) if d.get("price") and d.get("marketCap") else 0
        d["name"] = d.get("companyName", ticker)
        d["mktCap"] = d.get("marketCap", 0)
        return d
    return {}


def get_profile(ticker: str) -> dict:
    """Get company profile."""
    return get_quote(ticker)  # same endpoint on stable API


def get_income_statement(ticker: str, period: str = "quarter", limit: int = 8) -> list:
    """Get income statements."""
    data = _get("income-statement", {"symbol": ticker, "period": period, "limit": limit})
    return data if isinstance(data, list) else []


def get_balance_sheet(ticker: str, period: str = "quarter", limit: int = 8) -> list:
    """Get balance sheets."""
    data = _get("balance-sheet-statement", {"symbol": ticker, "period": period, "limit": limit})
    return data if isinstance(data, list) else []


def get_ratios(ticker: str, period: str = "quarter", limit: int = 4) -> list:
    """Get financial ratios."""
    data = _get("ratios", {"symbol": ticker, "period": period, "limit": limit})
    return data if isinstance(data, list) else []


def get_key_metrics(ticker: str, period: str = "quarter", limit: int = 4) -> list:
    """Get key metrics."""
    data = _get("key-metrics", {"symbol": ticker, "period": period, "limit": limit})
    return data if isinstance(data, list) else []


def get_historical_price(ticker: str, days: int = 180) -> list:
    """Get historical daily prices."""
    data = _get("historical-price-eod/full", {"symbol": ticker})
    if isinstance(data, list):
        # Return only the requested number of days, newest first
        return data[:days]
    return []


def get_insider_trading(ticker: str, limit: int = 50) -> list:
    """Get insider transactions."""
    data = _get("insider-trading", {"symbol": ticker, "limit": limit})
    return data if isinstance(data, list) else []


def get_analyst_estimates(ticker: str) -> list:
    """Get analyst estimates."""
    data = _get("analyst-estimates", {"symbol": ticker, "limit": 4})
    return data if isinstance(data, list) else []


def get_price_target(ticker: str) -> list:
    """Get analyst price targets."""
    data = _get("price-target-summary", {"symbol": ticker})
    return data if isinstance(data, list) else []


def get_earnings_calendar(ticker: str = None) -> list:
    """Get upcoming earnings dates."""
    params = {}
    if ticker:
        params["symbol"] = ticker
    else:
        params["from"] = datetime.now().strftime("%Y-%m-%d")
        params["to"] = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
    data = _get("earning_calendar", params)
    return data if isinstance(data, list) else []


def get_stock_screener(**kwargs) -> list:
    """Screen stocks by criteria."""
    data = _get("stock-screener", kwargs)
    return data if isinstance(data, list) else []


def get_gainers() -> list:
    """Get today's top gainers."""
    data = _get("gainers")
    return data if isinstance(data, list) else []


def get_most_active() -> list:
    """Get most active by volume."""
    data = _get("actives")
    return data if isinstance(data, list) else []


def is_configured() -> bool:
    # FMP free tier only works for large caps — disable for small-cap discovery
    # yfinance works fine from VPS (not a shared cloud IP)
    return False
