const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

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
