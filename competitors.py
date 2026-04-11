"""
Competitor Analysis Module
==========================
Finds peers/competitors and compares performance.
Key insight: if competitors are running and this stock hasn't moved,
it could be next in line for a rerating.
"""

import fmp


# Manual sector/theme peer groups for common discovery targets
PEER_GROUPS = {
    # Quantum computing
    "IONQ": ["RGTI", "QUBT", "QBTS", "ARQQ"],
    "RGTI": ["IONQ", "QUBT", "QBTS", "ARQQ"],
    "QUBT": ["IONQ", "RGTI", "QBTS", "ARQQ"],
    # Space / satellite
    "ASTS": ["RKLB", "LUNR", "SPIR", "BKSY", "MNTS"],
    "RKLB": ["ASTS", "LUNR", "SPIR", "ASTR"],
    "LUNR": ["ASTS", "RKLB", "SPIR", "BKSY"],
    # AI / defense tech
    "PLTR": ["BBAI", "SOUN", "BIGB"],
    "BBAI": ["PLTR", "SOUN", "BIGB"],
    "SOUN": ["PLTR", "BBAI"],
    # Nuclear / energy
    "SMR": ["OKLO", "NNE", "LEU", "CCJ"],
    "OKLO": ["SMR", "NNE", "LEU", "CCJ"],
    "NNE": ["SMR", "OKLO", "LEU"],
    "LEU": ["SMR", "OKLO", "NNE", "CCJ"],
    # eVTOL / urban air
    "JOBY": ["ACHR", "LILM", "EVTL"],
    "ACHR": ["JOBY", "LILM", "EVTL"],
    # Fintech
    "SOFI": ["AFRM", "HIMS", "CLOV", "UPST"],
    "AFRM": ["SOFI", "HIMS", "UPST"],
    "HIMS": ["SOFI", "AFRM", "CLOV"],
    # Photonics / semiconductors
    "LWLG": ["POET", "COHR", "II-VI", "LITE"],
}


def _get_peers_fmp(ticker: str) -> list:
    """Get peers from FMP API."""
    try:
        data = fmp._get(f"stock_peers", {"symbol": ticker})
        if data and isinstance(data, list) and len(data) > 0:
            peers = data[0].get("peersList", [])
            return [p for p in peers if p != ticker][:8]
    except Exception:
        pass
    return []


def _get_peers(ticker: str) -> list:
    """Get peers from manual list + FMP API."""
    peers = list(PEER_GROUPS.get(ticker.upper(), []))

    # Also try FMP peers
    if fmp.is_configured():
        fmp_peers = _get_peers_fmp(ticker)
        for p in fmp_peers:
            if p not in peers:
                peers.append(p)

    return peers[:8]


def _get_performance(ticker: str) -> dict:
    """Get price performance for a ticker."""
    if fmp.is_configured():
        quote = fmp.get_quote(ticker)
        hist = fmp.get_historical_price(ticker, days=180)
        if quote and hist:
            price = quote.get("price", 0) or 0
            year_high = quote.get("yearHigh", 0) or 0
            year_low = quote.get("yearLow", 0) or 0
            mcap = quote.get("marketCap", 0) or 0
            name = quote.get("name", ticker)

            # 3-month return
            ret_3m = 0
            if len(hist) >= 63:
                old_price = hist[62].get("close", 0)
                if old_price > 0:
                    ret_3m = (price - old_price) / old_price

            # 1-month return
            ret_1m = 0
            if len(hist) >= 21:
                old_price = hist[20].get("close", 0)
                if old_price > 0:
                    ret_1m = (price - old_price) / old_price

            return {
                "ticker": ticker,
                "name": name,
                "price": price,
                "mcap": mcap,
                "ret_1m": ret_1m,
                "ret_3m": ret_3m,
                "year_high": year_high,
                "year_low": year_low,
                "pct_from_high": (year_high - price) / year_high if year_high > 0 else 0,
            }
    else:
        try:
            import yfinance as yf
            stock = yf.Ticker(ticker)
            info = stock.info or {}
            hist = stock.history(period="6mo")

            price = info.get("currentPrice") or info.get("regularMarketPrice", 0)
            if not price or not hist.empty:
                closes = hist["Close"]
                price = closes.iloc[-1] if len(closes) > 0 else 0
                ret_3m = (closes.iloc[-1] / closes.iloc[-63] - 1) if len(closes) >= 63 else 0
                ret_1m = (closes.iloc[-1] / closes.iloc[-21] - 1) if len(closes) >= 21 else 0
            else:
                ret_3m, ret_1m = 0, 0

            return {
                "ticker": ticker,
                "name": info.get("shortName", ticker),
                "price": price,
                "mcap": info.get("marketCap", 0),
                "ret_1m": ret_1m,
                "ret_3m": ret_3m,
                "year_high": info.get("fiftyTwoWeekHigh", 0),
                "year_low": info.get("fiftyTwoWeekLow", 0),
                "pct_from_high": 0,
            }
        except Exception:
            pass

    return {"ticker": ticker, "name": ticker, "price": 0, "mcap": 0,
            "ret_1m": 0, "ret_3m": 0, "year_high": 0, "year_low": 0, "pct_from_high": 0}


def analyze(ticker: str) -> dict:
    """
    Analyze a stock vs its competitors.

    Returns:
    - peer list with performance
    - whether this stock is lagging (opportunity) or leading
    - peer average performance vs this stock
    """
    peers = _get_peers(ticker)
    if not peers:
        return {
            "peers": [],
            "has_peers": False,
            "lagging": False,
            "peer_avg_3m": 0,
            "stock_3m": 0,
            "gap": 0,
            "details": "No peers found",
        }

    # Get performance for stock and all peers
    stock_perf = _get_performance(ticker)
    peer_perfs = []
    for p in peers:
        perf = _get_performance(p)
        if perf.get("price", 0) > 0:
            peer_perfs.append(perf)

    if not peer_perfs:
        return {
            "peers": [],
            "has_peers": False,
            "lagging": False,
            "peer_avg_3m": 0,
            "stock_3m": stock_perf.get("ret_3m", 0),
            "gap": 0,
            "details": "Could not fetch peer data",
        }

    # Calculate peer averages
    peer_avg_3m = sum(p["ret_3m"] for p in peer_perfs) / len(peer_perfs)
    peer_avg_1m = sum(p["ret_1m"] for p in peer_perfs) / len(peer_perfs)
    stock_3m = stock_perf.get("ret_3m", 0)
    stock_1m = stock_perf.get("ret_1m", 0)

    # Gap = how much this stock is lagging peers
    gap_3m = peer_avg_3m - stock_3m
    gap_1m = peer_avg_1m - stock_1m

    # Is this stock lagging? (peers up more or this stock is down while peers are up)
    lagging = gap_3m > 0.15  # peers outperformed by 15%+

    # Best performing peer
    best_peer = max(peer_perfs, key=lambda p: p["ret_3m"])

    # Build peer comparison list
    peer_list = []
    for p in sorted(peer_perfs, key=lambda x: x["ret_3m"], reverse=True):
        peer_list.append({
            "ticker": p["ticker"],
            "name": p["name"],
            "ret_1m": round(p["ret_1m"] * 100, 1),
            "ret_3m": round(p["ret_3m"] * 100, 1),
            "mcap": p["mcap"],
            "pct_from_high": round(p.get("pct_from_high", 0) * 100, 1),
        })

    # Market position analysis
    stock_mcap = stock_perf.get("mcap", 0)
    all_mcaps = [p["mcap"] for p in peer_perfs if p["mcap"] > 0]
    if stock_mcap > 0:
        all_mcaps.append(stock_mcap)

    position = "unknown"
    biggest = None
    if all_mcaps and stock_mcap > 0:
        max_mcap = max(all_mcaps)
        min_mcap = min(all_mcaps)
        rank = sorted(all_mcaps, reverse=True).index(stock_mcap) + 1

        if stock_mcap == max_mcap:
            position = "leader"
        elif stock_mcap >= max_mcap * 0.5:
            position = "contender"
        elif stock_mcap >= max_mcap * 0.1:
            position = "challenger"
        else:
            position = "underdog"

        # Find the biggest peer
        biggest_peer = max(peer_perfs, key=lambda p: p.get("mcap", 0))
        if biggest_peer["mcap"] > stock_mcap * 3:
            biggest = {
                "ticker": biggest_peer["ticker"],
                "name": biggest_peer["name"],
                "mcap": biggest_peer["mcap"],
                "ratio": round(biggest_peer["mcap"] / stock_mcap, 1) if stock_mcap > 0 else 0,
            }

    return {
        "peers": peer_list,
        "has_peers": True,
        "lagging": lagging,
        "peer_avg_3m": round(peer_avg_3m * 100, 1),
        "peer_avg_1m": round(peer_avg_1m * 100, 1),
        "stock_3m": round(stock_3m * 100, 1),
        "stock_1m": round(stock_1m * 100, 1),
        "gap_3m": round(gap_3m * 100, 1),
        "best_peer": best_peer["ticker"],
        "best_peer_3m": round(best_peer["ret_3m"] * 100, 1),
        "position": position,  # leader, contender, challenger, underdog
        "biggest_competitor": biggest,  # None or {ticker, name, mcap, ratio}
        "mcap_rank": f"{rank}/{len(all_mcaps)}" if all_mcaps and stock_mcap > 0 else "N/A",
        "details": f"{'Lagging' if lagging else 'In line with'} peers by {abs(gap_3m)*100:.0f}%",
    }
