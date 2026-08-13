"""Paper-trade ledger v1 — does the plan actually make money at real fills?

Every grade-A/B verdict with an actionable 'now' plan becomes a simulated
position at REAL 30-minute-granularity quotes. This is the only measurement
that includes everything the backtest can't: discovery bias, the veto stack,
entry feasibility (can you even get the plan's price?), and live regime.

Rules (v1 — frozen; management variants come later as TAGGED experiments,
never by editing v1 rows):

  OPEN   fill at the live quote only if it's within 2% of the plan entry AND
         above the stop. A candidate that can't fill stays pending and is
         retried each pass for 3 trading days, then marked 'missed' — the
         missed-fill rate is itself a first-class finding.
  SIZE   fixed $10k book, never compounds: risk 0.75% per trade, max 10% of
         book per position, max 1% of 20-day dollar volume. <1 share = missed.
  MANAGE stop first (exit at QUOTE — captures gap slippage), then target
         (exit AT the target — limit semantics, no gap-up windfall), then a
         20-trading-day time exit at quote. MFE/MAE updated every pass.
  COOL   10 trading days per ticker after any exit; one position per ticker.

Banner for every consumer: paper fills at 30-min granularity are OPTIMISTIC vs
real execution; results are descriptive only below 50 closed trades, and no
config/weights/threshold change may cite ledger data before closed n>=50
overall and n>=20 in the cited cell.
"""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np

import db

logger = logging.getLogger("discovery")

EQUITY = 10_000.0        # fixed book — never compounds (comparability over time)
RISK_PCT = 0.0075        # $75 risk per trade
MAX_POS_PCT = 0.10       # $1,000 max position
ADV_CAP = 0.01           # ≤1% of 20d dollar volume (microcap realism)
FILL_TOL = 0.02          # quote must be within 2% of the plan entry
CANDIDATE_DAYS = 3       # trading days a pending candidate is retried
COOLOFF_DAYS = 10        # trading days per ticker after an exit
MAX_AGE_DAYS = 20        # time exit

ET = ZoneInfo("America/New_York")


def market_open(now=None) -> bool:
    now = now or datetime.now(ET)
    if now.tzinfo is None:
        now = now.replace(tzinfo=ET)
    now = now.astimezone(ET)
    if now.weekday() >= 5:
        return False
    minutes = now.hour * 60 + now.minute
    return 9 * 60 + 30 <= minutes < 16 * 60


def _busdays(a: str, b: str) -> int:
    """Trading days between two ISO timestamps (weekend-only approximation)."""
    try:
        return int(np.busday_count(a[:10], b[:10]))
    except Exception:
        return 0


def size_shares(fill: float, stop: float, adv_dollars: float) -> int:
    """Shares = the BINDING constraint of risk / position cap / liquidity cap."""
    risk_ps = fill - stop
    if risk_ps <= 0 or fill <= 0:
        return 0
    by_risk = EQUITY * RISK_PCT / risk_ps
    by_pos = EQUITY * MAX_POS_PCT / fill
    by_adv = (ADV_CAP * adv_dollars / fill) if adv_dollars and adv_dollars > 0 else by_pos
    return int(min(by_risk, by_pos, by_adv))


def can_fill(quote: float, plan_entry: float, stop: float) -> bool:
    return (quote and plan_entry and quote > stop
            and abs(quote / plan_entry - 1) <= FILL_TOL)


def manage_decision(trade: dict, quote: float, now_iso: str) -> dict | None:
    """Pure exit logic for one open trade at the current quote.
    Returns update fields (or None to hold). Stop FIRST at the QUOTE (gap
    slippage is real); target exits AT the target (limit fill, no windfall);
    then the time exit."""
    stop, target, fill = trade["stop"], trade["target"], trade["fill_price"]
    risk = fill - stop
    if risk <= 0:
        return None
    if quote <= stop:
        exit_price, reason = float(quote), "stop"
    elif quote >= target:
        exit_price, reason = float(target), "target"
    elif _busdays(trade["opened_at"], now_iso) > MAX_AGE_DAYS:
        exit_price, reason = float(quote), "time"
    else:
        return None
    return {
        "status": "closed", "exit_price": round(exit_price, 4),
        "exit_reason": reason, "closed_at": now_iso,
        "r_realised": round((exit_price - fill) / risk, 3),
    }


def _quote_for(ticker: str, ranked_by_ticker: dict) -> float | None:
    """Live-ish quote: prefer this scan's fresh quote, else yfinance fast_info
    (open ledger positions can drop out of the top-40 scan set)."""
    s = ranked_by_ticker.get(ticker)
    if s and (s.get("quote") or {}).get("price"):
        return float(s["quote"]["price"])
    try:
        import yfinance as yf
        q = yf.Ticker(ticker).fast_info.last_price
        return float(q) if q else None
    except Exception:
        return None


def process(ranked_stocks: list, regime_label: str = None) -> dict:
    """One ledger pass — called after each scan. No-op outside market hours."""
    if not market_open():
        return {"skipped": "market closed"}
    now_iso = datetime.now().isoformat()
    by_ticker = {s.get("ticker"): s for s in ranked_stocks if s.get("ticker")}
    report = {"opened": 0, "closed": 0, "missed": 0, "pending": 0, "held": 0}

    # ── 1. MANAGE every open position (even ones out of today's scan set) ──
    for tr in db.get_paper_trades(status="open"):
        quote = _quote_for(tr["ticker"], by_ticker)
        if quote is None:
            continue
        risk = tr["fill_price"] - tr["stop"]
        upd = {"last_quote": round(quote, 4)}
        if risk > 0:
            upd["mfe_r"] = round(max(tr.get("mfe_r") or -9, (quote - tr["fill_price"]) / risk), 3)
            upd["mae_r"] = round(min(tr.get("mae_r") or 9, (quote - tr["fill_price"]) / risk), 3)
        decision = manage_decision(tr, quote, now_iso)
        if decision:
            upd.update(decision)
            report["closed"] += 1
            logger.info(f"paper: closed {tr['ticker']} {decision['exit_reason']} "
                        f"r={decision['r_realised']}")
        else:
            report["held"] += 1
        db.paper_update(tr["id"], **upd)

    # ── 2. RETRY pending candidates; expire stale ones as 'missed' ──
    for tr in db.get_paper_trades(status="pending"):
        quote = _quote_for(tr["ticker"], by_ticker)
        if quote is None:
            continue
        if can_fill(quote, tr["plan_entry"], tr["stop"]):
            s = by_ticker.get(tr["ticker"]) or {}
            q = s.get("quote") or {}
            adv = (q.get("avg_volume") or 0) * quote
            shares = size_shares(quote, tr["stop"], adv)
            if shares >= 1:
                db.paper_update(tr["id"], status="open", fill_price=round(quote, 4),
                                shares=shares, opened_at=now_iso, last_quote=round(quote, 4),
                                mfe_r=0.0, mae_r=0.0)
                report["opened"] += 1
                continue
            db.paper_update(tr["id"], status="missed", last_quote=round(quote, 4),
                            notes="illiquid — sizing below 1 share")
            report["missed"] += 1
            continue
        if _busdays(tr["first_seen"], now_iso) > CANDIDATE_DAYS:
            db.paper_update(tr["id"], status="missed", last_quote=round(quote, 4),
                            notes=f"never fillable within {CANDIDATE_DAYS} trading days")
            report["missed"] += 1
        else:
            report["pending"] += 1

    # ── 3. OPEN new candidates from this scan's A/B verdicts ──
    for s in ranked_stocks:
        ticker = s.get("ticker")
        v = s.get("setup") or {}
        plan = v.get("plan") or {}
        if not ticker or v.get("grade") not in ("A", "B"):
            continue
        if plan.get("entry_type") != "now" or not plan.get("entry") or not plan.get("stop"):
            continue
        existing = db.get_paper_trades(ticker=ticker)
        if any(t["status"] in ("open", "pending") for t in existing):
            continue
        recent_exit = [t for t in existing if t["status"] == "closed" and t.get("closed_at")
                       and _busdays(t["closed_at"], now_iso) < COOLOFF_DAYS]
        if recent_exit:
            continue
        recent_missed = [t for t in existing if t["status"] == "missed" and t.get("first_seen")
                         and _busdays(t["first_seen"], now_iso) < CANDIDATE_DAYS]
        if recent_missed:
            continue

        q = s.get("quote") or {}
        quote = q.get("price")
        row = {
            "ticker": ticker, "setup_type": v.get("setup"), "grade": v.get("grade"),
            "regime_at_open": regime_label,
            "plan_entry": plan["entry"], "stop": plan["stop"], "target": plan.get("target"),
            "first_seen": now_iso, "last_quote": quote,
        }
        if quote and can_fill(float(quote), plan["entry"], plan["stop"]):
            adv = (q.get("avg_volume") or 0) * float(quote)
            shares = size_shares(float(quote), plan["stop"], adv)
            if shares >= 1:
                row.update({"status": "open", "fill_price": round(float(quote), 4),
                            "shares": shares, "opened_at": now_iso, "mfe_r": 0.0, "mae_r": 0.0})
                db.paper_insert(row)
                report["opened"] += 1
                logger.info(f"paper: opened {ticker} {v.get('grade')} {v.get('setup')} "
                            f"@{quote} x{shares}")
                continue
            row.update({"status": "missed", "notes": "illiquid — sizing below 1 share"})
            db.paper_insert(row)
            report["missed"] += 1
            continue
        row["status"] = "pending"   # retried next pass, expires in 3 trading days
        db.paper_insert(row)
        report["pending"] += 1

    return report
