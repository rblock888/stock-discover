"""FastAPI backend for the Stock Discovery Tool."""

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import config
import fmp
import fundamentals
import momentum
import catalysts
import insiders
import early_detection
import competitors
import reddit_sentiment
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
        to_score = uni["tickers"][:30]
        results = {}
        for i, ticker in enumerate(to_score):
            try:
                result = _score_ticker(ticker)
                results[ticker] = result
                logger.info(f"  Scored {i+1}/{len(to_score)}: {ticker} = {result['composite']:.1f}")
            except Exception as e:
                logger.error(f"  Failed {ticker}: {e}")

        # Step 3: Rank
        ranked = sorted(results.items(), key=lambda x: x[1]["composite"], reverse=True)
        alerts = [t for t, r in ranked if r["multi_signal_alert"]]
        ranked_list = [{"ticker": t, **r} for t, r in ranked]

        # Step 4: Detect new tickers vs previous scan
        new_tickers = []
        if cache["ranked"]:
            old_tickers = {r["ticker"] for r in cache["ranked"]}
            new_tickers = [r["ticker"] for r in ranked_list if r["ticker"] not in old_tickers]

        # Step 5: Detect score changes (stocks improving)
        improving = []
        if cache["results"]:
            for ticker, result in results.items():
                old = cache["results"].get(ticker)
                if old:
                    old_score = old.get("composite", 0)
                    new_score = result["composite"]
                    if new_score - old_score >= 5:  # improved by 5+ points
                        improving.append({
                            "ticker": ticker,
                            "old_score": old_score,
                            "new_score": new_score,
                            "change": round(new_score - old_score, 1),
                        })

        # Update cache
        cache["results"] = results
        cache["ranked"] = ranked_list
        cache["alerts"] = alerts
        cache["new_since_last"] = new_tickers
        cache["improving"] = improving
        cache["last_scan"] = datetime.now().isoformat()
        cache["scan_in_progress"] = False

        logger.info(
            f"Pipeline done: {len(ranked_list)} scored, "
            f"{len(alerts)} alerts, {len(new_tickers)} new, "
            f"{len(improving)} improving"
        )

    except Exception as e:
        logger.error(f"Pipeline failed: {e}")
        cache["scan_in_progress"] = False


async def _background_scanner():
    """Background task that runs the pipeline periodically."""
    # Run immediately on startup
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(pool, _run_full_pipeline)

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

def _score_ticker(ticker: str, weights: dict | None = None) -> dict:
    """Score a single ticker across all buckets."""
    if weights:
        for k, v in weights.items():
            if k in config.WEIGHTS:
                config.WEIGHTS[k] = v

    bucket_scores = {
        "fundamentals": fundamentals.score(ticker),
        "momentum": momentum.score(ticker),
        "catalyst": catalysts.score(ticker),
        "insider": insiders.score(ticker),
        "sentiment": reddit_sentiment.score(ticker),
    }
    result = scorer.composite_score(bucket_scores)

    # Add early detection / potential score
    early = early_detection.score(ticker, bucket_scores)
    result["early_detection"] = early

    # Add competitor analysis
    comp = competitors.analyze(ticker)
    result["competitors"] = comp

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
    return {
        "universe": cache["universe"],
        "ranked": cache["ranked"],
        "alerts": cache["alerts"],
        "new_tickers": cache.get("new_since_last", []),
        "improving": cache.get("improving", []),
        "last_scan": cache["last_scan"],
        "scan_in_progress": cache["scan_in_progress"],
        "next_scan_in": _next_scan_seconds(),
    }


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
    asyncio.create_task(
        loop.run_in_executor(pool, _run_full_pipeline)
    )
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

    return {
        "results": results,
        "ranked": [{"ticker": t, **r} for t, r in ranked],
        "filtered_out": filtered_out,
        "alerts": alerts,
    }


@app.get("/api/score/{ticker}")
async def score_single(ticker: str):
    """Score a single ticker."""
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(pool, _score_ticker, ticker.upper())
    return {"ticker": ticker.upper(), **result}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
