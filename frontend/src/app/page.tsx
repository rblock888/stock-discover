"use client";

import { useEffect, useState, useCallback } from "react";
import {
  discover,
  scoreTickers,
  StockResult,
  UniverseResponse,
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

  // Multi-signal alerts (3+ buckets above 60)
  const alerts = stocks.filter((s) => s.multi_signal_alert);
  if (alerts.length > 0) {
    segments.push({
      title: "Multi-Signal Alerts",
      description: "3+ scoring dimensions above 60 — strongest alignment",
      color: "var(--amber)",
      stocks: alerts,
    });
  }

  // Momentum leaders (momentum > 70, not already in alerts)
  const alertTickers = new Set(alerts.map((s) => s.ticker));
  const momentumLeaders = stocks.filter(
    (s) =>
      !alertTickers.has(s.ticker) &&
      s.breakdown.momentum.raw >= 70
  );
  if (momentumLeaders.length > 0) {
    segments.push({
      title: "Momentum Leaders",
      description: "Strong price action and relative strength",
      color: "var(--green)",
      stocks: momentumLeaders,
    });
  }

  // Fundamental strength (fundamentals > 70, not in above)
  const usedTickers = new Set([
    ...alertTickers,
    ...momentumLeaders.map((s) => s.ticker),
  ]);
  const fundStrong = stocks.filter(
    (s) =>
      !usedTickers.has(s.ticker) &&
      s.breakdown.fundamentals.raw >= 70
  );
  if (fundStrong.length > 0) {
    segments.push({
      title: "Fundamental Strength",
      description: "Strong revenue growth, margins, and cash position",
      color: "var(--accent)",
      stocks: fundStrong,
    });
  }

  // Catalyst plays (catalyst > 65, not in above)
  const usedTickers2 = new Set([
    ...usedTickers,
    ...fundStrong.map((s) => s.ticker),
  ]);
  const catalystPlays = stocks.filter(
    (s) =>
      !usedTickers2.has(s.ticker) &&
      s.breakdown.catalyst.raw >= 65
  );
  if (catalystPlays.length > 0) {
    segments.push({
      title: "Catalyst Plays",
      description: "Upcoming earnings, analyst upgrades, or news flow",
      color: "#a78bfa",
      stocks: catalystPlays,
    });
  }

  // Insider activity (insider > 65, not in above)
  const usedTickers3 = new Set([
    ...usedTickers2,
    ...catalystPlays.map((s) => s.ticker),
  ]);
  const insiderBuying = stocks.filter(
    (s) =>
      !usedTickers3.has(s.ticker) &&
      s.breakdown.insider.raw >= 65
  );
  if (insiderBuying.length > 0) {
    segments.push({
      title: "Insider Activity",
      description: "Notable insider buying or tight ownership structure",
      color: "#22c55e",
      stocks: insiderBuying,
    });
  }

  // Social buzz (sentiment > 65, not in above)
  const usedTickers4 = new Set([
    ...usedTickers3,
    ...insiderBuying.map((s) => s.ticker),
  ]);
  const socialBuzz = stocks.filter(
    (s) =>
      !usedTickers4.has(s.ticker) &&
      s.breakdown.sentiment.raw >= 65
  );
  if (socialBuzz.length > 0) {
    segments.push({
      title: "Social Buzz",
      description: "Rising Reddit mentions with positive sentiment",
      color: "#f97316",
      stocks: socialBuzz,
    });
  }

  // Watchlist (remaining with composite > 45)
  const allUsed = new Set([
    ...usedTickers4,
    ...socialBuzz.map((s) => s.ticker),
  ]);
  const watchlist = stocks.filter(
    (s) => !allUsed.has(s.ticker) && s.composite >= 45
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

type Phase =
  | "discovering"
  | "filtering"
  | "scoring"
  | "done"
  | "error";

export default function Home() {
  const [phase, setPhase] = useState<Phase>("discovering");
  const [statusText, setStatusText] = useState("Scanning sources...");
  const [universe, setUniverse] = useState<UniverseResponse | null>(null);
  const [results, setResults] = useState<StockResult[]>([]);
  const [segments, setSegments] = useState<Segment[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<string>("");
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null);

  const runPipeline = useCallback(async () => {
    setPhase("discovering");
    setStatusText("Scanning Yahoo, Finviz, Reddit, SEC, RSS...");
    setError(null);
    setResults([]);
    setSegments([]);

    try {
      // Step 1: Discover
      const uni = await discover();
      setUniverse(uni);

      if (uni.tickers.length === 0) {
        setError("No tickers discovered from any source.");
        setPhase("error");
        return;
      }

      // Step 2: Score in small batches (5 at a time to avoid timeouts)
      setPhase("scoring");
      const toScore = uni.tickers.slice(0, 30);
      const batchSize = 5;
      const allRanked: StockResult[] = [];

      for (let i = 0; i < toScore.length; i += batchSize) {
        const batch = toScore.slice(i, i + batchSize);
        setStatusText(
          `Scoring ${i + batch.length}/${toScore.length}...`
        );

        try {
          const scoreRes = await scoreTickers(batch, true);
          allRanked.push(...scoreRes.ranked);

          // Sort and update progressively
          allRanked.sort((a, b) => b.composite - a.composite);
          setResults([...allRanked]);
          setSegments(segmentStocks([...allRanked]));
        } catch {
          // Skip failed batch, continue with rest
        }
      }

      setLastUpdated(new Date().toLocaleTimeString());
      setPhase("done");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to connect to API");
      setPhase("error");
    }
  }, []);

  // Auto-run on mount
  useEffect(() => {
    runPipeline();
  }, [runPipeline]);

  const selectedStock = selectedTicker
    ? results.find((r) => r.ticker === selectedTicker) ?? null
    : null;

  // Loading state
  if (phase === "discovering" || phase === "scoring" || phase === "filtering") {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="flex flex-col items-center gap-5">
          <div className="relative">
            <div
              className="w-16 h-16 border-[3px] border-t-transparent rounded-full animate-spin"
              style={{ borderColor: "var(--accent)", borderTopColor: "transparent" }}
            />
          </div>
          <div className="text-center">
            <h2 className="text-lg font-semibold tracking-tight mb-1">
              Stock Discovery
            </h2>
            <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
              {statusText}
            </p>
          </div>
          {universe && (
            <div className="mt-2">
              <SourceBadges sources={universe.sources} />
            </div>
          )}
        </div>
      </div>
    );
  }

  // Error state
  if (phase === "error") {
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
          <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
            {error}
          </p>
          <button
            onClick={runPipeline}
            className="px-4 py-2 rounded-md text-sm font-medium mt-2"
            style={{ backgroundColor: "var(--accent)", color: "#fff" }}
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  // Dashboard
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
            {results.length} stocks scored across {segments.length} segments
          </p>
        </div>
        <div className="flex items-center gap-4">
          {universe && <SourceBadges sources={universe.sources} />}
          <div className="flex items-center gap-2">
            <span className="text-[11px]" style={{ color: "var(--text-muted)" }}>
              Updated {lastUpdated}
            </span>
            <button
              onClick={runPipeline}
              className="px-3 py-1.5 rounded-md text-xs font-medium transition-all active:scale-[0.97]"
              style={{
                backgroundColor: "var(--bg-surface-hover)",
                color: "var(--text-secondary)",
                border: "1px solid var(--border)",
              }}
            >
              Refresh
            </button>
          </div>
        </div>
      </header>

      {/* Stats bar */}
      <div
        className="px-6 py-3 flex gap-6"
        style={{ borderBottom: "1px solid var(--border)" }}
      >
        <Stat
          label="Discovered"
          value={universe?.total ?? 0}
          suffix="tickers"
        />
        <Stat label="Scored" value={results.length} suffix="stocks" />
        <Stat
          label="Alerts"
          value={results.filter((r) => r.multi_signal_alert).length}
          color="var(--amber)"
        />
        <Stat
          label="Top Score"
          value={results.length > 0 ? results[0].composite.toFixed(1) : "—"}
          color="var(--green)"
        />
        <Stat
          label="Sources"
          value={Object.keys(universe?.sources ?? {}).length}
        />
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
                <p
                  className="text-[11px]"
                  style={{ color: "var(--text-secondary)" }}
                >
                  {segment.description}
                </p>
              </div>
            </div>

            {segment.stocks.length <= 5 ? (
              <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-3">
                {segment.stocks.map((stock) => (
                  <StockCard key={stock.ticker} stock={stock} />
                ))}
              </div>
            ) : (
              <StockTable
                stocks={segment.stocks}
                onSelect={setSelectedTicker}
              />
            )}

            {selectedStock &&
              segment.stocks.some(
                (s) => s.ticker === selectedStock.ticker
              ) && (
                <div className="mt-3">
                  <StockCard stock={selectedStock} />
                </div>
              )}
          </section>
        ))}

        {/* Full ranking at bottom */}
        <section>
          <div className="flex items-center gap-3 mb-3">
            <span
              className="w-1 h-6 rounded-full"
              style={{ backgroundColor: "var(--text-muted)" }}
            />
            <div>
              <h2 className="text-base font-semibold tracking-tight">
                Full Ranking
                <span
                  className="text-sm font-normal ml-2"
                  style={{ color: "var(--text-muted)" }}
                >
                  {results.length}
                </span>
              </h2>
              <p
                className="text-[11px]"
                style={{ color: "var(--text-secondary)" }}
              >
                All scored stocks ranked by composite score
              </p>
            </div>
          </div>
          <StockTable stocks={results} onSelect={setSelectedTicker} />
          {selectedStock && (
            <div className="mt-3">
              <StockCard stock={selectedStock} />
            </div>
          )}
        </section>
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
      <p
        className="text-[10px] uppercase tracking-[0.08em]"
        style={{ color: "var(--text-muted)" }}
      >
        {label}
      </p>
      <p className="text-lg font-bold tabular-nums" style={{ color }}>
        {value}
        {suffix && (
          <span
            className="text-[11px] font-normal ml-1"
            style={{ color: "var(--text-muted)" }}
          >
            {suffix}
          </span>
        )}
      </p>
    </div>
  );
}
