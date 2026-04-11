"""Financial Modeling Prep API wrapper. Replaces yfinance for server deployments."""

import os
import requests
from functools import lru_cache
from datetime import datetime, timedelta

API_KEY = os.environ.get("FMP_API_KEY", "")
BASE = "https://financialmodelingprep.com/api/v3"


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
    """Get current quote data (price, volume, market cap, etc.)."""
    data = _get(f"quote/{ticker}")
    if data and isinstance(data, list) and len(data) > 0:
        return data[0]
    return {}


def get_profile(ticker: str) -> dict:
    """Get company profile (sector, industry, description, etc.)."""
    data = _get(f"profile/{ticker}")
    if data and isinstance(data, list) and len(data) > 0:
        return data[0]
    return {}


def get_income_statement(ticker: str, period: str = "quarter", limit: int = 8) -> list:
    """Get income statements."""
    data = _get(f"income-statement/{ticker}", {"period": period, "limit": limit})
    return data if isinstance(data, list) else []


def get_balance_sheet(ticker: str, period: str = "quarter", limit: int = 8) -> list:
    """Get balance sheets."""
    data = _get(f"balance-sheet-statement/{ticker}", {"period": period, "limit": limit})
    return data if isinstance(data, list) else []


def get_ratios(ticker: str, period: str = "quarter", limit: int = 4) -> list:
    """Get financial ratios."""
    data = _get(f"ratios/{ticker}", {"period": period, "limit": limit})
    return data if isinstance(data, list) else []


def get_key_metrics(ticker: str, period: str = "quarter", limit: int = 4) -> list:
    """Get key metrics (revenue per share, margins, etc.)."""
    data = _get(f"key-metrics/{ticker}", {"period": period, "limit": limit})
    return data if isinstance(data, list) else []


def get_historical_price(ticker: str, days: int = 180) -> list:
    """Get historical daily prices."""
    from_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    to_date = datetime.now().strftime("%Y-%m-%d")
    data = _get(f"historical-price-full/{ticker}", {"from": from_date, "to": to_date})
    if isinstance(data, dict):
        return data.get("historical", [])
    return []


def get_insider_trading(ticker: str, limit: int = 50) -> list:
    """Get insider transactions."""
    data = _get(f"insider-trading", {"symbol": ticker, "limit": limit})
    return data if isinstance(data, list) else []


def get_analyst_estimates(ticker: str) -> list:
    """Get analyst estimates."""
    data = _get(f"analyst-estimates/{ticker}", {"limit": 4})
    return data if isinstance(data, list) else []


def get_price_target(ticker: str) -> list:
    """Get analyst price targets."""
    data = _get(f"price-target-summary/{ticker}")
    return data if isinstance(data, list) else []


def get_earnings_calendar(ticker: str = None) -> list:
    """Get upcoming earnings dates."""
    params = {}
    if ticker:
        params["symbol"] = ticker
    else:
        from_date = datetime.now().strftime("%Y-%m-%d")
        to_date = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
        params["from"] = from_date
        params["to"] = to_date
    data = _get("earning_calendar", params)
    return data if isinstance(data, list) else []


def get_stock_screener(
    market_cap_min: int = 50_000_000,
    market_cap_max: int = 10_000_000_000,
    volume_min: int = 100_000,
    price_min: float = 0.5,
    price_max: float = 50,
    limit: int = 100,
) -> list:
    """Screen stocks by criteria."""
    data = _get("stock-screener", {
        "marketCapMoreThan": market_cap_min,
        "marketCapLowerThan": market_cap_max,
        "volumeMoreThan": volume_min,
        "priceMoreThan": price_min,
        "priceLowerThan": price_max,
        "limit": limit,
    })
    return data if isinstance(data, list) else []


def get_gainers() -> list:
    """Get today's top gainers."""
    data = _get("stock_market/gainers")
    return data if isinstance(data, list) else []


def get_most_active() -> list:
    """Get most active by volume."""
    data = _get("stock_market/actives")
    return data if isinstance(data, list) else []


def is_configured() -> bool:
    return bool(API_KEY)
