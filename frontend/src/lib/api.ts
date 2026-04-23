const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "";

async function fetcher<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${url}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...options?.headers },
  });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export interface ScoreComponents {
  [key: string]: string | number;
}

export interface BucketScore {
  raw: number;
  weight: number;
  weighted: number;
  details: string;
  components: ScoreComponents;
}

export interface StockResult {
  ticker: string;
  composite: number;
  breakdown: {
    fundamentals: BucketScore;
    momentum: BucketScore;
    catalyst: BucketScore;
    insider: BucketScore;
    sentiment: BucketScore;
  };
  signals_above_60: number;
  multi_signal_alert: boolean;
  early_detection?: {
    score: number;
    components: ScoreComponents;
    details: string;
  };
  quote?: {
    price: number;
    change_pct: number;
    market_cap: number;
    volume: number;
    avg_volume: number;
    year_high: number;
    year_low: number;
    sector: string;
    industry?: string;
    name: string;
    description?: string;
  };
  ml_score?: number;
  pattern_match?: {
    score: number;
    best_match: string | null;
    matches: {
      ticker: string;
      similarity: number;
      move_pct: number;
      move_days: number;
      thesis: string;
    }[];
    details: string;
  };
  breakout?: {
    score: number;
    probability: number;
    confidence: string;
    expected_return_pct: number;
    factors: string[];
    details: string;
  };
  sector_momentum?: {
    score: number;
    catch_up_probability: number;
    expected_catch_up_pct: number;
    strong_peers: number;
    mega_peers: number;
    factors: string[];
    dominance_risk: string;
    details: string;
  };
  competitors?: {
    peers: {
      ticker: string;
      name: string;
      ret_1m: number;
      ret_3m: number;
      mcap: number;
      pct_from_high: number;
    }[];
    has_peers: boolean;
    lagging: boolean;
    peer_avg_3m: number;
    stock_3m: number;
    gap_3m: number;
    best_peer: string;
    best_peer_3m: number;
    position: string;
    biggest_competitor: {
      ticker: string;
      name: string;
      mcap: number;
      ratio: number;
    } | null;
    mcap_rank: string;
    details: string;
  };
}

export interface ScoreResponse {
  results: Record<string, Omit<StockResult, "ticker">>;
  ranked: StockResult[];
  filtered_out: { ticker: string; reason: string }[];
  alerts: string[];
}

export interface UniverseResponse {
  tickers: string[];
  sources: Record<string, string[]>;
  source_counts: Record<string, number>;
  total: number;
}

export interface ConfigResponse {
  weights: Record<string, number>;
  min_price: number;
  max_price: number;
  min_avg_volume: number;
  min_market_cap: number;
  multi_signal_threshold: number;
  top_n: number;
  reddit_configured: boolean;
}

export async function discover(options?: {
  use_yahoo?: boolean;
  use_finviz?: boolean;
  use_reddit?: boolean;
  use_sec?: boolean;
  use_rss?: boolean;
}): Promise<UniverseResponse> {
  return fetcher("/api/discover", {
    method: "POST",
    body: JSON.stringify(options || {}),
  });
}

export async function scoreTickers(
  tickers: string[],
  skipFilter = false,
  weights?: Record<string, number>
): Promise<ScoreResponse> {
  return fetcher("/api/score", {
    method: "POST",
    body: JSON.stringify({ tickers, skip_filter: skipFilter, weights }),
  });
}

export async function scoreSingle(ticker: string): Promise<StockResult> {
  return fetcher(`/api/score/${ticker}`);
}

export interface DashboardResponse {
  universe: UniverseResponse | null;
  ranked: StockResult[];
  alerts: string[];
  new_tickers: string[];
  improving: { ticker: string; old_score: number; new_score: number; change: number }[];
  last_scan: string | null;
  scan_in_progress: boolean;
  next_scan_in: number;
}

export async function getDashboard(): Promise<DashboardResponse> {
  return fetcher("/api/dashboard");
}

export async function forceScan(): Promise<{ status: string }> {
  return fetcher("/api/scan", { method: "POST" });
}

// ─── Watchlist ───
export interface WatchlistItem {
  ticker: string;
  added_date: string;
  entry_price: number | null;
  target_price: number | null;
  stop_loss: number | null;
  notes: string;
  shares: number;
  current_price: number;
  quote: { price: number; name: string; change_pct: number };
  pnl_pct: number;
  pnl_dollars: number;
  composite?: number;
  ml_score?: number;
}

export async function getWatchlist(): Promise<{ items: WatchlistItem[] }> {
  return fetcher("/api/watchlist");
}

export async function addToWatchlist(data: {
  ticker: string;
  entry_price?: number;
  target_price?: number;
  stop_loss?: number;
  notes?: string;
  shares?: number;
}): Promise<WatchlistItem> {
  return fetcher("/api/watchlist", { method: "POST", body: JSON.stringify(data) });
}

export async function removeFromWatchlist(ticker: string): Promise<{ removed: boolean }> {
  return fetcher(`/api/watchlist/${ticker}`, { method: "DELETE" });
}

// ─── Backtest ───
export interface BacktestResult {
  total_picks: number;
  avg_return: number;
  win_rate: number;
  best_picks: { ticker: string; return_pct: number; days_held: number; entry_price: number; current_price: number }[];
  worst_picks: { ticker: string; return_pct: number; days_held: number; entry_price: number; current_price: number }[];
  by_segment: Record<string, { count: number; avg_return: number; win_rate: number; best?: string }>;
  by_window: Record<string, { count: number; avg_return: number; win_rate: number }>;
  details: string;
}

export async function getBacktest(): Promise<BacktestResult> {
  return fetcher("/api/backtest");
}

export async function getConfig(): Promise<ConfigResponse> {
  return fetcher("/api/config");
}

export async function updateConfig(
  config: Partial<ConfigResponse>
): Promise<ConfigResponse> {
  return fetcher("/api/config", {
    method: "PUT",
    body: JSON.stringify(config),
  });
}
