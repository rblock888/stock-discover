"""Day-movers watchlist — names with the ENERGY to move +5-10% TODAY.

This is a different question from the swing grades. A grade-A setup is a
multi-day trade plan; a day mover needs (1) the CAPABILITY — a stock whose
normal day is 5-8% (ATR%) can print 5-10%, a 1.5%-a-day large cap can't —
and (2) a TRIGGER sitting right there: a coiled base at the pivot, a fresh
catalyst/news event, squeeze fuel, or a vertical-feed hint (FDA/clinical).

Exclusions keep the list honest:
  • AVOID-graded names (vetoed for traps/dilution/downtrends — a veto is a veto)
  • earnings TODAY (it will move, but that's a coin flip, not a setup)
  • illiquid (< $2M average daily dollar volume) or sub-$1 names

Every published list is logged with previous closes so its hit rate
("did it actually touch +5% that day?") is MEASURED — see
evaluation.day_movers_scorecard(). Accrues from first publication.
"""

MIN_SCORE = 55
MAX_MOVERS = 5
MIN_DOLLAR_VOL = 2_000_000
MIN_PRICE = 1.0


def _f(x, d=0.0):
    try:
        v = float(x)
        return v if v == v else d
    except (TypeError, ValueError):
        return d


def _capability(atr_pct: float) -> float:
    """ATR% → base score: the stock's normal daily range IS its ceiling."""
    pts = [(2.0, 10.0), (3.0, 25.0), (5.0, 55.0), (7.0, 75.0), (10.0, 90.0), (15.0, 100.0)]
    if atr_pct <= pts[0][0]:
        return pts[0][1]
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        if atr_pct <= x2:
            return y1 + (y2 - y1) * (atr_pct - x1) / (x2 - x1)
    return 100.0


def score_one(stock: dict) -> dict | None:
    """Day-move potential for one ranked stock, or None if excluded."""
    v = stock.get("setup") or {}
    q = stock.get("quote") or {}
    if v.get("grade") == "AVOID":
        return None
    px = _f(q.get("price"))
    if px < MIN_PRICE or px * _f(q.get("avg_volume")) < MIN_DOLLAR_VOL:
        return None
    ed = ((stock.get("breakdown", {}).get("catalyst", {}) or {}).get("metrics") or {}).get("earnings_days")
    if ed is not None and ed == 0:
        return None   # earnings-day moves are coin flips, not setups

    edge = stock.get("edge") or {}
    atr_pct = _f((edge.get("pulse") or {}).get("atr_pct"))
    coiled = stock.get("coiled") or {}
    cat = _f((stock.get("breakdown", {}).get("catalyst", {}) or {}).get("raw"))
    event = ((stock.get("breakdown", {}).get("catalyst", {}) or {}).get("metrics") or {}).get("event")
    sq = _f((stock.get("short_squeeze") or {}).get("score"))
    vd = stock.get("vol_delta") or {}

    score = _capability(atr_pct)
    reasons = [f"{atr_pct:.1f}%/day range"]
    trigger_px = None

    if coiled.get("state") in ("COILED", "BREAKING") or _f(coiled.get("pivot_prox")) >= 0.9:
        score += 15
        pivot = coiled.get("pivot_price")
        if pivot and px < _f(pivot):
            trigger_px = _f(pivot)
            reasons.append(f"coiled, pivot {trigger_px}")
        else:
            reasons.append("coiled at pivot")
    if cat >= 60:
        score += 10
        reasons.append(f"catalyst {cat:.0f}")
    if event == 90:
        score += 10
        reasons.append("fresh positive news")
    if sq >= 60:
        score += 10
        reasons.append(f"squeeze {sq:.0f}")
    if stock.get("feed_hint"):
        score += 8
        reasons.append(stock["feed_hint"].replace("gnw_", "").replace("prn_", "") + " feed")
    if vd.get("state") == "ACCUMULATION":
        score += 5
        reasons.append("flow+")

    return {
        "ticker": stock.get("ticker"), "score": round(min(100.0, score)),
        "atr_pct": round(atr_pct, 1), "prev_close": px,
        "trigger_px": trigger_px, "reasons": reasons[:4],
        "grade": v.get("grade"),
    }


def build_watchlist(ranked: list) -> list:
    """Top day-move candidates from a scan's ranked list."""
    out = []
    for s in ranked:
        try:
            m = score_one(s)
        except Exception:
            continue
        if m and m["score"] >= MIN_SCORE:
            out.append(m)
    out.sort(key=lambda m: -m["score"])
    return out[:MAX_MOVERS]
