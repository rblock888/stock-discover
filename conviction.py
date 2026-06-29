"""Conviction synthesis — the single answer: is this a good pick, and why?

Collapses every signal (the early-upside detectors, regime, calibrated win-rate,
fundamentals, squeeze) into ONE opinionated verdict per stock:

  grade   A / B / C / AVOID / —     (— = no clear setup)
  setup   the reason it's interesting (Spring reclaim, Demand-zone retest,
          Breakout, Coiled spring, Accumulation base, ...)
  thesis  one plain-language line
  action  what to actually do (entry / stop hint)

Priority is given to the EARLY-upside setups (catch it before it flies) and to
MEASURED signals (calibrated win-rate). It's a transparent rule-based synthesis,
not a black box — every grade shows its positives and cautions.
"""


def _f(x, d=0.0):
    try:
        v = float(x)
        return v if v == v else d  # NaN guard
    except (TypeError, ValueError):
        return d


def assess(stock: dict, regime: dict | None = None) -> dict:
    coiled = stock.get("coiled") or {}
    smad = stock.get("smad") or {}
    edge = stock.get("edge") or {}
    bearing = (edge.get("bearing") or {}).get("state")
    flow = (edge.get("flow") or {}).get("state")
    composite = _f(stock.get("composite"))
    cpw = stock.get("calibrated_p_win")
    tilt = _f((stock.get("tilt") or {}).get("factor"), 1.0)
    q = stock.get("quote") or {}
    mcap = _f(q.get("market_cap"))
    fund = _f((stock.get("breakdown", {}).get("fundamentals", {}) or {}).get("raw"))
    sq = stock.get("short_squeeze") or {}
    comp = stock.get("competitors") or {}

    cstate = coiled.get("state")
    sstate = smad.get("state")
    zone = smad.get("demand_zone")

    # ── Hard AVOID conditions ──
    avoid = []
    if sstate == "BULL TRAP":
        avoid.append("fakeout — effort without result")
    if cstate == "EXTENDED":
        avoid.append(f"already extended +{_f(coiled.get('ret_3m_pct')):.0f}% in 3m")
    if bearing == "DOWN":
        avoid.append("downtrend")
    if flow == "THIN" and sstate not in ("SPRING", "DEMAND RETEST"):
        avoid.append("thin liquidity")

    # ── Primary setup (priority: earliest / highest-odds first) ──
    setup, base, action = None, 0.0, None
    if sstate == "SPRING":
        setup, base = "Spring reclaim", _f(smad.get("smad_score"), 60)
        action = "Long the reclaim; stop below the sweep low"
    elif sstate == "DEMAND RETEST":
        setup, base = "Demand-zone retest", _f(smad.get("smad_score"), 60)
        action = (f"Buy the retest into ${zone[0]}–${zone[1]}, stop below ${zone[0]}"
                  if zone else "Buy the zone retest; tight stop below the zone")
    elif cstate == "BREAKING":
        setup, base = "Breakout", _f(coiled.get("coiled_score"), 60)
        action = "Entry on the break or first shallow pullback"
    elif sstate == "BOS IMPULSE":
        setup, base = "Breakout (structure)", max(_f(smad.get("smad_score")), 50)
        action = "Long the impulse / first pullback to the demand zone"
    elif cstate == "COILED":
        setup, base = "Coiled spring", _f(coiled.get("coiled_score"), 60)
        action = "Watch for a volume break of the base pivot"
    elif cstate == "BASING" or sstate == "ACCUMULATION":
        setup, base = "Accumulation base", max(_f(coiled.get("coiled_score")), _f(smad.get("smad_score")), 45)
        action = "On watch — wait for the spring or the break"
    elif composite >= 62 and comp.get("lagging") and _f(comp.get("gap_3m")) > 20:
        setup, base = "Lagging catch-up", composite * 0.7
        action = "Sector ran, this lagged — catch-up candidate"

    if avoid:
        return {
            "grade": "AVOID", "score": round(min(base or composite, 30)),
            "setup": setup or "—", "thesis": "Avoid — " + ", ".join(avoid[:2]),
            "action": "Skip / wait for a cleaner setup", "positives": [], "cautions": avoid,
        }

    if not setup:
        return {
            "grade": "—", "score": round(min(composite, 40)), "setup": "—",
            "thesis": "No clear early-upside setup", "action": None,
            "positives": [], "cautions": [],
        }

    # ── Conviction adjustments ──
    score = base
    pos, cau = [], []
    mood = (regime.get("mood") or {}).get("label") if regime and regime.get("available") else None

    if tilt >= 1.08:
        score += 6; pos.append("regime tailwind")
    elif tilt <= 0.95:
        score -= 8; cau.append("regime leaning against")
    if mood == "RISK-ON":
        score += 3
    elif mood == "RISK-OFF":
        score -= 6; cau.append("risk-off tape")

    if cpw is not None:
        if cpw >= 0.35:
            score += 8; pos.append(f"{cpw * 100:.0f}% measured win-rate")
        elif cpw < 0.18:
            score -= 6; cau.append("low measured win-rate")

    if fund >= 70:
        score += 5; pos.append(f"fundamentals {fund:.0f}")
    if composite >= 65:
        score += 3
    if _f(sq.get("score")) >= 65:
        score += 4; pos.append(f"squeeze {_f(sq.get('score')):.0f}")
    if 0 < mcap < 2e9 and mood == "RISK-ON":
        score += 2  # small-cap in a risk-on tape

    score = max(0.0, min(100.0, score))
    grade = "A" if score >= 75 else ("B" if score >= 60 else "C")

    bits = [setup]
    # lead the thesis with the most INFORMATIVE positive (measured win / fundamentals
    # / squeeze) over the generic "regime tailwind"
    lead = next((p for p in pos if "regime" not in p), pos[0] if pos else None)
    if lead:
        bits.append(lead)
    if mood:
        bits.append(mood.lower().replace("-", " ") + " tape")
    thesis = " · ".join(bits)
    if cau:
        thesis += " — " + cau[0]

    return {
        "grade": grade, "score": round(score), "setup": setup,
        "thesis": thesis, "action": action, "positives": pos, "cautions": cau,
    }
