"""
Telegram alerts module — sends notifications for new opportunities.

Setup:
1. Create a Telegram bot via @BotFather, get token
2. Send any message to your bot
3. Visit https://api.telegram.org/bot<TOKEN>/getUpdates to find your chat_id
4. Set env vars: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

Alert types:
- "new_alert": stock just became multi-signal alert
- "ai_pick": new AI top pick (high ml_score)
- "watchlist_move": watchlist stock moved >5%
- "improving": existing pick scored higher
"""

import os
import requests
import db

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


def is_configured() -> bool:
    return bool(BOT_TOKEN and CHAT_ID)


def _send(text: str, parse_mode: str = "Markdown") -> bool:
    if not is_configured():
        return False
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": text, "parse_mode": parse_mode,
                  "disable_web_page_preview": True},
            timeout=10,
        )
        return resp.status_code == 200
    except Exception:
        return False


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
        score_line += f"  · Measured win *{cpw * 100:.0f}%* (5d)"
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
        return cpw >= 0.30  # measurably above the ~0.22 base rate
    return stock.get("composite", 0) >= 68  # fallback until calibration is ready


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
    """
    if not is_configured():
        return

    # Alert measured high-conviction setups from the top of the ranking.
    # (No longer gates on ml_score — it has no measured edge.)
    for stock in ranked_stocks[:8]:
        if not _is_high_conviction(stock):
            continue
        atype = "new_alert" if stock.get("multi_signal_alert") else "high_conviction"
        alert_new_pick(stock, atype)

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
