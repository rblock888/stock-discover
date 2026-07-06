"""
Push-notification alerts — sends opportunities to Pushover and/or Telegram.

Setup (use either or both; alerts go to every configured channel):

  Pushover (https://pushover.net):
    1. Install the Pushover app, copy your USER KEY from the dashboard
    2. Create an Application/API token (one-time) for "Stock Discovery"
    3. Set env vars: PUSHOVER_USER, PUSHOVER_TOKEN

  Telegram:
    1. Create a bot via @BotFather, get the token
    2. Message the bot, find your chat_id via getUpdates
    3. Set env vars: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

Alert types: new_alert, high_conviction, coiled, breakout, improving, watchlist.
"""

import os
import re
import requests
import db

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
PUSHOVER_TOKEN = os.environ.get("PUSHOVER_TOKEN", "")
PUSHOVER_USER = os.environ.get("PUSHOVER_USER", "")


def _telegram_configured() -> bool:
    return bool(BOT_TOKEN and CHAT_ID)


def _pushover_configured() -> bool:
    return bool(PUSHOVER_TOKEN and PUSHOVER_USER)


def is_configured() -> bool:
    return _telegram_configured() or _pushover_configured()


def _md_to_html(text: str) -> str:
    """Telegram *bold* / _italic_ → Pushover-supported HTML."""
    text = re.sub(r"\*(.+?)\*", r"<b>\1</b>", text)
    text = re.sub(r"_(.+?)_", r"<i>\1</i>", text)
    return text


def _send(text: str, title: str = None, parse_mode: str = "Markdown") -> bool:
    """Send to every configured channel. Returns True if any delivery succeeded."""
    if title is None:
        # derive a title from the first line (strip markdown + emoji-free is fine)
        first = text.split("\n", 1)[0]
        title = re.sub(r"[*_]", "", first).strip()[:250] or "Stock Discovery"
    sent = False

    if _pushover_configured():
        try:
            # message body = everything after the first line (title carries the header)
            body = text.split("\n", 1)[1].strip() if "\n" in text else text
            resp = requests.post(
                "https://api.pushover.net/1/messages.json",
                data={
                    "token": PUSHOVER_TOKEN, "user": PUSHOVER_USER,
                    "title": title, "message": _md_to_html(body)[:1024], "html": 1,
                },
                timeout=10,
            )
            sent = sent or resp.status_code == 200
        except Exception:
            pass

    if _telegram_configured():
        try:
            resp = requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={"chat_id": CHAT_ID, "text": text, "parse_mode": parse_mode,
                      "disable_web_page_preview": True},
                timeout=10,
            )
            sent = sent or resp.status_code == 200
        except Exception:
            pass

    return sent


def _format_stock(stock: dict) -> str:
    """Format a stock for telegram — honest, measured signals only (matches UI)."""
    ticker = stock.get("ticker", "?")
    q = stock.get("quote") or {}
    price = q.get("price", 0)
    change = q.get("change_pct", 0)
    name = q.get("name", ticker)
    composite = stock.get("composite", 0)
    cpw = stock.get("calibrated_p_win")
    edge = stock.get("edge") or {}
    tilt = stock.get("tilt") or {}
    sq = stock.get("short_squeeze") or {}

    lines = [f"*${ticker}* — {name}"]
    if price:
        change_str = f" ({change:+.1f}%)" if change else ""
        lines.append(f"💵 ${price:.2f}{change_str}")

    # Composite + the MEASURED win-rate (calibrated), not the fabricated "AI %"
    score_line = f"📊 Composite *{composite:.0f}*"
    if cpw is not None:
        score_line += f"  · Measured P(+5% in 5d) *{cpw * 100:.0f}%*"
    lines.append(score_line)

    # Plain-language regime gauges
    flow = (edge.get("flow") or {}).get("state")
    bearing = (edge.get("bearing") or {}).get("state")
    pulse = (edge.get("pulse") or {}).get("state")
    if flow and bearing and pulse:
        lines.append(f"⚙️ {bearing} · {flow} flow · {pulse} vol")

    # Regime tilt (why it ranks where it does)
    factor = tilt.get("factor", 1.0)
    if abs(factor - 1) >= 0.04:
        sign = "+" if factor >= 1 else "−"
        reason = (tilt.get("reasons") or [""])[0].lstrip("+− ")
        lines.append(f"🌐 Regime {sign}{abs((factor - 1) * 100):.0f}%{f' ({reason})' if reason else ''}")

    if (sq.get("score") or 0) >= 60:
        lines.append(f"🔥 Squeeze {sq['score']:.0f} · {sq.get('short_pct_float', 0):.0f}% SI · {sq.get('days_to_cover', 0):.0f}d cover")

    return "\n".join(lines)


def _is_high_conviction(stock: dict) -> bool:
    """Alert-worthy = MEASURED conviction in a supportive regime.

    Gates on the calibrated hit-rate (or top-tier composite before calibration
    is ready), and refuses downtrends / thin tape. Deliberately does NOT use
    ml_score — it has no measured edge.
    """
    edge = stock.get("edge") or {}
    bearing = (edge.get("bearing") or {}).get("state")
    flow = (edge.get("flow") or {}).get("state")
    if bearing in ("DOWN", "CHOPPY DOWN") or flow == "THIN":
        return False
    if (stock.get("tilt") or {}).get("factor", 1.0) < 1.0:
        return False  # regime is leaning against it

    cpw = stock.get("calibrated_p_win")
    if cpw is not None:
        try:
            import evaluation
            gate = evaluation.cpw_gate(5)   # base rate + real margin, re-derives live
        except Exception:
            gate = 0.30
        return cpw >= gate
    # fallback until calibration is ready: the graded verdict + the one bucket
    # with measured positive IC — NOT the noise composite (IC +0.016)
    grade = (stock.get("setup") or {}).get("grade")
    cat = ((stock.get("breakdown") or {}).get("catalyst") or {}).get("raw") or 0
    return grade in ("A", "B") and cat >= 60


def alert_new_pick(stock: dict, alert_type: str = "ai_pick") -> bool:
    """Send alert for a new top pick or multi-signal alert."""
    ticker = stock.get("ticker")
    if not ticker:
        return False

    # Skip if already sent recently
    if db.alert_already_sent(ticker, alert_type, within_hours=24):
        return False

    if alert_type == "new_alert":
        header = "🚨 *MULTI-SIGNAL ALERT*"
    elif alert_type == "high_conviction":
        header = "🎯 *HIGH-CONVICTION SETUP*"
    elif alert_type == "improving":
        header = "📈 *SCORE IMPROVING*"
    else:
        header = "📌 *NEW PICK*"

    body = f"{header}\n\n{_format_stock(stock)}"
    if _send(body):
        db.log_alert(ticker, alert_type, {"composite": stock.get("composite")})
        return True
    return False


def alert_coiled(stock: dict, kind: str, bypass: bool = False) -> bool:
    """Alert on a fresh pre-breakout setup: a loaded coil or a breakout trigger.
    `bypass` tags alerts sent past the normal 3-slot cap (hot-catalyst A/B rule)
    so their forward returns can be scored separately — kill-switch at n>=30 if
    their 10d win-rate trails the baseline."""
    ticker = stock.get("ticker")
    if not ticker:
        return False
    if db.alert_already_sent(ticker, kind, within_hours=48):  # tell us once, not every scan
        return False

    c = stock.get("coiled") or {}
    header = "🚀 *BREAKOUT TRIGGER*" if kind == "breakout" else "🌱 *COILED SPRING LOADED*"
    detail = f"\n⊟ {c.get('state')} {c.get('coiled_score', 0):.0f}/100"
    reasons = c.get("reasons") or []
    if reasons:
        detail += " · " + " · ".join(reasons[:2])

    body = f"{header}\n\n{_format_stock(stock)}{detail}"
    if _send(body):
        db.log_alert(ticker, kind, {"coiled_score": c.get("coiled_score"), "bypass": bypass,
                                    "catalyst": ((stock.get("breakdown") or {}).get("catalyst") or {}).get("raw")})
        return True
    return False


def _premarket_gaps(tickers: list, threshold_pct: float = 3.0) -> dict:
    """{ticker: gap_pct} for names moving >=3% in PRE-MARKET vs previous close.

    yfinance serves preMarketPrice free during 04:00-09:30 ET — exactly the
    window the 08:45 brief runs in. A plan priced off yesterday's close is
    STALE on a gapping name; flag it rather than let the entry mislead.
    Fail-open: outside pre-market (or on fetch failure) returns {}."""
    gaps = {}
    try:
        import yfinance as yf
        for t in tickers[:10]:
            try:
                info = yf.Ticker(t).info or {}
                pre, prev = info.get("preMarketPrice"), info.get("previousClose")
                if pre and prev:
                    gap = (float(pre) / float(prev) - 1) * 100
                    if abs(gap) >= threshold_pct:
                        gaps[t] = round(gap, 1)
            except Exception:
                continue
    except Exception:
        pass
    return gaps


def format_preopen_brief(ranked: list, regime_label: str = None,
                         open_trades: list = None, day: str = None,
                         macro_line: str = None, events: list = None,
                         gaps: dict = None, movers: list = None) -> str | None:
    """The best-of list before the New York open — compact enough for a phone.

    Top actionable setups (A/B with plans), then the strongest WATCH names
    (forming, pre-trigger), event-risk flags, and the paper-ledger book.
    Returns None when there's genuinely nothing worth waking up for."""
    graded = [s for s in ranked if (s.get("setup") or {}).get("grade") in ("A", "B")]
    watches = [s for s in ranked if (s.get("setup") or {}).get("grade") == "WATCH"]
    movers = movers or []
    if not graded and not watches and not movers:
        return None

    lines = [f"🔔 *PRE-OPEN BRIEF*{' — ' + day if day else ''}", ""]
    if regime_label:
        lines.append(f"🌡 {regime_label} · {len(graded)} actionable · {len(watches)} forming")
    if macro_line:
        lines.append(f"🌍 {macro_line}")
    # high-impact events TODAY — the books' rule: don't trade the news
    for e in (events or []):
        if e.get("days_away") == 0:
            lines.append(f"📅 *{e['name']} today {e['time_et']} ET* — expect chop, size down")
    if regime_label or macro_line or events:
        lines.append("")

    gaps = gaps or {}
    if movers:
        lines.append("🚀 *MOVERS WATCH* — 5-10% day potential")
        for m in movers:
            why = " · ".join(m["reasons"])
            trig = f" · watch >{m['trigger_px']}" if m.get("trigger_px") else ""
            gap_note = f" ⚡{gaps[m['ticker']]:+.1f}% pre-mkt" if m["ticker"] in gaps else ""
            lines.append(f"${m['ticker']} {m['score']} — {why}{trig}{gap_note}")
        lines.append("")
    if graded:
        lines.append("🎯 swing setups:")
    for s in graded[:3]:
        v = s["setup"]
        pl = v.get("plan") or {}
        lines.append(f"[{v['grade']}] ${s['ticker']} — {v.get('setup', '')}")
        if pl.get("entry"):
            lines.append(f"   buy {pl['entry']} · stop {pl['stop']} · tgt {pl['target']} ({pl.get('rr', '?')}R)")
        if s["ticker"] in gaps:
            g = gaps[s["ticker"]]
            lines.append(f"   ⚡ gapping {g:+.1f}% pre-market — plan is stale, re-plan at open")
        cau = next((c for c in (v.get("cautions") or []) if "earnings" in c or "dilution" in c), None)
        if cau:
            lines.append(f"   ⚠ {cau[:70]}")
    if watches:
        top_watch = sorted(watches, key=lambda s: -(s["setup"].get("score") or 0))[:3]
        lines.append("👁 watch: " + " · ".join(f"${s['ticker']}" for s in top_watch))
    if open_trades:
        pos = ", ".join(f"${t['ticker']} {t.get('mfe_r') or 0:+.1f}R peak" for t in open_trades[:3])
        lines.append(f"📒 open: {pos}")
    return "\n".join(lines)


def send_preopen_brief(ranked: list, regime_label: str = None, log: bool = True) -> bool:
    """Send the daily pre-open digest (once per day — dedupe via a pseudo-ticker)."""
    if not is_configured() or not ranked:
        return False
    if log and db.alert_already_sent("_DAILY", "preopen_brief", within_hours=12):
        return False
    open_trades = []
    try:
        open_trades = db.get_paper_trades(status="open")
    except Exception:
        pass
    from datetime import datetime as _dt
    macro_line = events = None
    try:
        import macro_bias, econ_calendar
        macro_line = macro_bias.brief_line()
        events = econ_calendar.upcoming(days=1)
    except Exception:
        pass
    movers = []
    try:
        import day_movers
        movers = day_movers.build_watchlist(ranked)
    except Exception:
        pass
    graded_tickers = [s["ticker"] for s in ranked
                      if (s.get("setup") or {}).get("grade") in ("A", "B")]
    gaps = _premarket_gaps([m["ticker"] for m in movers] + graded_tickers
                           + [t["ticker"] for t in open_trades])
    body = format_preopen_brief(ranked, regime_label, open_trades,
                                day=_dt.now().strftime("%b %d"),
                                macro_line=macro_line, events=events, gaps=gaps,
                                movers=movers)
    if body is None:
        # nothing actionable — still tell us once, silence is ambiguous
        body = (f"🔔 *PRE-OPEN BRIEF — {_dt.now().strftime('%b %d')}*\n\n"
                f"No actionable A/B setups this morning ({regime_label or 'regime n/a'}). "
                "The engine found nothing worth chasing — that's a position too.")
    if _send(body):
        if log:
            # movers logged with previous closes so their hit rate ("did it
            # actually touch +5% that day?") is MEASURED — day_movers_scorecard
            db.log_alert("_DAILY", "preopen_brief", {
                "n_ranked": len(ranked),
                "movers": [{"ticker": m["ticker"], "prev_close": m["prev_close"],
                            "score": m["score"]} for m in movers],
            })
        return True
    return False


def alert_intraday_breakout(fired: dict) -> bool:
    """5-minute watcher trigger: a completed intraday bar closed through the
    pivot on real volume. Payload is fully instrumented so its own scorecard
    can kill it (n>=30 with 10d excess <= 0 → watcher disabled)."""
    ticker = fired.get("ticker")
    if not ticker:
        return False
    if db.alert_already_sent(ticker, "intraday_breakout", within_hours=48):
        return False
    body = (
        f"⚡ *INTRADAY BREAKOUT — ${ticker}*\n\n"
        f"5m close *${fired['price']:.2f}* through pivot ${fired['pivot_price']:.2f} "
        f"on *{fired['rvol_prorated']:.1f}x* prorated volume\n"
        f"⊟ coiled {fired.get('coiled_score', 0):.0f}/100 · daily scan confirms on next pass"
    )
    if _send(body):
        db.log_alert(ticker, "intraday_breakout", fired)
        return True
    return False


def alert_watchlist_move(ticker: str, old_price: float, new_price: float, item: dict) -> bool:
    """Alert when a watchlist stock moves significantly."""
    if not item:
        return False

    change_pct = (new_price - old_price) / old_price * 100 if old_price else 0
    if abs(change_pct) < 5:
        return False  # ignore small moves

    direction = "📈" if change_pct > 0 else "📉"
    if db.alert_already_sent(ticker, f"wl_{int(change_pct/5)*5}", within_hours=12):
        return False

    entry = item.get("entry_price")
    pnl = ""
    if entry:
        pnl_pct = (new_price - entry) / entry * 100
        pnl = f"\n💰 P&L: *{pnl_pct:+.1f}%* (entered at ${entry:.2f})"

    body = (
        f"{direction} *${ticker} moved {change_pct:+.1f}%*\n\n"
        f"Now: ${new_price:.2f}{pnl}"
    )
    if _send(body):
        db.log_alert(ticker, f"wl_{int(change_pct/5)*5}", {"price": new_price})
        return True
    return False


def send_test() -> bool:
    """Send a test message."""
    return _send("✅ *Stock Discovery alerts active*\nYou'll receive notifications for new picks and watchlist moves.")


def process_scan_results(ranked_stocks: list, ai_picks: list = None):
    """
    Called after each scan. Sends alerts for new picks and improvements.

    ALERT_MODE "focused" (default): this whole per-scan stream is SILENT — the
    day speaks twice only: the 08:45 ET pre-open brief (movers watchlist) and
    the intraday watcher when a watched name actually breaks. Set "all" in
    config.py to restore the legacy firehose.
    """
    if not is_configured():
        return
    import config as _cfg
    if getattr(_cfg, "ALERT_MODE", "focused") == "focused":
        return

    # Alert measured high-conviction setups from the top of the ranking.
    # (No longer gates on ml_score — it has no measured edge.)
    for stock in ranked_stocks[:8]:
        if not _is_high_conviction(stock):
            continue
        atype = "new_alert" if stock.get("multi_signal_alert") else "high_conviction"
        alert_new_pick(stock, atype)

    # Pre-breakout setups across the whole ranking — catch them before/at launch.
    # FRESH names only (a name alerted <48h ago used to consume a [:3] slot for
    # days, silently starving new triggers — the measured binding defect), sorted
    # by catalyst (the one bucket with measured IC), not composite order.
    def _cat(s):
        return ((s.get("breakdown") or {}).get("catalyst") or {}).get("raw") or 0

    def _fresh(state, kind):
        lst = [s for s in ranked_stocks
               if (s.get("coiled") or {}).get("state") == state
               and not db.alert_already_sent(s.get("ticker", ""), kind, within_hours=48)]
        lst.sort(key=_cat, reverse=True)
        return lst

    breaking = _fresh("BREAKING", "breakout")
    sent_breakouts = 0
    for stock in breaking[:3]:
        if alert_coiled(stock, "breakout"):
            sent_breakouts += 1
    # bypass beyond the 3 slots ONLY for the strongest confluence: hot catalyst
    # (>=70 — 60 is the median, not a bar), graded A/B, and a real-R:R plan.
    for stock in breaking[3:]:
        if sent_breakouts >= 5:   # hard cap per scan
            break
        v = stock.get("setup") or {}
        rr = (v.get("plan") or {}).get("rr") or 0
        if _cat(stock) >= 70 and v.get("grade") in ("A", "B") and rr >= 1.5:
            if alert_coiled(stock, "breakout", bypass=True):
                sent_breakouts += 1
    for stock in _fresh("COILED", "coiled")[:3]:
        alert_coiled(stock, "coiled")

    # Check watchlist for big moves
    watchlist = db.get_watchlist()
    if not watchlist:
        return

    for item in watchlist:
        ticker = item["ticker"]
        # Find latest price from scan
        match = next((s for s in ranked_stocks if s.get("ticker") == ticker), None)
        if not match or not match.get("quote"):
            continue
        current_price = match["quote"].get("price", 0)
        if not current_price:
            continue

        # Compare to last snapshot
        snaps = db.get_snapshots(ticker)
        if len(snaps) < 2:
            continue
        old_price = snaps[1].get("price", 0)  # snaps[0] is current scan
        if old_price:
            alert_watchlist_move(ticker, old_price, current_price, item)
