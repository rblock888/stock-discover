"""
Early Detection Module — "Einstein Score"
==========================================
Finds stocks BEFORE the move by measuring divergence between
improving fundamentals and depressed price.

The idea: a stock that has improving revenue, insider buying,
and growing attention BUT is still near its lows and under-owned
by institutions = potential rerating candidate.

Key signals:
1. Fundamental-Price Divergence: fundamentals up, price still down
2. Accumulation: quiet volume increase without big price move yet
3. Revenue Inflection: going from negative to positive growth
4. Insider buying at low prices (smart money front-running)
5. Low institutional ownership (room for big buyers to enter)
6. Early social attention (mentions starting, not peaking)
7. Price near 52-week low but off absolute bottom (bottoming pattern)
"""

import fmp


def _safe_div(a, b, default=0):
    try:
        return a / b if b and b != 0 else default
    except Exception:
        return default


def score(ticker: str, bucket_scores: dict = None) -> dict:
    """
    Calculate early detection / potential score.

    Uses raw bucket scores + additional analysis to find
    stocks where the move HASN'T happened yet.

    Returns score 0-100 where higher = more early-stage potential.
    """
    components = {}
    scores = []

    # Get data
    if fmp.is_configured():
        quote = fmp.get_quote(ticker)
        profile = fmp.get_profile(ticker)
        income = fmp.get_income_statement(ticker, limit=8)
        hist = fmp.get_historical_price(ticker, days=365)
    else:
        try:
            import yfinance as yf
            stock = yf.Ticker(ticker)
            info = stock.info or {}
            quote = {
                "price": info.get("currentPrice") or info.get("regularMarketPrice", 0),
                "marketCap": info.get("marketCap", 0),
                "avgVolume": info.get("averageVolume", 0),
                "volume": info.get("volume", 0),
                "yearLow": info.get("fiftyTwoWeekLow", 0),
                "yearHigh": info.get("fiftyTwoWeekHigh", 0),
                "changesPercentage": 0,
            }
            profile = {
                "mktCap": info.get("marketCap", 0),
            }
            income = []
            price_hist = stock.history(period="1y")
            hist = []
            if not price_hist.empty:
                for _, row in price_hist.iterrows():
                    hist.append({"close": row["Close"], "volume": row["Volume"]})
                hist = list(reversed(hist))
        except Exception:
            quote, profile, income, hist = {}, {}, [], []

    price = quote.get("price", 0) or 0
    year_low = quote.get("yearLow", 0) or 0
    year_high = quote.get("yearHigh", 0) or 0

    if not price or price <= 0:
        return {"score": 0, "details": "No price data", "components": {}}

    # =========================================================================
    # 1. PRICE POSITION — Near lows = more upside potential (0-100)
    # Best: 10-30% off 52w low (bottoming, not still falling)
    # Worst: At 52w high (run already happened)
    # =========================================================================
    position_score = 0
    if year_high > 0 and year_low > 0:
        range_52w = year_high - year_low
        if range_52w > 0:
            position_in_range = (price - year_low) / range_52w
            # Sweet spot: 10-35% up from 52w low
            if 0.10 <= position_in_range <= 0.35:
                position_score = 100  # bottoming pattern, perfect
            elif position_in_range < 0.10:
                position_score = 60   # might still be falling
            elif position_in_range <= 0.50:
                position_score = 70   # early stages
            elif position_in_range <= 0.75:
                position_score = 30   # mid-run
            else:
                position_score = 5    # near highs, move happened

            pct_from_low = (price - year_low) / year_low * 100 if year_low > 0 else 0
            pct_from_high = (year_high - price) / year_high * 100 if year_high > 0 else 0
            components["price_position"] = f"{position_in_range:.0%} of 52w range"
            components["upside_to_high"] = f"{pct_from_high:.0f}% to 52w high"
    scores.append(("price_position", position_score, 0.20))

    # =========================================================================
    # 2. FUNDAMENTAL-PRICE DIVERGENCE — Fundamentals improving + price low (0-100)
    # Uses bucket scores if available
    # =========================================================================
    divergence_score = 50
    if bucket_scores:
        fund_raw = bucket_scores.get("fundamentals", {}).get("score", 50)
        mom_raw = bucket_scores.get("momentum", {}).get("score", 50)

        # High fundamentals + low momentum = DIVERGENCE = opportunity
        if fund_raw >= 60 and mom_raw < 40:
            divergence_score = 100
            components["divergence"] = f"Fundamentals {fund_raw:.0f} but momentum only {mom_raw:.0f}"
        elif fund_raw >= 50 and mom_raw < 50:
            divergence_score = 75
            components["divergence"] = f"Fundamentals ahead of price"
        elif fund_raw >= 60 and mom_raw >= 60:
            divergence_score = 30  # already recognized
            components["divergence"] = "Already priced in"
        else:
            divergence_score = 40
            components["divergence"] = "No clear divergence"
    scores.append(("divergence", divergence_score, 0.25))

    # =========================================================================
    # 3. REVENUE INFLECTION — Going from bad to good (0-100)
    # The most powerful early signal
    # =========================================================================
    inflection_score = 50
    if income and len(income) >= 4:
        revenues = [q.get("revenue", 0) for q in income[:6]]
        revenues = [r for r in revenues if r and r > 0]

        if len(revenues) >= 4:
            # QoQ growth rates
            growths = []
            for i in range(len(revenues) - 1):
                if revenues[i+1] > 0:
                    growths.append((revenues[i] - revenues[i+1]) / abs(revenues[i+1]))

            if len(growths) >= 2:
                latest_growth = growths[0]
                prior_growth = growths[1]

                # Inflection: growth accelerating from negative/low to positive
                if prior_growth < 0 and latest_growth > 0:
                    inflection_score = 100
                    components["inflection"] = f"Revenue turned positive: {prior_growth:.0%} → {latest_growth:.0%}"
                elif latest_growth > prior_growth and latest_growth > 0:
                    inflection_score = 80
                    components["inflection"] = f"Revenue accelerating: {prior_growth:.0%} → {latest_growth:.0%}"
                elif latest_growth > 0.20:
                    inflection_score = 65
                    components["inflection"] = f"Strong growth: {latest_growth:.0%}"
                elif latest_growth > 0:
                    inflection_score = 50
                    components["inflection"] = f"Growing: {latest_growth:.0%}"
                elif latest_growth < prior_growth:
                    inflection_score = 15
                    components["inflection"] = f"Decelerating: {latest_growth:.0%}"
                else:
                    inflection_score = 30
    scores.append(("inflection", inflection_score, 0.20))

    # =========================================================================
    # 4. QUIET ACCUMULATION — Volume increasing without big price move (0-100)
    # Smart money buying before the crowd
    # =========================================================================
    accumulation_score = 50
    if hist and len(hist) >= 60:
        closes = [d.get("close", 0) for d in hist]
        volumes = [d.get("volume", 0) for d in hist]

        if closes and volumes:
            # Recent 20d volume vs prior 20d
            recent_vol = sum(volumes[:20]) / 20 if len(volumes) >= 20 else 0
            prior_vol = sum(volumes[20:40]) / 20 if len(volumes) >= 40 else 0

            # Recent 20d price change
            recent_price_change = 0
            if closes[0] > 0 and len(closes) >= 20 and closes[19] > 0:
                recent_price_change = (closes[0] - closes[19]) / closes[19]

            if prior_vol > 0:
                vol_ratio = recent_vol / prior_vol

                # Volume up but price flat/slightly up = accumulation
                if vol_ratio > 1.3 and -0.05 <= recent_price_change <= 0.15:
                    accumulation_score = 90
                    components["accumulation"] = f"Vol {vol_ratio:.1f}x, price {recent_price_change:+.1%} (quiet buying)"
                elif vol_ratio > 1.2:
                    accumulation_score = 65
                    components["accumulation"] = f"Vol {vol_ratio:.1f}x expanding"
                elif vol_ratio < 0.7:
                    accumulation_score = 25
                    components["accumulation"] = "Volume drying up"
                else:
                    components["accumulation"] = f"Vol {vol_ratio:.1f}x"
    scores.append(("accumulation", accumulation_score, 0.15))

    # =========================================================================
    # 5. ROOM TO RUN — Low institutional ownership + small cap (0-100)
    # More room for big buyers = bigger potential move
    # =========================================================================
    room_score = 50
    mcap = quote.get("marketCap", 0) or profile.get("mktCap", 0) or 0

    if mcap > 0:
        if mcap < 300_000_000:
            room_score = 95  # micro-cap, huge move potential
            components["size"] = f"Micro-cap ${mcap/1e6:.0f}M"
        elif mcap < 1_000_000_000:
            room_score = 80
            components["size"] = f"Small-cap ${mcap/1e6:.0f}M"
        elif mcap < 5_000_000_000:
            room_score = 55
            components["size"] = f"Mid-cap ${mcap/1e6:.0f}M"
        else:
            room_score = 20
            components["size"] = f"Large-cap ${mcap/1e6:.0f}M"
    scores.append(("room_to_run", room_score, 0.10))

    # =========================================================================
    # 6. INSIDER SIGNAL at low prices (bonus from bucket scores)
    # =========================================================================
    insider_bonus = 0
    if bucket_scores:
        insider_raw = bucket_scores.get("insider", {}).get("score", 50)
        if insider_raw >= 70 and position_score >= 60:
            insider_bonus = 10
            components["insider_at_lows"] = "Insiders buying near lows"
    scores.append(("insider_bonus", min(100, insider_bonus * 10), 0.10))

    # =========================================================================
    # COMPOSITE
    # =========================================================================
    total = sum(s * w for _, s, w in scores)

    # Calculate potential upside estimate
    if year_high > 0 and price > 0:
        potential_upside = (year_high - price) / price
        components["potential"] = f"{potential_upside:.0%} to 52w high"

    return {
        "score": round(total, 1),
        "components": components,
        "details": ", ".join(f"{k}: {v}" for k, v in components.items()),
    }
