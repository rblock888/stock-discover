"""FastAPI backend for the Stock Discovery Tool."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import json

import config
import fmp
import fundamentals
import momentum
import catalysts
import insiders
import reddit_sentiment
import scorer
import universe_builder

pool = ThreadPoolExecutor(max_workers=5)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
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
    return scorer.composite_score(bucket_scores)


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
    return {"status": "ok"}


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

    # Filter first if not skipped
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

    # Score
    score_futures = [
        loop.run_in_executor(pool, _score_ticker, t, req.weights) for t in passed
    ]
    score_results = await asyncio.gather(*score_futures)

    results = {}
    for ticker, result in zip(passed, score_results):
        results[ticker] = result

    # Rank
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
