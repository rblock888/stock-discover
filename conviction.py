"""Conviction synthesis — the single answer: is this a good pick, and why?

This is the books' **Trade Confluence Checklist** ("4+ checks = high-confluence
setup"), adapted to a daily-bar US-stock scanner. It does NOT invent a new score;
it counts how many independent factors line up across THREE groups —

  TECHNICAL    the price-action setup (demand zone, reclaim, reversal, phase,
               trend, volume, compression)            ← Supply & Demand Mastery
  FUNDAMENTAL  company quality / fuel (fundamentals, catalyst, insiders,
               squeeze, sentiment)                     ← the equity adaptation
  CONTEXT      regime tailwind, liquidity, measured win-rate

— and grades by CONFLUENCE. The rule the books insist on (and the owner's point):
a top-grade pick needs BOTH a clean technical setup AND fundamentals behind it,
not one without the other. A grade is only as good as the trade plan under it, so
each verdict carries a concrete entry / stop / target / R:R.
"""

# Bump when the grading RULES change, so grade_scorecard never pools grades
# minted under different regimes of logic. v2 (2026-07-02): sentiment moved out
# of the counted fundamental group (measured IC -0.19 — the strongest anti-
# signal we have was literally incrementing the A-gate), and grade A now
# requires a live catalyst (>=60) or squeeze fuel (>=60) — the only measured
# positive drivers. Funnel check: if <2 A-grades/week over 3 weeks, loosen the
# catalyst clause to >=55 before touching anything else.
GRADE_VERSION = 2


def _f(x, d=0.0):
    try:
        v = float(x)
        return v if v == v else d
    except (TypeError, ValueError):
        return d


def _raw(stock, bucket):
    return _f((stock.get("breakdown", {}).get(bucket, {}) or {}).get("raw"))


def assess(stock: dict, regime: dict | None = None, setup_stats: dict | None = None) -> dict:
    coiled = stock.get("coiled") or {}
    smad = stock.get("smad") or {}
    edge = stock.get("edge") or {}
    book = stock.get("book") or {}
    bearing = (edge.get("bearing") or {}).get("state")
    flow = (edge.get("flow") or {}).get("state")
    above20 = bool(edge.get("above_20ma"))
    composite = _f(stock.get("composite"))
    cpw = stock.get("calibrated_p_win")
    tilt = _f((stock.get("tilt") or {}).get("factor"), 1.0)
    q = stock.get("quote") or {}
    mcap = _f(q.get("market_cap"))
    sq = _f((stock.get("short_squeeze") or {}).get("score"))
    comp = stock.get("competitors") or {}
    mood = (regime.get("mood") or {}).get("label") if regime and regime.get("available") else None

    cstate = coiled.get("state")
    sstate = smad.get("state")
    zone = smad.get("demand_zone")
    phase = (book.get("phase") or {}).get("state")
    rbs = book.get("rbs") or {}
    rev = book.get("reversal") or {}
    prof = book.get("profile") or {}
    ema = book.get("ema") or {}
    dbl = book.get("double_bottom") or {}
    rhs = book.get("reverse_hns") or {}
    plan = book.get("plan")

    fund, cat, ins, sent = _raw(stock, "fundamentals"), _raw(stock, "catalyst"), _raw(stock, "insider"), _raw(stock, "sentiment")

    # ── Primary setup (priority: earliest / highest-odds first) ──
    setup, base_action = None, None
    if sstate == "SPRING":
        setup, base_action = "Spring reclaim", "Long the reclaim; stop below the sweep low"
    elif sstate == "DEMAND RETEST":
        setup, base_action = "Demand-zone retest", "Buy the zone retest; stop below the zone"
    elif cstate == "BREAKING":
        setup, base_action = "Breakout", "Entry on the break / first pullback"
    elif sstate == "BOS IMPULSE":
        setup, base_action = "Breakout (structure)", "Long the impulse / pullback to the zone"
    elif rhs.get("confirmed") and phase != "MARKUP":
        setup, base_action = "Reverse H&S", "Long the neckline break; stop below the right shoulder"
    elif dbl.get("confirmed") and phase != "MARKUP":
        setup, base_action = "Double bottom", "Long the neckline break; stop below the second low"
    elif rbs.get("active"):
        setup, base_action = "Reclaimed-level (RBS)", "Buy the held retest; stop below the level"
    elif (dbl.get("active") or rhs.get("active")) and phase != "MARKUP" \
            and _f((book.get("context") or {}).get("ret_60d")) < 15:
        # a genuine pre-confirm bottom hasn't already rallied — a pattern whose
        # neckline broke weeks ago and is now +20%/60d isn't "pre-confirm", it's stale
        setup, base_action = "Bottoming (pre-confirm)", "On watch — needs the neckline break"
    elif cstate == "COILED":
        setup, base_action = "Coiled spring", "Watch for a volume break of the base pivot"
    elif (cstate == "BASING" or sstate == "ACCUMULATION" or phase == "ACCUMULATION") \
            and phase != "MARKUP" and prof.get("position") != "above" \
            and _f((book.get("context") or {}).get("ret_20d")) < 15:
        # a real base is quiet & sideways — not a name already +15%/20d into new highs
        setup, base_action = "Accumulation base", "On watch — wait for the spring / break"
    elif composite >= 62 and comp.get("lagging") and _f(comp.get("gap")) > 20:
        setup, base_action = "Lagging catch-up", "Sector ran, this lagged — catch-up candidate"

    # ── Confluence checklist ──
    def fac(label, group, passed, detail=""):
        return {"label": label, "group": group, "passed": bool(passed), "detail": detail}

    factors = [
        # TECHNICAL
        fac("Setup present", "technical", bool(setup), setup or "no setup"),
        fac("Fresh demand zone", "technical", bool(zone) and sstate in ("DEMAND RETEST", "BOS IMPULSE", "SPRING"),
            f"${zone[0]}–${zone[1]}" if zone else ""),
        fac("Reclaimed support (RBS)", "technical", rbs.get("active"), rbs.get("detail", "")),
        fac("Reversal candle", "technical", rev.get("bullish") and rev.get("at_low"), rev.get("name", "")),
        fac("Accepted in value", "technical", prof.get("position") in ("inside", "above"),
            f"price {prof.get('position')} value" if prof else ""),
        fac("Phase: accumulation/markup", "technical", phase in ("ACCUMULATION", "MARKUP"),
            (book.get("phase") or {}).get("detail", "")),
        fac("Double bottom / rev H&S", "technical", dbl.get("active") or rhs.get("active"),
            "double bottom" if dbl.get("active") else ("reverse H&S" if rhs.get("active") else "")),
        fac("EMA stack bullish", "technical", ema.get("stack_bullish") or ema.get("reclaim"),
            "20>50>200" if ema.get("stack_bullish") else ("reclaimed 50EMA" if ema.get("reclaim") else "")),
        fac("Trend up (not down)", "technical", above20 and bearing not in ("DOWN", "CHOPPY DOWN"), bearing or ""),
        fac("Volume confirms", "technical", flow in ("HEALTHY", "CROWDED") or cstate == "BREAKING", flow or ""),
        # FUNDAMENTAL
        fac("Strong fundamentals", "fundamental", fund >= 60, f"{fund:.0f}/100"),
        fac("Catalyst", "fundamental", cat >= 60, f"{cat:.0f}/100"),
        fac("Insider / ownership", "fundamental", ins >= 55, f"{ins:.0f}/100"),
        fac("Squeeze fuel", "fundamental", sq >= 60, f"{sq:.0f}/100"),
        # sentiment measured at IC -0.19 (the strongest ANTI-signal) — shown on the
        # checklist for information but no longer counted toward any grade gate
        fac("Positive sentiment", "info", sent >= 55, f"{sent:.0f}/100"),
        # CONTEXT
        fac("Regime tailwind", "context", tilt >= 1.05 or mood == "RISK-ON", mood or f"tilt {tilt:.2f}"),
        fac("Liquidity OK", "context", flow != "THIN", flow or ""),
        fac("Measured win-rate", "context", cpw is not None and cpw >= 0.30, f"{cpw*100:.0f}%" if cpw is not None else ""),
    ]
    n_tech = sum(1 for f in factors if f["group"] == "technical" and f["passed"])
    n_fund = sum(1 for f in factors if f["group"] == "fundamental" and f["passed"])
    n_ctx = sum(1 for f in factors if f["group"] == "context" and f["passed"])
    total = n_tech + n_fund + n_ctx

    # ── Hard AVOID vetoes ──
    avoid = []
    if sstate == "BULL TRAP":
        avoid.append("fakeout — effort without result")
    if cstate == "EXTENDED":
        avoid.append(f"already extended +{_f(coiled.get('ret_3m_pct')):.0f}% in 3m")
    if bearing == "DOWN" or phase == "MARKDOWN":
        avoid.append("downtrend / markdown")
    if phase == "DISTRIBUTION":
        avoid.append("distribution — supply overhead")
    if flow == "THIN" and sstate not in ("SPRING", "DEMAND RETEST"):
        avoid.append("thin liquidity")

    confluence = {"technical": n_tech, "fundamental": n_fund, "context": n_ctx, "total": total, "factors": factors}
    score = min(100.0, 30 + 7 * n_tech + 8 * n_fund + 6 * n_ctx)

    if avoid:
        return {
            "grade": "AVOID", "score": round(min(score, 30)), "setup": "—",
            "thesis": "Avoid — " + ", ".join(avoid[:2]), "action": "Skip / wait for a cleaner setup",
            "confluence": confluence, "plan": None, "positives": [], "cautions": avoid,
        }
    if not setup:
        return {
            "grade": "—", "score": round(min(score, 40)), "setup": "—",
            "thesis": "No clear early-upside setup", "action": None,
            "confluence": confluence, "plan": None, "positives": [], "cautions": [],
        }

    # ── Grade by CONFLUENCE — A demands BOTH technical AND fundamental alignment,
    # AND an actionable plan with real reward-for-risk (the books' R:R rule). A
    # watch-only setup (no tight entry) tops out at B no matter how it scores. ──
    rr = _f(plan.get("rr")) if plan else None
    actionable = bool(plan) and rr >= 1.8
    # A additionally requires a LIVE driver: catalyst >=60 (the only bucket with
    # measured positive IC, +0.24) or squeeze fuel >=60 (coverage-independent —
    # a hard catalyst-only gate would exclude uncovered biotech/photonics names
    # whose yfinance catalyst score caps at 44 with no analyst coverage).
    if actionable and n_tech >= 3 and n_fund >= 2 and (cat >= 60 or sq >= 60) and n_ctx >= 1:
        grade = "A"
    elif n_tech >= 2 and n_fund >= 1:
        grade = "B"
    else:
        grade = "C"

    cautions = []

    # ── Earnings proximity (caution only — the hard gate ships once its kill
    # criterion has data): a binary event inside the trade's horizon ──
    cat_metrics = (stock.get("breakdown", {}).get("catalyst", {}) or {}).get("metrics") or {}
    earnings_days = cat_metrics.get("earnings_days")
    if cat >= 60 and earnings_days is not None and 0 <= earnings_days <= 14:
        cautions.append(f"earnings within {earnings_days}d — binary event risk")

    # ── R:R floor (audit): a plan that pays under 1.5R can't be an actionable buy ──
    if plan and rr < 1.5:
        cautions.append(f"thin reward-for-risk ({rr:.2f}R)")
        grade = "C"
        score = min(score, 50)

    # ── Falling-knife guard (audit): a sharp bounce that's still deep below the 1y
    # high is counter-trend risk, not a base breakout — keep it visible but demote ──
    poh = _f((book.get("context") or {}).get("pct_off_high"))
    if poh <= -50:
        cautions.append(f"deep drawdown {poh:.0f}% off 1y high — falling-knife risk")
        if grade in ("A", "B"):
            grade = "C"
    elif poh <= -30:
        cautions.append(f"{poh:.0f}% below 1y high — bounce risk, not a clean base")
        if grade == "A":   # a local markup deep below the 1y high is still counter-trend
            grade = "B"

    # ── Extended-into-supply (audit): a +25%/month run that's still under the prior
    # distribution range (not a clean-air high) is a chase — dock it ──
    ctx = book.get("context") or {}
    ret20 = _f(ctx.get("ret_20d"))
    if ret20 >= 25 and poh <= -12:
        cautions.append(f"extended +{ret20:.0f}%/20d into overhead supply — chase risk")
        score = max(0.0, score - 18)
        if grade in ("A", "B"):
            grade = "C"

    # ── Phase/SMAD conflict (audit): book.phase and smad.state are computed
    # independently and can disagree (phase=MARKUP while smad=ACCUMULATION) —
    # that's the detector contradicting itself, not a clean read. Cap conviction
    # rather than silently trusting whichever branch happened to fire the setup ──
    if phase == "MARKUP" and sstate == "ACCUMULATION":
        cautions.append("phase/SMAD conflict — MARKUP vs ACCUMULATION read")
        if grade == "A":
            grade = "B"

    # ── No actionable plan (audit): a real setup with no defined entry/stop is a
    # WATCH item (a forming base / pre-trigger), NOT a tradeable A/B/C buy ──
    if not plan:
        grade = "WATCH"
        score = min(score, 50)

    # ── Close the loop: demote setups the HISTORICAL backtest says don't work ──
    stat = (setup_stats or {}).get(setup)
    if stat and stat.get("n", 0) >= 30:
        ar = _f(stat.get("avg_r"))
        if ar < -0.05:
            cautions.append(f"weak measured edge ({ar:+.2f}R, n={stat['n']})")
            grade = {"A": "B", "B": "C", "C": "C"}.get(grade, grade)
        elif ar >= 0.20:
            cautions.append(f"strong measured edge ({ar:+.2f}R, {stat.get('win_rate')}% win)")

    # thesis: setup + confluence + the most informative passing factor
    lead = next((f for f in factors if f["passed"] and f["group"] == "fundamental"), None) \
        or next((f for f in factors if f["passed"] and f["label"] not in ("Setup present", "Regime tailwind")), None)
    bits = [setup, f"{n_tech}T·{n_fund}F confluence"]
    if lead:
        bits.append(f"{lead['label'].lower()} {lead['detail']}".strip())
    if mood:
        bits.append(mood.lower().replace("-", " ") + " tape")
    thesis = " · ".join(b for b in bits if b)
    if cautions:
        thesis += " — " + cautions[0]

    if plan:
        verb = "Buy pullback to" if plan.get("entry_type") == "pullback" else "Buy"
        action = f"{verb} ${plan['entry']}, stop ${plan['stop']}, target ${plan['target']} ({plan['rr']}R)"
    else:
        action = base_action

    positives = [f"{f['label']} ({f['detail']})" if f["detail"] else f["label"]
                 for f in factors if f["passed"] and f["group"] in ("technical", "fundamental")][:5]

    return {
        "grade": grade, "score": round(score), "setup": setup, "thesis": thesis, "action": action,
        "confluence": confluence, "plan": plan, "positives": positives, "cautions": cautions,
    }
