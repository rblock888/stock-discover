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
    """Format a stock for telegram message."""
    ticker = stock.get("ticker", "?")
    price = stock.get("quote", {}).get("price", 0) if stock.get("quote") else 0
    change = stock.get("quote", {}).get("change_pct", 0) if stock.get("quote") else 0
    name = stock.get("quote", {}).get("name", ticker) if stock.get("quote") else ticker
    composite = stock.get("composite", 0)
    ml_score = stock.get("ml_score", 0)
    early = stock.get("early_detection", {}).get("score", 0) if stock.get("early_detection") else 0
    breakout = stock.get("breakout", {})

    lines = [f"*${ticker}* — {name}"]
    if price:
        change_str = f" ({change:+.1f}%)" if change else ""
        lines.append(f"💵 ${price:.2f}{change_str}")
    lines.append(f"📊 Score *{composite:.0f}*  · AI *{ml_score:.0f}*  · Early *{early:.0f}*")

    if breakout and breakout.get("score", 0) > 50:
        lines.append(f"🎯 Breakout: *{breakout['score']:.0f}%* prob, +{breakout.get('expected_return_pct', 0):.0f}% exp")

    pattern = stock.get("pattern_match", {})
    if pattern and pattern.get("best_match"):
        match = pattern.get("matches", [{}])[0]
        lines.append(f"🔮 Like {pattern['best_match']} (+{match.get('move_pct')}%)")

    return "\n".join(lines)


def alert_new_pick(stock: dict, alert_type: str = "ai_pick") -> bool:
    """Send alert for a new top pick or multi-signal alert."""
    ticker = stock.get("ticker")
    if not ticker:
        return False

    # Skip if already sent recently
    if db.alert_already_sent(ticker, alert_type, within_hours=24):
        return False

    if alert_type == "new_alert":
        header = "🚨 *NEW MULTI-SIGNAL ALERT*"
    elif alert_type == "ai_pick":
        header = "✨ *NEW AI TOP PICK*"
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

    ai_set = set(ai_picks or [])

    # Alert top 3 AI picks
    for stock in ranked_stocks[:5]:
        if stock.get("multi_signal_alert"):
            alert_new_pick(stock, "new_alert")
        elif stock.get("ticker") in ai_set and stock.get("ml_score", 0) >= 65:
            alert_new_pick(stock, "ai_pick")

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
