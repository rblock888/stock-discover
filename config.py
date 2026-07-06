"""Configuration for the stock discovery tool."""

# --- Scoring weights (must sum to 1.0) ---
# Reallocated 2026-07-02 from the measured evidence (n=466 @5d): catalyst was the
# only bucket with positive IC (+0.24); momentum (-0.09) and sentiment (-0.19)
# measured HARMFUL. Not the naive 100%-catalyst recommendation — the evidence
# base is only ~3 independent trading days, so this is a shrunk blend with
# guardrails: clamp any future reallocation to [0.05, 0.50] per bucket, and
# NEVER delete a bucket key (scorer iterates weights.items(); a removed key
# stops being persisted to bucket_scores and becomes permanently unmeasurable).
WEIGHTS = {
    "catalyst": 0.45,
    "fundamentals": 0.25,
    "insider": 0.15,
    "momentum": 0.10,
    "sentiment": 0.05,
}
WEIGHTS_CHANGED = "2026-07-02"  # evaluation segments pre/post this date

# Dates when a persisted signal's DEFINITION changed — evaluation must not pool
# rows across a cutover (the same column means different things before/after).
CUTOVER_DATES = {
    "weights_reallocation": "2026-07-02",
    "catalyst_metrics": "2026-07-02",       # cat_* sub-components start persisting
    "attention_component": "2026-07-02",    # sixth bucket_scores key starts persisting
    "setup_plan_persistence": "2026-07-02", # full trade plan persisted per snapshot
    "grade_version_2": "2026-07-02",        # A-gate: sentiment out of n_fund, (cat|sq) required
    "tier_first_sort": "2026-07-02",        # ranked list sorts grade-tier first, tilt within
    "tradeable_backtest": "2026-07-02",     # setup stats = realistic fills + slippage
    "win_thresholds_scaled": "2026-07-02",  # win bar scales with horizon (5%@5d .. 17%@60d)
}

# --- Universe filters ---
MIN_PRICE = 0.50
MAX_PRICE = 50.00
MIN_AVG_VOLUME = 100_000  # 20-day average
MIN_MARKET_CAP = 30_000_000  # $30M — allow true micro-caps for LWLG-style setups
MAX_MARKET_CAP = 50_000_000_000  # $50B — this app hunts small/mid-cap movers, not
                                   # mega-cap blue chips; generous enough to keep
                                   # existing growth names (RBLX/SOFI/GRAB-scale)

# --- Fundamentals thresholds ---
REVENUE_GROWTH_STRONG = 0.20  # 20% YoY = max score
GROSS_MARGIN_GOOD = 0.40
CASH_RUNWAY_SAFE_QUARTERS = 4

# --- Momentum thresholds ---
RS_LOOKBACK_DAYS = 63  # ~3 months for relative strength
VOLUME_EXPANSION_LOOKBACK = 20
MA_SHORT = 20
MA_LONG = 50

# --- Market regime / edge gauges ---
REGIME_INTERVAL = 15 * 60  # seconds between market-regime refreshes
RVOL_THIN = 0.6            # relative volume below → THIN participation
RVOL_CROWDED = 2.5         # relative volume above → CROWDED (microcaps hit 2x on any news)
ER_CLEAN = 0.25            # Kaufman efficiency ratio ≥ → "clean" trend, else choppy
ATR_PCT_WILD = 7.0         # daily ATR% above → WILD volatility
ATR_PCT_QUIET = 3.0        # daily ATR% below (and low percentile) → QUIET

# --- Reddit config ---
REDDIT_CLIENT_ID = ""       # Fill in to enable Reddit scoring
REDDIT_CLIENT_SECRET = ""   # Fill in to enable Reddit scoring
REDDIT_USER_AGENT = "StockDiscovery/1.0"
REDDIT_SUBREDDITS = [
    "wallstreetbets", "stocks", "investing", "pennystocks",
    "smallstreetbets", "options", "stockmarket",
]
REDDIT_LOOKBACK_DAYS = 30

# --- SEC EDGAR ---
SEC_USER_AGENT = "StockDiscovery rubenbruijnje@gmail.com"  # SEC requires a real contact
INSIDER_LOOKBACK_DAYS = 90

# --- Output ---
TOP_N = 20  # Number of stocks to show in final ranking
MULTI_SIGNAL_THRESHOLD = 3  # Minimum buckets scoring above 60 to trigger alert

# --- Alerting ---
# "focused" (default): ONE pre-open brief with the day-movers watchlist +
#   intraday breakout triggers when a watched name actually goes. Nothing else.
#   Random pings train you to ignore them — Ruben's explicit ask (2026-07-06).
# "all": legacy firehose (high-conviction, coiled, improving, watchlist moves).
ALERT_MODE = "focused"

# --- Default universe ---
# Start with a broad small/mid-cap list. Override with a file or custom list.
DEFAULT_UNIVERSE_FILE = "universe.txt"  # One ticker per line
