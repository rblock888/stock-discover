"use client";

import { useEffect, useState, useCallback } from "react";
import {
  getDashboard,
  forceScan,
  StockResult,
  UniverseResponse,
  DashboardResponse,
} from "@/lib/api";
import { StockTable } from "@/components/StockTable";
import { StockCard } from "@/components/StockCard";
import { SourceBadges } from "@/components/SourceBadges";

type Segment = {
  title: string;
  description: string;
  color: string;
  stocks: StockResult[];
};

function segmentStocks(stocks: StockResult[]): Segment[] {
  const segments: Segment[] = [];

  // EARLY STAGE
  const earlyStage = stocks
    .filter((s) => s.early_detection && s.early_detection.score >= 65)
    .sort((a, b) => (b.early_detection?.score ?? 0) - (a.early_detection?.score ?? 0));
  if (earlyStage.length > 0) {
    segments.push({
      title: "Early Stage Potential",
      description: "Improving fundamentals + depressed price = catch the wave before it breaks",
      color: "#22c55e",
      stocks: earlyStage,
    });
  }
  const earlyTickers = new Set(earlyStage.map((s) => s.ticker));

  // Multi-signal alerts
  const alerts = stocks.filter((s) => s.multi_signal_alert && !earlyTickers.has(s.ticker));
  if (alerts.length > 0) {
    segments.push({
      title: "Multi-Signal Alerts",
      description: "3+ scoring dimensions above 60 — strongest alignment",
      color: "var(--amber)",
      stocks: alerts,
    });
  }

  const usedTickers = new Set([...earlyTickers, ...alerts.map((s) => s.ticker)]);

  // Lagging peers (competitors ran, this one hasn't)
  const laggingPeers = stocks.filter(
    (s) => !usedTickers.has(s.ticker) && s.competitors?.lagging && s.competitors.gap_3m > 20
  );
  if (laggingPeers.length > 0) {
    segments.push({
      title: "Lagging Peers — Catch-Up Plays",
      description: "Competitors already moved, this stock hasn't — potential to follow",
      color: "#f59e0b",
      stocks: laggingPeers,
    });
  }
  const usedTickers2 = new Set([...usedTickers, ...laggingPeers.map((s) => s.ticker)]);

  // Momentum leaders
  const momentumLeaders = stocks.filter(
    (s) => !usedTickers2.has(s.ticker) && s.breakdown.momentum.raw >= 70
  );
  if (momentumLeaders.length > 0) {
    segments.push({
      title: "Momentum Leaders",
      description: "Strong price action and relative strength",
      color: "var(--green)",
      stocks: momentumLeaders,
    });
  }

  const usedTickers3 = new Set([...usedTickers2, ...momentumLeaders.map((s) => s.ticker)]);

  // Fundamental strength
  const fundStrong = stocks.filter(
    (s) => !usedTickers3.has(s.ticker) && s.breakdown.fundamentals.raw >= 70
  );
  if (fundStrong.length > 0) {
    segments.push({
      title: "Fundamental Strength",
      description: "Strong revenue growth, margins, and cash position",
      color: "var(--accent)",
      stocks: fundStrong,
    });
  }

  const usedTickers4 = new Set([...usedTickers3, ...fundStrong.map((s) => s.ticker)]);

  // Watchlist
  const watchlist = stocks.filter(
    (s) => !usedTickers4.has(s.ticker) && s.composite >= 45
  );
  if (watchlist.length > 0) {
    segments.push({
      title: "Watchlist",
      description: "Moderate scores — worth monitoring for improvement",
      color: "var(--text-secondary)",
      stocks: watchlist,
    });
  }

  return segments;
}

const REFRESH_INTERVAL = 60_000; // Check for new data every 60s

export default function Home() {
  const [data, setData] = useState<DashboardResponse | null>(null);
  const [segments, setSegments] = useState<Segment[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      const d = await getDashboard();
      setData(d);
      if (d.ranked.length > 0) {
        setSegments(segmentStocks(d.ranked));
      }
      setError(null);
      setLoading(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to connect");
      setLoading(false);
    }
  }, []);

  // Initial load
  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Auto-refresh every 60s
  useEffect(() => {
    const interval = setInterval(fetchData, REFRESH_INTERVAL);
    return () => clearInterval(interval);
  }, [fetchData]);

  async function handleForceScan() {
    await forceScan();
    // Poll until scan finishes
    const poll = setInterval(async () => {
      const d = await getDashboard();
      setData(d);
      if (!d.scan_in_progress && d.ranked.length > 0) {
        setSegments(segmentStocks(d.ranked));
        clearInterval(poll);
      }
    }, 5000);
  }

  const selectedStock = selectedTicker
    ? data?.ranked.find((r) => r.ticker === selectedTicker) ?? null
    : null;

  // Loading — scan in progress, no data yet
  if (loading || (data?.scan_in_progress && data.ranked.length === 0)) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="flex flex-col items-center gap-5">
          <div
            className="w-16 h-16 border-[3px] border-t-transparent rounded-full animate-spin"
            style={{ borderColor: "var(--accent)", borderTopColor: "transparent" }}
          />
          <div className="text-center">
            <h2 className="text-lg font-semibold tracking-tight mb-1">Stock Discovery</h2>
            <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
              {data?.scan_in_progress
                ? "First scan running — discovering and scoring stocks..."
                : "Connecting to API..."}
            </p>
          </div>
        </div>
      </div>
    );
  }

  // Error
  if (error && !data?.ranked.length) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="flex flex-col items-center gap-4 max-w-md text-center">
          <div
            className="w-14 h-14 rounded-full flex items-center justify-center text-xl"
            style={{ backgroundColor: "var(--red-dim)" }}
          >
            !
          </div>
          <h2 className="text-lg font-semibold">Connection Error</h2>
          <p className="text-sm" style={{ color: "var(--text-secondary)" }}>{error}</p>
          <button
            onClick={fetchData}
            className="px-4 py-2 rounded-md text-sm font-medium"
            style={{ backgroundColor: "var(--accent)", color: "#fff" }}
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  const nextScanMin = data?.next_scan_in ? Math.ceil(data.next_scan_in / 60) : 0;

  return (
    <div className="min-h-screen">
      {/* Top bar */}
      <header
        className="sticky top-0 z-10 px-6 py-3 flex items-center justify-between"
        style={{
          backgroundColor: "var(--bg-surface)",
          borderBottom: "1px solid var(--border)",
        }}
      >
        <div>
          <h1 className="text-base font-bold tracking-tight">Stock Discovery</h1>
          <p className="text-[11px]" style={{ color: "var(--text-muted)" }}>
            Auto-scans every 30 min
            {data?.scan_in_progress && (
              <span style={{ color: "var(--amber)" }}> — scanning now...</span>
            )}
          </p>
        </div>
        <div className="flex items-center gap-4">
          {data?.universe && <SourceBadges sources={data.universe.sources} />}
          <div className="flex items-center gap-2">
            {data?.last_scan && (
              <span className="text-[11px]" style={{ color: "var(--text-muted)" }}>
                Updated {new Date(data.last_scan).toLocaleTimeString()}
                {nextScanMin > 0 && ` · next in ${nextScanMin}m`}
              </span>
            )}
            <button
              onClick={handleForceScan}
              disabled={data?.scan_in_progress}
              className="px-3 py-1.5 rounded-md text-xs font-medium transition-all active:scale-[0.97]"
              style={{
                backgroundColor: data?.scan_in_progress ? "var(--bg-primary)" : "var(--bg-surface-hover)",
                color: data?.scan_in_progress ? "var(--text-muted)" : "var(--text-secondary)",
                border: "1px solid var(--border)",
              }}
            >
              {data?.scan_in_progress ? "Scanning..." : "Scan Now"}
            </button>
          </div>
        </div>
      </header>

      {/* Notifications */}
      {data?.new_tickers && data.new_tickers.length > 0 && (
        <div
          className="px-6 py-2 text-xs flex items-center gap-2"
          style={{ backgroundColor: "rgba(34, 197, 94, 0.08)", borderBottom: "1px solid var(--border)" }}
        >
          <span style={{ color: "#22c55e" }}>NEW</span>
          <span style={{ color: "var(--text-secondary)" }}>
            {data.new_tickers.join(", ")} appeared since last scan
          </span>
        </div>
      )}
      {data?.improving && data.improving.length > 0 && (
        <div
          className="px-6 py-2 text-xs flex items-center gap-2"
          style={{ backgroundColor: "var(--amber-dim)", borderBottom: "1px solid var(--border)" }}
        >
          <span style={{ color: "var(--amber)" }}>IMPROVING</span>
          <span style={{ color: "var(--text-secondary)" }}>
            {data.improving.map((i) => `${i.ticker} +${i.change}`).join(", ")}
          </span>
        </div>
      )}

      {/* Stats bar */}
      <div
        className="px-6 py-3 flex gap-6"
        style={{ borderBottom: "1px solid var(--border)" }}
      >
        <Stat label="Discovered" value={data?.universe?.total ?? 0} suffix="tickers" />
        <Stat label="Scored" value={data?.ranked.length ?? 0} suffix="stocks" />
        <Stat
          label="Alerts"
          value={data?.alerts.length ?? 0}
          color="var(--amber)"
        />
        <Stat
          label="Early Stage"
          value={segments.find((s) => s.title.includes("Early"))?.stocks.length ?? 0}
          color="#22c55e"
        />
        <Stat
          label="Top Score"
          value={data?.ranked.length ? data.ranked[0].composite.toFixed(1) : "—"}
          color="var(--green)"
        />
        <Stat label="Sources" value={Object.keys(data?.universe?.sources ?? {}).length} />
      </div>

      {/* Segments */}
      <main className="px-6 py-6 space-y-8">
        {segments.map((segment) => (
          <section key={segment.title}>
            <div className="flex items-center gap-3 mb-3">
              <span
                className="w-1 h-6 rounded-full"
                style={{ backgroundColor: segment.color }}
              />
              <div>
                <h2 className="text-base font-semibold tracking-tight">
                  {segment.title}
                  <span
                    className="text-sm font-normal ml-2"
                    style={{ color: "var(--text-muted)" }}
                  >
                    {segment.stocks.length}
                  </span>
                </h2>
                <p className="text-[11px]" style={{ color: "var(--text-secondary)" }}>
                  {segment.description}
                </p>
              </div>
            </div>

            {segment.stocks.length <= 6 ? (
              <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-3">
                {segment.stocks.map((stock) => (
                  <StockCard key={stock.ticker} stock={stock} />
                ))}
              </div>
            ) : (
              <StockTable stocks={segment.stocks} onSelect={setSelectedTicker} />
            )}

            {selectedStock && segment.stocks.some((s) => s.ticker === selectedStock.ticker) && (
              <div className="mt-3">
                <StockCard stock={selectedStock} />
              </div>
            )}
          </section>
        ))}

        {/* Full ranking */}
        {(data?.ranked.length ?? 0) > 0 && (
          <section>
            <div className="flex items-center gap-3 mb-3">
              <span className="w-1 h-6 rounded-full" style={{ backgroundColor: "var(--text-muted)" }} />
              <div>
                <h2 className="text-base font-semibold tracking-tight">
                  Full Ranking
                  <span className="text-sm font-normal ml-2" style={{ color: "var(--text-muted)" }}>
                    {data?.ranked.length}
                  </span>
                </h2>
                <p className="text-[11px]" style={{ color: "var(--text-secondary)" }}>
                  All scored stocks ranked by composite score
                </p>
              </div>
            </div>
            <StockTable stocks={data?.ranked ?? []} onSelect={setSelectedTicker} />
            {selectedStock && (
              <div className="mt-3">
                <StockCard stock={selectedStock} />
              </div>
            )}
          </section>
        )}
      </main>
    </div>
  );
}

function Stat({
  label,
  value,
  suffix,
  color,
}: {
  label: string;
  value: number | string;
  suffix?: string;
  color?: string;
}) {
  return (
    <div>
      <p className="text-[10px] uppercase tracking-[0.08em]" style={{ color: "var(--text-muted)" }}>
        {label}
      </p>
      <p className="text-lg font-bold tabular-nums" style={{ color }}>
        {value}
        {suffix && (
          <span className="text-[11px] font-normal ml-1" style={{ color: "var(--text-muted)" }}>
            {suffix}
          </span>
        )}
      </p>
    </div>
  );
}
