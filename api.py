"""FastAPI backend for the Stock Discovery Tool."""

import asyncio
import logging
import math
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


def _clean(obj):
    """Recursively convert numpy/pandas types to native Python types.

    Also maps non-finite floats (NaN/inf) to None — json.dumps raises on them,
    which would 500 an entire endpoint over one bad yfinance value.
    """
    if obj is None:
        return None
    # numpy scalar → native
    if hasattr(obj, "item") and hasattr(obj, "dtype"):
        obj = obj.item()
    if isinstance(obj, bool):
        return bool(obj)
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(x) for x in obj]
    return obj

import config
import fmp
import fundamentals
import momentum
import catalysts
import insiders
import early_detection
import competitors
import ml_patterns
import ml_breakout
import ml_sector
import news_sentiment
import reddit_sentiment
import db
import backtest
import alerts as alerts_module
import axt_filter
import photonics_cycle
import short_squeeze
import squeeze_discovery
import price_history
import ticker_edge
import pre_breakout
import smad
import book_signals
import market_regime
import brief as brief_composer
import evaluation
import regime_tilt
import conviction

# Initialize database
db.init_db()
import scorer
import universe_builder

logger = logging.getLogger("discovery")
pool = ThreadPoolExecutor(max_workers=5)

# --- Cache ---
SCAN_INTERVAL = 30 * 60  # 30 minutes

cache = {
    "universe": None,
    "results": None,
    "ranked": [],
    "alerts": [],
    "last_scan": None,
    "scan_in_progress": False,
    "new_since_last": [],  # tickers that appeared since last scan
    "history": [],  # track score changes over time
}

axt_cache = {
    "results": [],
    "last_scan": None,
    "scan_in_progress": False,
}

photonics_cache = {
    "phases": [],
    "last_scan": None,
    "scan_in_progress": False,
}

squeeze_cache = {
    "results": [],
    "last_scan": None,
    "scan_in_progress": False,
}

brief_cache = {"brief": None}


def _recompose_brief():
    """Rebuild the daily brief from current caches. Never raises."""
    try:
        scan = {
            "ranked": cache.get("ranked") or [],
            "new_tickers": cache.get("new_since_last") or [],
            "improving": cache.get("improving") or [],
            "decaying": cache.get("decaying") or [],
            "breadth": cache.get("breadth") or {},
        }
        brief_cache["brief"] = brief_composer.compose_and_polish(
            market_regime.get_cached(),
            scan,
            watchlist=db.get_watchlist(),
            squeeze=squeeze_cache.get("results") or [],
        )
    except Exception as e:
        logger.error(f"Brief compose failed: {e}")


def _run_full_pipeline():
    """Run the full discover → score pipeline. Called by background task."""
    logger.info("Starting full pipeline scan...")
    cache["scan_in_progress"] = True

    try:
        # Step 1: Discover
        uni = universe_builder.build_universe()
        cache["universe"] = uni
        logger.info(f"Discovered {uni['total']} tickers")

        if not uni["tickers"]:
            cache["scan_in_progress"] = False
            return

        # Step 2: Score top 30
        to_score = uni["tickers"][:40]
        results = {}
        for i, ticker in enumerate(to_score):
            try:
                result = _score_ticker(ticker)
                results[ticker] = result
                logger.info(f"  Scored {i+1}/{len(to_score)}: {ticker} = {result['composite']:.1f}")
            except Exception as e:
                logger.error(f"  Failed {ticker}: {e}")

        # Step 3: Rank — composite tilted by the current regime (bounded, logged).
        # composite is untouched; rank_score = composite × tilt drives ordering.
        regime_now = market_regime.get_cached()
        regime_label = (regime_now.get("mood") or {}).get("label") if regime_now.get("available") else None
        ranked_list = [{"ticker": t, **r} for t, r in results.items()]
        for r in ranked_list:
            tilt = regime_tilt.compute_tilt(r, regime_now)
            r["tilt"] = tilt
            r["rank_score"] = round(r["composite"] * tilt["factor"], 1)
            r["setup"] = conviction.assess(r, regime_now)  # single graded verdict
        ranked_list.sort(key=lambda x: x["rank_score"], reverse=True)
        alerts = [r["ticker"] for r in ranked_list if r["multi_signal_alert"]]

        # Step 4: Detect new tickers vs previous scan
        new_tickers = []
        if cache["ranked"]:
            old_tickers = {r["ticker"] for r in cache["ranked"]}
            new_tickers = [r["ticker"] for r in ranked_list if r["ticker"] not in old_tickers]

        # Step 5: Detect score changes (stocks improving / decaying)
        improving = []
        decaying = []
        if cache["results"]:
            for ticker, result in results.items():
                old = cache["results"].get(ticker)
                if old:
                    old_score = old.get("composite", 0)
                    new_score = result["composite"]
                    delta = new_score - old_score
                    entry = {
                        "ticker": ticker,
                        "old_score": old_score,
                        "new_score": new_score,
                        "change": round(delta, 1),
                    }
                    if delta >= 5:  # improved by 5+ points
                        improving.append(entry)
                    elif delta <= -5:  # faded by 5+ points
                        decaying.append(entry)

        # Step 6: Universe breadth from the edge gauges (zero extra fetches)
        flags = [r.get("edge", {}).get("above_20ma") for r in results.values()]
        flags = [f for f in flags if f is not None]
        breadth = {
            "pct_above_20ma": round(100 * sum(flags) / len(flags), 1) if flags else None,
            "n": len(flags),
        }

        # Update cache
        cache["results"] = results
        cache["ranked"] = ranked_list
        cache["alerts"] = alerts
        cache["new_since_last"] = new_tickers
        cache["improving"] = improving
        cache["decaying"] = decaying
        cache["breadth"] = breadth
        cache["last_scan"] = datetime.now().isoformat()
        cache["scan_in_progress"] = False

        # ─── Persist snapshots for backtesting ───
        try:
            ai_picks = [s["ticker"] for s in sorted(ranked_list, key=lambda x: x.get("ml_score", 0), reverse=True)[:3]]
            db.save_snapshot(ranked_list, scan_date=cache["last_scan"], ai_picks=ai_picks, regime_label=regime_label)
        except Exception as e:
            logger.error(f"Failed to save snapshot: {e}")

        # ─── Send Telegram alerts ───
        try:
            ai_picks = [s["ticker"] for s in sorted(ranked_list, key=lambda x: x.get("ml_score", 0), reverse=True)[:3]]
            alerts_module.process_scan_results(ranked_list, ai_picks)
        except Exception as e:
            logger.error(f"Failed to send alerts: {e}")

        # ─── Recompose the daily brief on fresh scan data ───
        _recompose_brief()

        logger.info(
            f"Pipeline done: {len(ranked_list)} scored, "
            f"{len(alerts)} alerts, {len(new_tickers)} new, "
            f"{len(improving)} improving, {len(decaying)} decaying"
        )

    except Exception as e:
        logger.error(f"Pipeline failed: {e}")
        cache["scan_in_progress"] = False


def _run_photonics_pipeline():
    """Score all phase seed universes through the photonics cycle model."""
    photonics_cache["scan_in_progress"] = True
    try:
        phases = photonics_cycle.scan_all_phases()
        photonics_cache["phases"] = phases
        photonics_cache["last_scan"] = datetime.now().isoformat()
        total_candidates = sum(len(p["candidates"]) for p in phases)
        logger.info(f"Photonics cycle scan done: {total_candidates} candidates across 5 phases")
    except Exception as e:
        logger.error(f"Photonics cycle scan failed: {e}")
    finally:
        photonics_cache["scan_in_progress"] = False


def _run_squeeze_pipeline():
    """Proactively discover squeeze candidates via Finviz short-interest screens."""
    squeeze_cache["scan_in_progress"] = True
    try:
        results = squeeze_discovery.scan(max_candidates=80, min_score=35)
        squeeze_cache["results"] = results
        squeeze_cache["last_scan"] = datetime.now().isoformat()
        candidates = sum(1 for r in results if r["score"] >= 60)
        logger.info(f"Squeeze discovery done: {len(results)} setups, {candidates} high/extreme")
    except Exception as e:
        logger.error(f"Squeeze discovery failed: {e}")
    finally:
        squeeze_cache["scan_in_progress"] = False


def _run_axt_pipeline(tickers: list[str] | None = None):
    """Score tickers through the AXT filter. Defaults to the seed universe."""
    axt_cache["scan_in_progress"] = True
    to_scan = tickers or axt_filter.AXT_SEED_UNIVERSE
    results = []
    for ticker in to_scan:
        try:
            r = axt_filter.score(ticker)
            results.append(r)
            logger.info(f"  AXT {ticker}: rerate={r['rerate_score']}, layer={r['stack_layer']}")
        except Exception as e:
            logger.error(f"  AXT failed {ticker}: {e}")
    results.sort(key=lambda x: x["rerate_score"], reverse=True)
    axt_cache["results"] = results
    axt_cache["last_scan"] = datetime.now().isoformat()
    axt_cache["scan_in_progress"] = False
    logger.info(f"AXT scan done: {len(results)} tickers, {sum(1 for r in results if r['is_candidate'])} candidates")


def _run_regime_pipeline():
    """Refresh the market regime (and recompose the brief on top of it)."""
    breadth = cache.get("breadth") or {}
    market_regime.refresh(
        breadth_universe_pct=breadth.get("pct_above_20ma"),
        universe_n=breadth.get("n"),
    )
    _recompose_brief()


async def _regime_loop():
    """Refresh the market regime every REGIME_INTERVAL."""
    loop = asyncio.get_event_loop()
    while True:
        await asyncio.sleep(config.REGIME_INTERVAL)
        try:
            await loop.run_in_executor(pool, _run_regime_pipeline)
        except Exception as e:
            logger.error(f"Regime refresh error: {e}")


def _run_secondary_pipelines():
    """Rerun the heavier discovery scanners (AXT, photonics, squeeze)."""
    loop = asyncio.get_event_loop()
    # Submit to the pool; each manages its own work and must not block each other
    loop.run_in_executor(pool, _run_axt_pipeline, None)
    loop.run_in_executor(pool, _run_photonics_pipeline)
    loop.run_in_executor(pool, _run_squeeze_pipeline)


_eval_state = {"last": 0.0}
EVAL_INTERVAL = 6 * 3600  # forward-return backfill is heavy (~200 fetches); every 6h


def _run_evaluation_pipeline(force: bool = False):
    """Backfill realized forward returns + recompute scorecard/calibration."""
    if not force and time.time() - _eval_state["last"] < EVAL_INTERVAL:
        return
    _eval_state["last"] = time.time()
    try:
        evaluation.refresh()
    except Exception as e:
        logger.error(f"Evaluation pipeline failed: {e}")


async def _secondary_loop():
    """Keep AXT / photonics / squeeze scans fresh on the same cadence as the main scan.

    Without this they only ran once at startup and went stale (the squeeze
    scanner in particular is the whole point of the Squeeze tab).
    """
    while True:
        await asyncio.sleep(SCAN_INTERVAL)
        try:
            _run_secondary_pipelines()
            asyncio.get_event_loop().run_in_executor(pool, _run_evaluation_pipeline, False)
        except Exception as e:
            logger.error(f"Secondary scan error: {e}")


async def _background_scanner():
    """Background task that runs the pipeline periodically."""
    loop = asyncio.get_event_loop()
    # Regime first so the first scan/brief has market context, then keep it fresh
    await loop.run_in_executor(pool, _run_regime_pipeline)
    asyncio.create_task(_regime_loop())

    await loop.run_in_executor(pool, _run_full_pipeline)
    # Kick the heavier discovery scanners once now, then keep them fresh on a loop.
    # NOTE: run_in_executor submits to the pool and returns a Future —
    # do NOT wrap in asyncio.create_task (it requires a coroutine and raises).
    _run_secondary_pipelines()
    asyncio.create_task(_secondary_loop())

    # Backfill forward-return evaluation once at startup (then 6h-gated in the loop)
    loop.run_in_executor(pool, _run_evaluation_pipeline, True)

    # Then every SCAN_INTERVAL
    while True:
        await asyncio.sleep(SCAN_INTERVAL)
        try:
            await loop.run_in_executor(pool, _run_full_pipeline)
        except Exception as e:
            logger.error(f"Background scan error: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start background scanner
    task = asyncio.create_task(_background_scanner())
    yield
    task.cancel()
    pool.shutdown(wait=False)


app = FastAPI(title="Stock Discovery API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Models ---

class ScoreRequest(BaseModel):
    tickers: list[str]
    weights: dict[str, float] | None = None
    skip_filter: bool = False


class UniverseRequest(BaseModel):
    use_yahoo: bool = True
    use_finviz: bool = True
    use_reddit: bool = True
    use_sec: bool = True
    use_rss: bool = True


class ConfigUpdate(BaseModel):
    weights: dict[str, float] | None = None
    min_price: float | None = None
    max_price: float | None = None
    min_avg_volume: int | None = None


# --- Helpers ---

def _num(x, default=0.0) -> float:
    """Coerce to a finite float; yfinance loves returning None/NaN."""
    try:
        v = float(x)
        return v if math.isfinite(v) else default
    except (TypeError, ValueError):
        return default


def _score_ticker(ticker: str, weights: dict | None = None) -> dict:
    """Score a single ticker across all buckets."""
    # Per-call weights — never mutate the global config.WEIGHTS (it races
    # across the scoring thread pool).
    local_weights = dict(config.WEIGHTS)
    if weights:
        for k, v in weights.items():
            if k in local_weights:
                local_weights[k] = v

    # Shared daily history — fetched once, reused by momentum + edge gauges
    hist = price_history.get_history(ticker)
    yf_info = None

    bucket_scores = {
        "fundamentals": fundamentals.score(ticker),
        "momentum": momentum.score(ticker, hist=hist),
        "catalyst": catalysts.score(ticker),
        "insider": insiders.score(ticker),
        "sentiment": news_sentiment.score(ticker),
    }
    # Kill NaN at the source — a single NaN bucket poisons the composite,
    # the ML layer, ranking sorts, and JSON serialization
    for b in bucket_scores.values():
        b["score"] = _num(b.get("score", 0))
    result = scorer.composite_score(bucket_scores, weights=local_weights)

    # Add price/market data
    try:
        if fmp.is_configured():
            q = fmp.get_quote(ticker)
            # Try to get description too
            desc = q.get("description", "")
            if desc and len(desc) > 160:
                desc = desc[:160].rsplit(" ", 1)[0] + "…"
            result["quote"] = {
                "price": q.get("price", 0),
                "change_pct": q.get("changesPercentage", 0),
                "market_cap": q.get("marketCap", 0),
                "volume": q.get("volume", 0),
                "avg_volume": q.get("avgVolume", 0),
                "year_high": q.get("yearHigh", 0),
                "year_low": q.get("yearLow", 0),
                "sector": q.get("sector", ""),
                "industry": q.get("industry", ""),
                "name": q.get("name", ticker),
                "description": desc,
            }
        else:
            import yfinance as yf
            info = yf.Ticker(ticker).info or {}
            yf_info = info
            price = _num(info.get("currentPrice") or info.get("regularMarketPrice", 0))
            prev = _num(info.get("previousClose", price), default=price)
            change_pct = ((price - prev) / prev * 100) if prev else 0
            # Short description
            desc = info.get("longBusinessSummary", "") or info.get("longName", "")
            if desc and len(desc) > 160:
                desc = desc[:160].rsplit(" ", 1)[0] + "…"
            result["quote"] = {
                "price": price,
                "change_pct": _num(change_pct),
                "market_cap": _num(info.get("marketCap", 0)),
                "volume": _num(info.get("volume", 0)),
                "avg_volume": _num(info.get("averageVolume", 0)),
                "year_high": _num(info.get("fiftyTwoWeekHigh", 0)),
                "year_low": _num(info.get("fiftyTwoWeekLow", 0)),
                "sector": info.get("sector", ""),
                "industry": info.get("industry", ""),
                "name": info.get("shortName", ticker) or info.get("longName", ticker),
                "description": desc,
            }
    except Exception:
        result["quote"] = None

    # Add early detection / potential score
    early = early_detection.score(ticker, bucket_scores)
    result["early_detection"] = early

    # Pre-breakout / coiled-spring detector — catch them BEFORE they fly
    try:
        result["coiled"] = pre_breakout.compute(ticker, hist)
    except Exception:
        result["coiled"] = dict(pre_breakout.UNAVAILABLE)

    # Smart-money accumulation / demand-zone (supply/demand + institutional intent)
    try:
        result["smad"] = smad.compute(ticker, hist)
    except Exception:
        result["smad"] = dict(smad.UNAVAILABLE)

    # Daily-bar book signals: market phase, RBS flip, reversal candle, volume
    # profile, concrete trade plan (Supply & Demand Mastery + Institutional Intent)
    try:
        result["book"] = book_signals.compute(hist, zone=(result.get("smad") or {}).get("demand_zone"))
    except Exception:
        result["book"] = {"available": False}

    # Add competitor analysis
    comp = competitors.analyze(ticker)
    result["competitors"] = comp

    # ─── ML layer ───
    # 1. Pattern matching vs historical winners
    pattern = ml_patterns.analyze({**bucket_scores, "early_detection": early})
    result["pattern_match"] = pattern

    # 2. Breakout probability
    early_score = early.get("score", 0)
    breakout = ml_breakout.analyze(bucket_scores, early_score)
    result["breakout"] = breakout

    # 3. Sector momentum / catch-up prediction
    sector = ml_sector.analyze(comp, early_score)
    result["sector_momentum"] = sector

    # Composite ML score (0-100) — weighted combination
    ml_score = (
        pattern["score"] * 0.35 +
        breakout["score"] * 0.45 +
        sector["score"] * 0.20
    )
    result["ml_score"] = round(_num(ml_score), 1)

    # Short squeeze potential — reuse the already-fetched yfinance info
    squeeze = short_squeeze.score(ticker, bucket_scores, yf_info=yf_info)
    result["short_squeeze"] = squeeze

    # Measured (calibrated) win-probability from the closed-loop evaluation,
    # if calibration has been computed. None until enough forward data exists.
    try:
        p = evaluation.calibrated_p_win(result["composite"], "composite_score", 5)
        result["calibrated_p_win"] = round(p, 3) if p is not None else None
    except Exception:
        result["calibrated_p_win"] = None

    # Trading-regime gauges (FLOW / BEARING / PULSE) from the shared history
    try:
        result["edge"] = ticker_edge.compute(ticker, hist)
    except Exception:
        result["edge"] = dict(ticker_edge.UNAVAILABLE)

    return result


def _filter_ticker(ticker: str) -> dict:
    """Check if a ticker passes filters."""
    try:
        if fmp.is_configured():
            quote = fmp.get_quote(ticker)
            if not quote:
                return {"ticker": ticker, "passed": False, "reason": "No data"}
            price = quote.get("price", 0) or 0
            avg_vol = quote.get("avgVolume", 0) or 0
            mcap = quote.get("marketCap", 0) or 0
        else:
            import yfinance as yf
            stock = yf.Ticker(ticker)
            info = stock.info or {}
            price = info.get("currentPrice") or info.get("regularMarketPrice") or 0
            avg_vol = info.get("averageVolume") or 0
            mcap = info.get("marketCap") or 0

        if price < config.MIN_PRICE or price > config.MAX_PRICE:
            return {"ticker": ticker, "passed": False, "reason": f"Price ${price:.2f}"}
        if avg_vol < config.MIN_AVG_VOLUME:
            return {"ticker": ticker, "passed": False, "reason": f"Volume {avg_vol:,.0f}"}
        if mcap < config.MIN_MARKET_CAP:
            return {"ticker": ticker, "passed": False, "reason": f"MCap ${mcap/1e6:.0f}M"}
        return {"ticker": ticker, "passed": True, "reason": "OK"}
    except Exception:
        return {"ticker": ticker, "passed": False, "reason": "Error fetching data"}


# --- Routes ---

@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "fmp_configured": fmp.is_configured(),
        "fmp_key_prefix": fmp.API_KEY[:4] + "..." if fmp.API_KEY else "NOT SET",
        "last_scan": cache["last_scan"],
        "scan_in_progress": cache["scan_in_progress"],
        "cached_results": len(cache["ranked"]),
    }


@app.get("/api/dashboard")
async def dashboard():
    """
    Main endpoint — returns cached results instantly.
    No waiting. Background scanner keeps data fresh.
    """
    regime = market_regime.get_cached()
    return _clean({
        "universe": cache["universe"],
        "ranked": cache["ranked"],
        "alerts": cache["alerts"],
        "new_tickers": cache.get("new_since_last", []),
        "improving": cache.get("improving", []),
        "decaying": cache.get("decaying", []),
        "breadth": cache.get("breadth"),
        "market_regime": {
            "score": regime.get("mood", {}).get("score"),
            "label": regime.get("mood", {}).get("label"),
            "vix": regime.get("volatility", {}).get("vix"),
            "as_of": regime.get("as_of"),
        } if regime.get("available") else None,
        "last_scan": cache["last_scan"],
        "scan_in_progress": cache["scan_in_progress"],
        "next_scan_in": _next_scan_seconds(),
    })


def _next_scan_seconds() -> int:
    if not cache["last_scan"]:
        return 0
    try:
        last = datetime.fromisoformat(cache["last_scan"])
        elapsed = (datetime.now() - last).total_seconds()
        remaining = max(0, SCAN_INTERVAL - elapsed)
        return int(remaining)
    except Exception:
        return 0


@app.post("/api/scan")
async def force_scan():
    """Force a new scan immediately."""
    if cache["scan_in_progress"]:
        return {"status": "already_running"}
    loop = asyncio.get_event_loop()
    loop.run_in_executor(pool, _run_full_pipeline)
    return {"status": "started"}


@app.get("/api/config")
async def get_config():
    return {
        "weights": config.WEIGHTS,
        "min_price": config.MIN_PRICE,
        "max_price": config.MAX_PRICE,
        "min_avg_volume": config.MIN_AVG_VOLUME,
        "min_market_cap": config.MIN_MARKET_CAP,
        "multi_signal_threshold": config.MULTI_SIGNAL_THRESHOLD,
        "top_n": config.TOP_N,
        "reddit_configured": bool(config.REDDIT_CLIENT_ID),
    }


@app.put("/api/config")
async def update_config(req: ConfigUpdate):
    if req.weights:
        config.WEIGHTS = req.weights
    if req.min_price is not None:
        config.MIN_PRICE = req.min_price
    if req.max_price is not None:
        config.MAX_PRICE = req.max_price
    if req.min_avg_volume is not None:
        config.MIN_AVG_VOLUME = req.min_avg_volume
    return await get_config()


@app.post("/api/discover")
async def discover(req: UniverseRequest):
    """Auto-discover tickers from multiple sources."""
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        pool,
        lambda: universe_builder.build_universe(
            use_yahoo=req.use_yahoo,
            use_finviz=req.use_finviz,
            use_reddit=req.use_reddit,
            use_sec=req.use_sec,
            use_rss=req.use_rss,
        ),
    )
    return result


@app.post("/api/score")
async def score_tickers(req: ScoreRequest):
    """Score a list of tickers."""
    loop = asyncio.get_event_loop()
    tickers = [t.upper() for t in req.tickers]

    if not req.skip_filter:
        filter_futures = [
            loop.run_in_executor(pool, _filter_ticker, t) for t in tickers
        ]
        filter_results = await asyncio.gather(*filter_futures)
        passed = [r["ticker"] for r in filter_results if r["passed"]]
        filtered_out = [r for r in filter_results if not r["passed"]]
    else:
        passed = tickers
        filtered_out = []

    if not passed:
        return {"results": {}, "ranked": [], "filtered_out": filtered_out, "alerts": []}

    score_futures = [
        loop.run_in_executor(pool, _score_ticker, t, req.weights) for t in passed
    ]
    score_results = await asyncio.gather(*score_futures)

    results = {}
    for ticker, result in zip(passed, score_results):
        results[ticker] = result

    ranked = sorted(results.items(), key=lambda x: x[1]["composite"], reverse=True)
    alerts = [t for t, r in ranked if r["multi_signal_alert"]]

    return _clean({
        "results": results,
        "ranked": [{"ticker": t, **r} for t, r in ranked],
        "filtered_out": filtered_out,
        "alerts": alerts,
    })


@app.get("/api/score/{ticker}")
async def score_single(ticker: str):
    """Score a single ticker."""
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(pool, _score_ticker, ticker.upper())
    return _clean({"ticker": ticker.upper(), **result})


# ────────────────────────────────────────────
# Watchlist endpoints
# ────────────────────────────────────────────

class WatchlistAddRequest(BaseModel):
    ticker: str
    entry_price: float | None = None
    target_price: float | None = None
    stop_loss: float | None = None
    notes: str = ""
    shares: float = 0


class WatchlistUpdateRequest(BaseModel):
    entry_price: float | None = None
    target_price: float | None = None
    stop_loss: float | None = None
    notes: str | None = None
    shares: float | None = None


@app.get("/api/watchlist")
async def get_watchlist():
    """Get watchlist with live prices and P&L."""
    items = db.get_watchlist()
    enriched = []
    for item in items:
        ticker = item["ticker"]
        # Try to get current price from cache first
        match = next((r for r in cache.get("ranked", []) if r.get("ticker") == ticker), None)
        if match and match.get("quote"):
            current = match["quote"].get("price", 0)
            quote = match["quote"]
        else:
            # Fetch fresh
            try:
                if fmp.is_configured():
                    q = fmp.get_quote(ticker)
                    current = q.get("price", 0)
                    quote = {"price": current, "name": q.get("name", ticker), "change_pct": q.get("changesPercentage", 0)}
                else:
                    import yfinance as yf
                    info = yf.Ticker(ticker).info or {}
                    current = info.get("currentPrice") or info.get("regularMarketPrice", 0)
                    quote = {"price": current, "name": info.get("shortName", ticker), "change_pct": 0}
            except Exception:
                current = 0
                quote = {"price": 0, "name": ticker, "change_pct": 0}

        item["current_price"] = current
        item["quote"] = quote
        if item.get("entry_price") and current:
            item["pnl_pct"] = round((current - item["entry_price"]) / item["entry_price"] * 100, 2)
            item["pnl_dollars"] = round((current - item["entry_price"]) * (item.get("shares", 0) or 0), 2)
        else:
            item["pnl_pct"] = 0
            item["pnl_dollars"] = 0

        # Add latest score data if available
        if match:
            item["composite"] = match.get("composite", 0)
            item["ml_score"] = match.get("ml_score", 0)

        enriched.append(item)
    return _clean({"items": enriched})


@app.post("/api/watchlist")
async def add_watchlist(req: WatchlistAddRequest):
    entry_price = req.entry_price
    # Auto-fill entry price with current market price if not provided
    if entry_price is None or entry_price <= 0:
        ticker = req.ticker.upper()
        match = next((r for r in cache.get("ranked", []) if r.get("ticker") == ticker), None)
        if match and match.get("quote"):
            entry_price = match["quote"].get("price")
        if not entry_price:
            try:
                if fmp.is_configured():
                    entry_price = fmp.get_quote(ticker).get("price")
                else:
                    import yfinance as yf
                    info = yf.Ticker(ticker).info or {}
                    entry_price = info.get("currentPrice") or info.get("regularMarketPrice")
            except Exception:
                entry_price = None

    item = db.add_to_watchlist(
        req.ticker,
        entry_price=entry_price,
        target_price=req.target_price,
        stop_loss=req.stop_loss,
        notes=req.notes,
        shares=req.shares,
    )
    return _clean(item or {})


@app.put("/api/watchlist/{ticker}")
async def update_watchlist(ticker: str, req: WatchlistUpdateRequest):
    fields = {k: v for k, v in req.model_dump().items() if v is not None}
    item = db.update_watchlist_item(ticker, **fields)
    return _clean(item or {})


@app.delete("/api/watchlist/{ticker}")
async def delete_watchlist(ticker: str):
    removed = db.remove_from_watchlist(ticker)
    return {"removed": removed}


# ────────────────────────────────────────────
# Backtest endpoint
# ────────────────────────────────────────────

@app.get("/api/backtest")
async def get_backtest():
    """Get historical performance of past picks."""
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(pool, backtest.compute_performance)
    return _clean(result)


# ────────────────────────────────────────────
# Alerts endpoint
# ────────────────────────────────────────────

@app.get("/api/alerts/recent")
async def get_recent_alerts():
    return {
        "alerts": db.get_recent_alerts(limit=20),
        "configured": alerts_module.is_configured(),
        "channels": {
            "pushover": alerts_module._pushover_configured(),
            "telegram": alerts_module._telegram_configured(),
        },
    }


@app.post("/api/alerts/test")
async def test_alert():
    success = alerts_module.send_test()
    return {
        "sent": success,
        "configured": alerts_module.is_configured(),
        "channels": {
            "pushover": alerts_module._pushover_configured(),
            "telegram": alerts_module._telegram_configured(),
        },
    }


# ────────────────────────────────────────────
# AXT Microcap Filter endpoints
# ────────────────────────────────────────────

class AxtScanRequest(BaseModel):
    tickers: list[str] | None = None  # None = use seed universe


@app.get("/api/axt-scan")
async def get_axt_scan():
    """Return cached AXT filter results over the seed universe."""
    return _clean({
        "results": axt_cache["results"],
        "last_scan": axt_cache["last_scan"],
        "scan_in_progress": axt_cache["scan_in_progress"],
        "candidates": [r for r in axt_cache["results"] if r.get("is_candidate")],
        "seed_universe": axt_filter.AXT_SEED_UNIVERSE,
    })


@app.post("/api/axt-scan")
async def run_axt_scan(req: AxtScanRequest):
    """Trigger an AXT scan. Optionally pass custom ticker list."""
    if axt_cache["scan_in_progress"]:
        return {"status": "already_running"}
    loop = asyncio.get_event_loop()
    loop.run_in_executor(pool, _run_axt_pipeline, req.tickers)
    return {"status": "started"}


@app.get("/api/axt-scan/{ticker}")
async def axt_score_single(ticker: str):
    """Score a single ticker through the AXT filter."""
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(pool, axt_filter.score, ticker.upper())
    return _clean(result)


# ────────────────────────────────────────────
# Photonics Cycle endpoints
# ────────────────────────────────────────────

@app.get("/api/photonics-cycle")
async def get_photonics_cycle():
    """Return cached photonics cycle data — all 5 phases with ranked tickers."""
    return _clean({
        "current_phase_num": photonics_cycle.CURRENT_PHASE_NUM,
        "phases": photonics_cache["phases"],
        "last_scan": photonics_cache["last_scan"],
        "scan_in_progress": photonics_cache["scan_in_progress"],
    })


@app.post("/api/photonics-cycle/rescan")
async def rescan_photonics_cycle():
    """Trigger a fresh photonics cycle scan."""
    if photonics_cache["scan_in_progress"]:
        return {"status": "already_running"}
    loop = asyncio.get_event_loop()
    loop.run_in_executor(pool, _run_photonics_pipeline)
    return {"status": "started"}


@app.get("/api/photonics-cycle/{ticker}")
async def photonics_score_single(ticker: str):
    """Score a single ticker against all 5 phases."""
    t = ticker.upper()
    loop = asyncio.get_event_loop()
    results = {}
    for phase in photonics_cycle.PHASES:
        r = await loop.run_in_executor(pool, photonics_cycle.score_for_phase, t, phase)
        results[phase["id"]] = r
    return _clean({
        "ticker": t,
        "phases": results,
        "best_phase": max(results.items(), key=lambda x: x[1]["phase_score"])[0],
    })


# ────────────────────────────────────────────
# Market Regime / Brief / History endpoints
# ────────────────────────────────────────────

@app.get("/api/market-regime")
async def get_market_regime():
    """Cached market-regime payload (mood, indices, volatility, sectors, narrative)."""
    return _clean(market_regime.get_cached())


@app.post("/api/market-regime/refresh")
async def refresh_market_regime():
    """Trigger an immediate regime refresh."""
    loop = asyncio.get_event_loop()
    loop.run_in_executor(pool, _run_regime_pipeline)
    return {"status": "started"}


@app.get("/api/brief")
async def get_brief():
    """The latest composed daily brief (template or LLM-polished)."""
    return _clean({"brief": brief_cache.get("brief"), "last_scan": cache.get("last_scan")})


@app.get("/api/scorecard")
async def get_scorecard():
    """Measured model scorecard: per-signal IC, decile hit-rates, calibration, coverage.

    Builds from already-persisted snapshot_returns (no network) if the
    background backfill hasn't populated the in-memory cache yet.
    """
    cached = evaluation.get_cached()
    if not cached.get("scorecards"):
        cards = {h: evaluation.scorecard(h) for h in evaluation.HORIZONS}
        for h in evaluation.HORIZONS:
            for sig in ("composite_score", "ml_score"):
                evaluation.calibration(sig, h)
        cached = evaluation.get_cached()
        cached["scorecards"] = cards
    return _clean(cached)


@app.post("/api/scorecard/refresh")
async def refresh_scorecard():
    """Force a fresh forward-return backfill + recompute (heavy)."""
    loop = asyncio.get_event_loop()
    loop.run_in_executor(pool, _run_evaluation_pipeline, True)
    return {"status": "started"}


@app.get("/api/price-history/{ticker}")
async def get_price_history(ticker: str, period: str = "6mo"):
    """Daily closes for the deep-dive price chart (via the shared TTL cache)."""
    def _load():
        hist = price_history.get_history(ticker.upper(), period=period)
        if hist is None or hist.empty:
            return {"ticker": ticker.upper(), "points": []}
        pts = [
            {"date": d.strftime("%Y-%m-%d"), "close": round(float(c), 4)}
            for d, c in zip(hist.index, hist["Close"].to_numpy())
            if math.isfinite(float(c))
        ]
        return {"ticker": ticker.upper(), "points": pts}

    loop = asyncio.get_event_loop()
    return _clean(await loop.run_in_executor(pool, _load))


@app.get("/api/history/{ticker}")
async def get_score_history(ticker: str):
    """Score history for sparklines, from scan snapshots (ascending)."""
    rows = db.get_snapshots(ticker.upper())
    points = [
        {
            "scan_date": r["scan_date"],
            "composite": r.get("composite_score"),
            "ml_score": r.get("ml_score"),
            "price": r.get("price"),
        }
        for r in reversed(rows)
    ]
    return _clean({"ticker": ticker.upper(), "points": points, "count": len(points)})


# ────────────────────────────────────────────
# Squeeze Discovery endpoints
# ────────────────────────────────────────────

@app.get("/api/squeeze-scan")
async def get_squeeze_scan():
    """Return cached squeeze discovery results."""
    return _clean({
        "results": squeeze_cache["results"],
        "candidates": [r for r in squeeze_cache["results"] if r["score"] >= 60],
        "last_scan": squeeze_cache["last_scan"],
        "scan_in_progress": squeeze_cache["scan_in_progress"],
    })


@app.post("/api/squeeze-scan/rescan")
async def rescan_squeeze():
    """Trigger a fresh squeeze discovery scan."""
    if squeeze_cache["scan_in_progress"]:
        return {"status": "already_running"}
    loop = asyncio.get_event_loop()
    loop.run_in_executor(pool, _run_squeeze_pipeline)
    return {"status": "started"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
