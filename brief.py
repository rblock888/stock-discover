"""Daily brief: a plain-language narrative over scan + regime + watchlist state.

compose() is deterministic template work over already-cached data — it does no
fetching and cannot meaningfully fail. If ANTHROPIC_API_KEY is set (and the
optional `anthropic` package is installed), the headline and paragraph are
rewritten more naturally by claude-haiku-4-5. Bullets ALWAYS stay
template-generated so numbers and tickers cannot be hallucinated; any LLM
problem silently falls back to the template text.
"""

import hashlib
import json
import logging
import os
import re
import time
from datetime import datetime

logger = logging.getLogger("discovery")

LLM_MIN_INTERVAL = 30 * 60  # at most one LLM call per half hour
_llm_memo = {"hash": None, "result": None, "last_call": 0.0}

_LLM_PROMPT = """You are rewriting a stock-scanner's daily brief so it reads naturally.
Rewrite the headline and paragraph below. Keep every number exactly as given.
Do not add facts, tickers, advice, or hedging that is not already present.
Reply with ONLY a JSON object: {{"headline": "...", "paragraph": "..."}}

Facts:
{facts}"""


def compose(regime: dict | None, scan: dict, watchlist: list | None = None,
            squeeze: list | None = None) -> dict:
    """Build the brief from cached state. Pure dict ops; defensive everywhere."""
    regime = regime or {}
    ranked = scan.get("ranked") or []
    new_tickers = scan.get("new_tickers") or []
    improving = scan.get("improving") or []
    decaying = scan.get("decaying") or []
    breadth = scan.get("breadth") or {}
    watchlist = watchlist or []
    squeeze = squeeze or []

    # ── Bullets (priority order, capped at 7) ────────────────────────────────
    bullets = []

    if new_tickers:
        bullets.append({"type": "new", "text": f"New on the radar: {', '.join(new_tickers[:5])}."})

    for item in improving[:2]:
        bullets.append({
            "type": "improving",
            "text": f"{item['ticker']} improving: {item['old_score']:.0f} → {item['new_score']:.0f} ({item['change']:+.0f}).",
        })
    for item in decaying[:2]:
        bullets.append({
            "type": "decaying",
            "text": f"{item['ticker']} fading: {item['old_score']:.0f} → {item['new_score']:.0f} ({item['change']:+.0f}).",
        })

    hot_squeeze = [s for s in squeeze if (s.get("score") or 0) >= 60][:3]
    for s in hot_squeeze:
        bullets.append({
            "type": "squeeze",
            "text": (
                f"Squeeze watch: {s.get('ticker')} ({s.get('score', 0):.0f} — "
                f"{s.get('short_pct_float', 0):.0f}% SI, {s.get('days_to_cover', 0):.0f}d to cover)."
            ),
        })

    top_ml = max(ranked, key=lambda r: r.get("ml_score") or 0, default=None)
    if top_ml and (top_ml.get("ml_score") or 0) >= 50:
        bullets.append({
            "type": "pick",
            "text": f"Model favorite: {top_ml['ticker']} (AI {top_ml['ml_score']:.0f}, composite {top_ml.get('composite', 0):.0f}).",
        })

    # Watchlist proximity — prices matched from the ranked cache (no fetching)
    prices = {r.get("ticker"): (r.get("quote") or {}).get("price") for r in ranked}
    for item in watchlist:
        t = (item.get("ticker") or "").upper()
        price = prices.get(t)
        if not price:
            continue
        stop = item.get("stop_loss")
        target = item.get("target_price")
        if stop and price <= stop:
            bullets.append({"type": "watchlist", "text": f"{t} has breached your stop (${stop:.2f}) — now ${price:.2f}."})
        elif stop and 0 <= (price - stop) / price <= 0.05:
            bullets.append({"type": "watchlist", "text": f"{t} is {(price - stop) / price * 100:.1f}% above your stop (${stop:.2f})."})
        if target and 0 <= (target - price) / price <= 0.05:
            bullets.append({"type": "watchlist", "text": f"{t} is {(target - price) / price * 100:.1f}% below your target (${target:.2f})."})

    bullets = bullets[:7]

    # ── Headline ─────────────────────────────────────────────────────────────
    mood = regime.get("mood") or {}
    label = mood.get("label")
    if label:
        extras = []
        if new_tickers:
            extras.append(f"{len(new_tickers)} new")
        if hot_squeeze:
            extras.append(f"{len(hot_squeeze)} squeeze setup{'s' if len(hot_squeeze) != 1 else ''}")
        if improving:
            extras.append(f"{len(improving)} heating up")
        n = len(ranked)
        headline = f"{label} tape — {n} name{'s' if n != 1 else ''} ranked"
        if extras:
            headline += f", {', '.join(extras)}"
    elif ranked:
        n = len(ranked)
        headline = f"Scan update — {n} name{'s' if n != 1 else ''} ranked, top pick {ranked[0].get('ticker', '—')}"
    else:
        headline = "Scan warming up — first results arriving shortly"

    # ── Paragraph ────────────────────────────────────────────────────────────
    para_bits = []
    if regime.get("available"):
        para_bits.append(regime.get("narrative") or "")
    if breadth.get("pct_above_20ma") is not None:
        para_bits.append(
            f"In the discovery universe, {breadth['pct_above_20ma']:.0f}% of the "
            f"{breadth.get('n')} tracked names are above their 20-day average."
        )
    if improving and not decaying:
        para_bits.append("Scores are skewing higher scan-over-scan.")
    elif decaying and not improving:
        para_bits.append("Scores are skewing lower scan-over-scan.")

    return {
        "headline": headline,
        "paragraph": " ".join(p for p in para_bits if p),
        "bullets": bullets,
        "generated_at": datetime.now().isoformat(),
        "source": "template",
    }


def compose_and_polish(regime: dict | None, scan: dict, watchlist: list | None = None,
                       squeeze: list | None = None) -> dict:
    """compose() + optional LLM rewrite of headline/paragraph (template on any failure)."""
    brief = compose(regime, scan, watchlist=watchlist, squeeze=squeeze)
    polished = _maybe_llm_rewrite(brief)
    return polished or brief


def _maybe_llm_rewrite(brief: dict) -> dict | None:
    """The only networked function in this module. Returns None on ANY problem."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    facts_json = json.dumps(
        {
            "headline": brief["headline"],
            "paragraph": brief["paragraph"],
            "bullets": [b["text"] for b in brief["bullets"]],
        },
        sort_keys=True,
    )
    facts_hash = hashlib.sha256(facts_json.encode()).hexdigest()

    if _llm_memo["hash"] == facts_hash and _llm_memo["result"]:
        return {**_llm_memo["result"], "generated_at": brief["generated_at"]}
    if time.time() - _llm_memo["last_call"] < LLM_MIN_INTERVAL:
        return None
    _llm_memo["last_call"] = time.time()

    try:
        import anthropic  # optional dependency — pip install anthropic
        client = anthropic.Anthropic(api_key=api_key, timeout=10.0, max_retries=0)
        msg = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=600,
            messages=[{"role": "user", "content": _LLM_PROMPT.format(facts=facts_json)}],
        )
        text = msg.content[0].text.strip()
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
        data = json.loads(text)
        headline = (data.get("headline") or "").strip()
        paragraph = (data.get("paragraph") or "").strip()
        if not headline or not paragraph or len(paragraph) > 1200:
            return None

        # Ticker safety: every caps token in the rewrite must already exist in the facts
        out_tickers = set(re.findall(r"\b[A-Z]{2,5}\b", f"{headline} {paragraph}"))
        fact_tickers = set(re.findall(r"\b[A-Z]{2,5}\b", facts_json))
        if not out_tickers.issubset(fact_tickers):
            return None

        polished = {**brief, "headline": headline, "paragraph": paragraph, "source": "llm"}
        _llm_memo["hash"] = facts_hash
        _llm_memo["result"] = polished
        return polished
    except Exception as e:
        logger.warning(f"brief: LLM polish failed ({e}); using template")
        return None
