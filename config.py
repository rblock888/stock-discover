"""Configuration for the stock discovery tool."""

# --- Scoring weights (must sum to 1.0) ---
WEIGHTS = {
    "fundamentals": 0.30,
    "momentum": 0.25,
    "catalyst": 0.20,
    "insider": 0.15,
    "sentiment": 0.10,  # Now news sentiment via yfinance
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
SEC_USER_AGENT = "StockDiscovery research@example.com"  # SEC requires identification
INSIDER_LOOKBACK_DAYS = 90

# --- Output ---
TOP_N = 20  # Number of stocks to show in final ranking
MULTI_SIGNAL_THRESHOLD = 3  # Minimum buckets scoring above 60 to trigger alert

# --- Default universe ---
# Start with a broad small/mid-cap list. Override with a file or custom list.
DEFAULT_UNIVERSE_FILE = "universe.txt"  # One ticker per line
