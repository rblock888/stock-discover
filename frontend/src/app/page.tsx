"use client";

import { useEffect, useState, useCallback } from "react";
import {
  getDashboard,
  forceScan,
  StockResult,
  DashboardResponse,
} from "@/lib/api";
import { StockTable } from "@/components/StockTable";
import { StockCard } from "@/components/StockCard";
import { SourceBadges } from "@/components/SourceBadges";
import { WatchlistPanel } from "@/components/WatchlistPanel";
import { BacktestPanel } from "@/components/BacktestPanel";

type Segment = {
  title: string;
  subtitle: string;
  color: string;
  stocks: StockResult[];
  view: "hero" | "cards" | "table";
};

function segmentStocks(stocks: StockResult[]): Segment[] {
  const segments: Segment[] = [];
  const used = new Set<string>();

  function add(title: string, sub: string, color: string, view: Segment["view"], filter: (s: StockResult) => boolean) {
    const matched = stocks.filter((s) => !used.has(s.ticker) && filter(s));
    if (matched.length > 0) {
      segments.push({ title, subtitle: sub, color, view, stocks: matched });
      matched.forEach((s) => used.add(s.ticker));
    }
  }

  // AI top picks — highest ML score
  const aiPicks = [...stocks]
    .filter((s) => (s.ml_score ?? 0) >= 55)
    .sort((a, b) => (b.ml_score ?? 0) - (a.ml_score ?? 0))
    .slice(0, 3);
  if (aiPicks.length > 0) {
    segments.push({
      title: "AI Top Picks",
      subtitle: "Highest probability setups based on historical pattern matching and breakout models",
      color: "var(--accent)",
      view: "hero",
      stocks: aiPicks,
    });
    aiPicks.forEach((s) => used.add(s.ticker));
  }

  // Asymmetric Upside — micro/small caps with strong data (the LWLG hunter)
  const asymmetric = [...stocks]
    .filter((s) => {
      if (used.has(s.ticker)) return false;
      const mcap = s.quote?.market_cap ?? 0;
      const isSmall = mcap > 0 && mcap < 500_000_000;
      const hasSignal =
        (s.ml_score ?? 0) >= 50 ||
        (s.early_detection?.score ?? 0) >= 65 ||
        s.composite >= 55;
      const hasFundamentals = s.breakdown.fundamentals.raw >= 50;
      return isSmall && hasSignal && hasFundamentals;
    })
    .sort((a, b) => {
      // Sort by combined: ml_score + early_detection + inverse mcap
      const aScore = (a.ml_score ?? 0) + (a.early_detection?.score ?? 0) * 0.5;
      const bScore = (b.ml_score ?? 0) + (b.early_detection?.score ?? 0) * 0.5;
      return bScore - aScore;
    })
    .slice(0, 6);
  if (asymmetric.length > 0) {
    segments.push({
      title: "Asymmetric Upside",
      subtitle: "Sub-$500M cap with improving fundamentals — LWLG-style rerating candidates",
      color: "#e11d48",
      view: asymmetric.length <= 3 ? "hero" : "cards",
      stocks: asymmetric,
    });
    asymmetric.forEach((s) => used.add(s.ticker));
  }

  // Top 3 picks — biggest hero cards
  const topPicks = [...stocks]
    .filter((s) => !used.has(s.ticker) && (s.composite >= 55 || (s.early_detection?.score ?? 0) >= 65))
    .slice(0, 3);
  if (topPicks.length > 0) {
    segments.push({
      title: "Top Picks Right Now",
      subtitle: "Strongest overall alignment across all scoring dimensions",
      color: "var(--accent)",
      view: "hero",
      stocks: topPicks,
    });
    topPicks.forEach((s) => used.add(s.ticker));
  }

  add(
    "Early-Stage Setups",
    "Improving fundamentals, price hasn't moved yet",
    "var(--green)",
    "cards",
    (s) => (s.early_detection?.score ?? 0) >= 65
  );

  add(
    "Lagging Peers",
    "Sector moved, these didn't — catch-up candidates",
    "#ff9800",
    "cards",
    (s) => !!s.competitors?.lagging && s.competitors.gap_3m > 20
  );

  add(
    "Momentum Leaders",
    "Strong relative strength and breakout patterns",
    "var(--green-bright)",
    "cards",
    (s) => s.breakdown.momentum.raw >= 70
  );

  add(
    "Hidden Fundamentals",
    "Revenue growth and strong balance sheet",
    "var(--accent)",
    "cards",
    (s) => s.breakdown.fundamentals.raw >= 70
  );

  add(
    "Watchlist",
    "Moderate scores worth monitoring",
    "var(--text-muted)",
    "table",
    (s) => s.composite >= 40
  );

  return segments;
}

export default function Home() {
  const [data, setData] = useState<DashboardResponse | null>(null);
  const [segments, setSegments] = useState<Segment[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      const d = await getDashboard();
      setData(d);
      if (d.ranked.length > 0) setSegments(segmentStocks(d.ranked));
      setError(null);
      setLoading(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to connect");
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);
  useEffect(() => {
    const i = setInterval(fetchData, 60_000);
    return () => clearInterval(i);
  }, [fetchData]);

  async function handleScan() {
    await forceScan();
    const poll = setInterval(async () => {
      const d = await getDashboard();
      setData(d);
      if (!d.scan_in_progress && d.ranked.length > 0) {
        setSegments(segmentStocks(d.ranked));
        clearInterval(poll);
      }
    }, 5000);
  }

  const selectedStock = selected ? data?.ranked.find((r) => r.ticker === selected) ?? null : null;

  if (loading || (data?.scan_in_progress && !data?.ranked.length)) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="flex flex-col items-center gap-4">
          <div
            className="w-10 h-10 border-2 border-t-transparent rounded-full animate-spin"
            style={{ borderColor: "var(--accent)", borderTopColor: "transparent" }}
          />
          <p className="text-[13px]" style={{ color: "var(--text-secondary)" }}>
            {data?.scan_in_progress ? "Running scan..." : "Connecting..."}
          </p>
        </div>
      </div>
    );
  }

  if (error && !data?.ranked.length) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="text-center">
          <p className="text-[13px] mb-3" style={{ color: "var(--red)" }}>{error}</p>
          <button
            onClick={fetchData}
            className="px-3 py-1.5 rounded text-[12px]"
            style={{ backgroundColor: "var(--accent)", color: "#fff" }}
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  const nextMin = data?.next_scan_in ? Math.ceil(data.next_scan_in / 60) : 0;

  return (
    <div className="min-h-screen">
      {/* ── Top bar ── */}
      <header
        className="sticky top-0 z-20 flex items-center justify-between h-12 px-5"
        style={{ backgroundColor: "var(--bg-surface)", borderBottom: "1px solid var(--border)" }}
      >
        <div className="flex items-center gap-3">
          <div className="w-5 h-5 rounded" style={{ background: "linear-gradient(135deg, var(--accent), var(--green))" }} />
          <div>
            <h1 className="text-[13px] font-semibold tracking-tight">Stock Discovery</h1>
            <p className="text-[10px]" style={{ color: "var(--text-muted)" }}>
              {data?.ranked.length ?? 0} stocks tracked · auto-scan every 30 min
            </p>
          </div>
          {data?.scan_in_progress && (
            <span className="text-[10px] flex items-center gap-1" style={{ color: "var(--amber)" }}>
              <span className="w-1.5 h-1.5 rounded-full animate-pulse" style={{ backgroundColor: "var(--amber)" }} />
              scanning
            </span>
          )}
        </div>
        <div className="flex items-center gap-3">
          {data?.universe && <SourceBadges sources={data.universe.sources} />}
          {data?.last_scan && (
            <span className="text-[10px]" style={{ color: "var(--text-muted)" }}>
              {new Date(data.last_scan).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
              {nextMin > 0 && ` · next ${nextMin}m`}
            </span>
          )}
          <button
            onClick={handleScan}
            disabled={data?.scan_in_progress}
            className="text-[11px] px-3 py-1 rounded transition-colors"
            style={{
              backgroundColor: "var(--bg-elevated)",
              color: "var(--text-secondary)",
              border: "1px solid var(--border)",
            }}
          >
            Scan Now
          </button>
        </div>
      </header>

      {/* ── Notifications ── */}
      {data?.new_tickers && data.new_tickers.length > 0 && (
        <div className="h-7 px-5 flex items-center gap-2 text-[11px]" style={{ backgroundColor: "var(--green-dim)", borderBottom: "1px solid var(--border)" }}>
          <span className="font-bold" style={{ color: "var(--green)" }}>NEW</span>
          <span style={{ color: "var(--text-secondary)" }}>{data.new_tickers.join(", ")}</span>
        </div>
      )}
      {data?.improving && data.improving.length > 0 && (
        <div className="h-7 px-5 flex items-center gap-2 text-[11px]" style={{ backgroundColor: "var(--amber-dim)", borderBottom: "1px solid var(--border)" }}>
          <span className="font-bold" style={{ color: "var(--amber)" }}>IMPROVING</span>
          <span style={{ color: "var(--text-secondary)" }}>
            {data.improving.map((i) => `${i.ticker} +${i.change}`).join("  ")}
          </span>
        </div>
      )}

      {/* ── Content ── */}
      <main className="max-w-[1400px] mx-auto px-5 py-6 space-y-8">
        {/* Watchlist + Backtest top row */}
        <section className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <WatchlistPanel />
          <BacktestPanel />
        </section>

        {segments.map((segment) => (
          <section key={segment.title}>
            <div className="flex items-baseline gap-3 mb-4">
              <span className="w-[3px] h-5 rounded-full" style={{ backgroundColor: segment.color }} />
              <h2 className="text-[16px] font-semibold tracking-tight" style={{ letterSpacing: "-0.02em" }}>
                {segment.title}
              </h2>
              <span className="text-[12px] tabular-nums" style={{ color: "var(--text-muted)", fontFamily: "var(--font-mono)" }}>
                {segment.stocks.length}
              </span>
              <span className="text-[11px]" style={{ color: "var(--text-muted)" }}>
                {segment.subtitle}
              </span>
            </div>

            {segment.view === "hero" ? (
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
                {segment.stocks.map((stock) => (
                  <StockCard key={stock.ticker} stock={stock} />
                ))}
              </div>
            ) : segment.view === "cards" ? (
              <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-3">
                {segment.stocks.map((stock) => (
                  <StockCard key={stock.ticker} stock={stock} />
                ))}
              </div>
            ) : (
              <StockTable stocks={segment.stocks} onSelect={setSelected} />
            )}

            {selectedStock && segment.stocks.some((s) => s.ticker === selectedStock.ticker) && (
              <div className="mt-3">
                <StockCard stock={selectedStock} />
              </div>
            )}
          </section>
        ))}
      </main>
    </div>
  );
}
