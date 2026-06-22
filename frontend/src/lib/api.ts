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

export interface ShortSqueezeResult {
  score: number;
  level: "extreme" | "high" | "moderate" | "low";
  short_pct_float: number;
  days_to_cover: number;
  float_shares: number;
  shares_short: number;
  components: ScoreComponents;
  details: string;
}

export interface EdgeGauge {
  state: string;
  score: number;
  summary: string;
  advice: string[];
  rvol?: number;
  er?: number;
  slope10_pct?: number;
  atr_pct?: number;
  atr_pctile?: number;
}

export interface EdgeBlock {
  available: boolean;
  above_20ma: boolean | null;
  flow?: EdgeGauge;
  bearing?: EdgeGauge;
  pulse?: EdgeGauge;
}

export interface RegimeTilt {
  factor: number;
  reasons: string[];
}

export interface CoiledBlock {
  available: boolean;
  coiled_score: number;
  state: "COILED" | "BASING" | "EXTENDED" | "NO SETUP" | "UNKNOWN";
  summary?: string;
  squeeze_pctile?: number;
  range_pct?: number;
  ext_pct?: number;
  ret_3m_pct?: number;
  pivot_prox?: number;
  reasons?: string[];
}

export interface StockResult {
  ticker: string;
  composite: number;
  edge?: EdgeBlock;
  coiled?: CoiledBlock;
  calibrated_p_win?: number | null;
  tilt?: RegimeTilt;
  rank_score?: number;
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
  short_squeeze?: ShortSqueezeResult;
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

export interface ScoreDelta {
  ticker: string;
  old_score: number;
  new_score: number;
  change: number;
}

export interface DashboardResponse {
  universe: UniverseResponse | null;
  ranked: StockResult[];
  alerts: string[];
  new_tickers: string[];
  improving: ScoreDelta[];
  decaying: ScoreDelta[];
  breadth: { pct_above_20ma: number | null; n: number } | null;
  market_regime: { score: number; label: string; vix: number; as_of: string } | null;
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

// ─── AXT Microcap Filter ───

export interface AxtFilter {
  score: number;
  label: string;
  pass: boolean;
  hits?: string[];
}

export interface AxtResult {
  ticker: string;
  name: string;
  rerate_score: number;
  stack_layer: string;
  filters: {
    stack_position: AxtFilter;
    market_cap: AxtFilter;
    revenue_profile: AxtFilter;
    supply_chain: AxtFilter;
    capacity_signal: AxtFilter;
  };
  filters_passed: number;
  is_candidate: boolean;
  narrative_penalty: number;
  narrative_hits: string[];
  supply_hits: string[];
  capacity_hits: string[];
  market_cap: number;
  sector: string;
  industry: string;
  price: number;
}

export interface AxtScanResponse {
  results: AxtResult[];
  candidates: AxtResult[];
  last_scan: string | null;
  scan_in_progress: boolean;
  seed_universe: string[];
}

export async function getAxtScan(): Promise<AxtScanResponse> {
  return fetcher("/api/axt-scan");
}

export async function runAxtScan(tickers?: string[]): Promise<{ status: string }> {
  return fetcher("/api/axt-scan", {
    method: "POST",
    body: JSON.stringify({ tickers: tickers ?? null }),
  });
}

export async function axtScoreSingle(ticker: string): Promise<AxtResult> {
  return fetcher(`/api/axt-scan/${ticker}`);
}

// ─── Photonics Cycle ───

export interface PhaseFilter {
  score: number;
  pass: boolean;
  label: string;
}

export interface PhaseResult {
  ticker: string;
  name: string;
  phase_score: number;
  filters: {
    stack: PhaseFilter;
    mcap: PhaseFilter;
    revenue: PhaseFilter;
    supply: PhaseFilter;
    capacity: PhaseFilter;
  };
  filters_passed: number;
  is_candidate: boolean;
  supply_hits: string[];
  capacity_hits: string[];
  narrative_penalty: number;
  market_cap: number;
  sector: string;
  industry: string;
  price: number;
}

export interface CyclePhase {
  id: string;
  num: number;
  name: string;
  layer: string;
  timeline: string;
  status: "in_progress" | "emerging" | "current" | "upcoming" | "future";
  asymmetry: "medium" | "high" | "very_high";
  color: string;
  description: string;
  results: PhaseResult[];
  candidates: PhaseResult[];
}

export interface PhotonicsCycleResponse {
  current_phase_num: number;
  phases: CyclePhase[];
  last_scan: string | null;
  scan_in_progress: boolean;
}

export async function getPhotonicsCycle(): Promise<PhotonicsCycleResponse> {
  return fetcher("/api/photonics-cycle");
}

export async function rescanPhotonicsCycle(): Promise<{ status: string }> {
  return fetcher("/api/photonics-cycle/rescan", { method: "POST" });
}

// ─── Squeeze Discovery ───

export interface SqueezeCandidate {
  ticker: string;
  name: string;
  price: number;
  change_pct: number;
  sector: string;
  market_cap: number;
  score: number;
  level: "extreme" | "high" | "moderate" | "low";
  short_pct_float: number;
  days_to_cover: number;
  float_shares: number;
  shares_short: number;
  components: Record<string, string>;
  details: string;
}

export interface SqueezeScanResponse {
  results: SqueezeCandidate[];
  candidates: SqueezeCandidate[];
  last_scan: string | null;
  scan_in_progress: boolean;
}

export async function getSqueezeScan(): Promise<SqueezeScanResponse> {
  return fetcher("/api/squeeze-scan");
}

export async function rescanSqueeze(): Promise<{ status: string }> {
  return fetcher("/api/squeeze-scan/rescan", { method: "POST" });
}

// ─── Market Regime ───

export interface IndexTrend {
  state: "UPTREND" | "PULLBACK" | "RECOVERY" | "DOWNTREND" | "CHOP";
  points: number;
  close: number;
  vs_20ma_pct: number;
  ret_1m_pct: number | null;
}

export interface SectorHeat {
  etf: string;
  name: string;
  ret_1m_pct: number | null;
  ret_5d_pct: number | null;
  above_20ma: boolean;
}

export interface RegimeStripDay {
  snap_date: string;
  mood_score: number;
  label: string;
  vix: number;
}

export interface MarketRegimeResponse {
  available: boolean;
  as_of?: string;
  stale?: boolean;
  mood?: { score: number; label: "RISK-ON" | "NEUTRAL" | "RISK-OFF" };
  indices?: Record<string, IndexTrend>;
  volatility?: { state: "QUIET" | "TRADABLE" | "WILD"; vix: number; percentile: number; change_5d_pct: number | null; score: number };
  smallcap?: { state: "HOT" | "NEUTRAL" | "COLD"; score: number; rel_1m_pct: number | null; rel_3m_pct: number | null };
  sectors?: SectorHeat[];
  breadth?: { universe_pct: number | null; universe_n: number | null; sectors_pct: number };
  narrative?: string;
  advice?: string[];
  strip?: RegimeStripDay[];
}

export async function getMarketRegime(): Promise<MarketRegimeResponse> {
  return fetcher("/api/market-regime");
}

// ─── Daily Brief ───

export interface BriefBullet {
  type: "new" | "improving" | "decaying" | "squeeze" | "pick" | "watchlist";
  text: string;
}

export interface Brief {
  headline: string;
  paragraph: string;
  bullets: BriefBullet[];
  generated_at: string;
  source: "template" | "llm";
}

export async function getBrief(): Promise<{ brief: Brief | null; last_scan: string | null }> {
  return fetcher("/api/brief");
}

// ─── Score history ───

export interface HistoryPoint {
  scan_date: string;
  composite: number | null;
  ml_score: number | null;
  price: number | null;
}

export interface HistoryResponse {
  ticker: string;
  points: HistoryPoint[];
  count: number;
}

export async function getHistory(ticker: string): Promise<HistoryResponse> {
  return fetcher(`/api/history/${ticker}`);
}

export interface PriceHistory {
  ticker: string;
  points: { date: string; close: number }[];
}

export async function getPriceHistory(ticker: string): Promise<PriceHistory> {
  return fetcher(`/api/price-history/${ticker}`);
}

// ─── Model Scorecard (closed-loop evaluation) ───

export interface ScoreDecile {
  bin: number;
  score_lo: number;
  score_hi: number;
  n: number;
  avg_return_pct: number;
  avg_excess_pct: number | null;
  win_rate: number;
  beat_spy_rate: number | null;
}

export interface SignalCard {
  ic: number;
  ic_excess: number | null;
  n: number;
  deciles: ScoreDecile[];
  top_minus_bottom_pct: number;
  top_win_rate: number;
  bottom_win_rate: number;
}

export interface Scorecard {
  available: boolean;
  horizon: number;
  n: number;
  overall_avg_return_pct?: number;
  overall_win_rate?: number;
  overall_beat_spy_rate?: number | null;
  signals?: Record<string, SignalCard>;
  detail?: string;
}

export interface CalibrationCurve {
  available: boolean;
  signal?: string;
  horizon?: number;
  win_threshold?: number;
  n?: number;
  base_rate?: number;
  curve?: { score: number; p_win: number; n: number }[];
}

export interface DataStatus {
  tickers_scored: number;
  tickers_with_price_history: number;
  junk_tickers: number;
  trading_days_deep: number;
  first_day: string | null;
  last_day: string | null;
  resolved_by_horizon: Record<string, number>;
  horizons: number[];
}

export interface EvidenceWeights {
  available: boolean;
  status: "ready" | "accruing";
  n: number;
  need?: number;
  horizon: number;
  bucket_ic?: Record<string, number>;
  current_weights: Record<string, number>;
  recommended_weights?: Record<string, number>;
  detail: string;
}

export interface TiltAB {
  available: boolean;
  status: "ready" | "accruing";
  n: number;
  moved?: number;
  need?: number;
  horizon: number;
  ic_base?: number;
  ic_tilt?: number;
  ic_delta?: number;
  top_quartile_base_pct?: number;
  top_quartile_tilt_pct?: number;
  tilt_helps?: boolean;
  detail: string;
}

export interface ScorecardResponse {
  scorecards: Record<string, Scorecard> | null;
  data_status: DataStatus;
  last_run: string | null;
  calibration: Record<string, CalibrationCurve>;
  evidence_weights?: EvidenceWeights;
  tilt_ab?: TiltAB;
}

export async function getScorecard(): Promise<ScorecardResponse> {
  return fetcher("/api/scorecard");
}
