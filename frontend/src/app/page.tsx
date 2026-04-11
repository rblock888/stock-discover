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

type Segment = {
  title: string;
  description: string;
  color: string;
  stocks: StockResult[];
};

function segmentStocks(stocks: StockResult[]): Segment[] {
  const segments: Segment[] = [];
  const used = new Set<string>();

  function add(title: string, desc: string, color: string, filter: (s: StockResult) => boolean) {
    const matched = stocks.filter((s) => !used.has(s.ticker) && filter(s));
    if (matched.length > 0) {
      segments.push({ title, description: desc, color, stocks: matched });
      matched.forEach((s) => used.add(s.ticker));
    }
  }

  add(
    "Early Stage Potential",
    "Improving fundamentals + depressed price — catch the wave before it breaks",
    "var(--green)",
    (s) => (s.early_detection?.score ?? 0) >= 65
  );

  add(
    "Multi-Signal Alerts",
    "3+ scoring dimensions above 60 — strongest alignment",
    "var(--amber)",
    (s) => s.multi_signal_alert
  );

  add(
    "Lagging Peers",
    "Competitors already ran — this one might follow",
    "#ff9800",
    (s) => !!s.competitors?.lagging && s.competitors.gap_3m > 20
  );

  add(
    "Momentum Leaders",
    "Strong price action and relative strength",
    "var(--green-bright)",
    (s) => s.breakdown.momentum.raw >= 70
  );

  add(
    "Fundamental Strength",
    "Revenue growth, margins, and solid balance sheet",
    "var(--accent)",
    (s) => s.breakdown.fundamentals.raw >= 70
  );

  add(
    "Watchlist",
    "Moderate scores — monitoring for improvement",
    "var(--text-muted)",
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

  // Loading
  if (loading || (data?.scan_in_progress && !data?.ranked.length)) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="flex flex-col items-center gap-4">
          <div
            className="w-10 h-10 border-2 border-t-transparent rounded-full animate-spin"
            style={{ borderColor: "var(--accent)", borderTopColor: "transparent" }}
          />
          <p className="text-[13px]" style={{ color: "var(--text-secondary)" }}>
            {data?.scan_in_progress ? "Running first scan..." : "Connecting..."}
          </p>
        </div>
      </div>
    );
  }

  // Error
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
        className="sticky top-0 z-10 flex items-center justify-between h-10 px-4"
        style={{ backgroundColor: "var(--bg-surface)", borderBottom: "1px solid var(--border)" }}
      >
        <div className="flex items-center gap-3">
          <span className="text-[13px] font-semibold tracking-tight" style={{ letterSpacing: "-0.01em" }}>
            Stock Discovery
          </span>
          <span className="text-[10px]" style={{ color: "var(--text-muted)" }}>
            {data?.ranked.length ?? 0} stocks
          </span>
          {data?.scan_in_progress && (
            <span className="text-[10px] flex items-center gap-1" style={{ color: "var(--amber)" }}>
              <span className="w-1 h-1 rounded-full animate-pulse" style={{ backgroundColor: "var(--amber)" }} />
              scanning
            </span>
          )}
        </div>
        <div className="flex items-center gap-3">
          {data?.universe && <SourceBadges sources={data.universe.sources} />}
          {data?.last_scan && (
            <span className="text-[10px]" style={{ color: "var(--text-muted)" }}>
              {new Date(data.last_scan).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
              {nextMin > 0 && ` · ${nextMin}m`}
            </span>
          )}
          <button
            onClick={handleScan}
            disabled={data?.scan_in_progress}
            className="text-[10px] px-2 py-[3px] rounded transition-colors"
            style={{
              backgroundColor: "var(--bg-elevated)",
              color: "var(--text-secondary)",
              border: "1px solid var(--border)",
            }}
          >
            Scan
          </button>
        </div>
      </header>

      {/* ── Notification bars ── */}
      {data?.new_tickers && data.new_tickers.length > 0 && (
        <div
          className="h-7 px-4 flex items-center gap-2 text-[11px]"
          style={{ backgroundColor: "var(--green-dim)", borderBottom: "1px solid var(--border)" }}
        >
          <span className="font-semibold" style={{ color: "var(--green)" }}>NEW</span>
          <span style={{ color: "var(--text-secondary)" }}>{data.new_tickers.join(", ")}</span>
        </div>
      )}
      {data?.improving && data.improving.length > 0 && (
        <div
          className="h-7 px-4 flex items-center gap-2 text-[11px]"
          style={{ backgroundColor: "var(--amber-dim)", borderBottom: "1px solid var(--border)" }}
        >
          <span className="font-semibold" style={{ color: "var(--amber)" }}>IMPROVING</span>
          <span style={{ color: "var(--text-secondary)" }}>
            {data.improving.map((i) => `${i.ticker} +${i.change}`).join("  ")}
          </span>
        </div>
      )}

      {/* ── Stats row ── */}
      <div
        className="flex items-center gap-6 h-12 px-4"
        style={{ borderBottom: "1px solid var(--border)" }}
      >
        <Stat label="Discovered" value={data?.universe?.total ?? 0} />
        <Stat label="Scored" value={data?.ranked.length ?? 0} />
        <Stat label="Alerts" value={data?.alerts.length ?? 0} color="var(--amber)" />
        <Stat
          label="Early"
          value={segments.find((s) => s.title.includes("Early"))?.stocks.length ?? 0}
          color="var(--green)"
        />
        <Stat
          label="Top"
          value={data?.ranked.length ? data.ranked[0].composite.toFixed(1) : "—"}
          color="var(--green)"
        />
      </div>

      {/* ── Content ── */}
      <main className="px-4 py-5 space-y-6 max-w-[1400px] mx-auto">
        {segments.map((segment) => (
          <section key={segment.title}>
            <div className="flex items-center gap-2 mb-2">
              <span className="w-[3px] h-4 rounded-full" style={{ backgroundColor: segment.color }} />
              <h2 className="text-[13px] font-semibold" style={{ letterSpacing: "-0.01em" }}>
                {segment.title}
              </h2>
              <span className="text-[11px] tabular-nums" style={{ color: "var(--text-muted)", fontFamily: "var(--font-mono)" }}>
                {segment.stocks.length}
              </span>
              <span className="text-[10px] ml-1" style={{ color: "var(--text-muted)" }}>
                {segment.description}
              </span>
            </div>

            {segment.stocks.length <= 6 ? (
              <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-2">
                {segment.stocks.map((stock) => (
                  <StockCard key={stock.ticker} stock={stock} />
                ))}
              </div>
            ) : (
              <StockTable stocks={segment.stocks} onSelect={setSelected} />
            )}

            {selectedStock && segment.stocks.some((s) => s.ticker === selectedStock.ticker) && (
              <div className="mt-2">
                <StockCard stock={selectedStock} />
              </div>
            )}
          </section>
        ))}

        {/* Full ranking */}
        {(data?.ranked.length ?? 0) > 0 && (
          <section>
            <div className="flex items-center gap-2 mb-2">
              <span className="w-[3px] h-4 rounded-full" style={{ backgroundColor: "var(--text-muted)" }} />
              <h2 className="text-[13px] font-semibold">Full Ranking</h2>
              <span className="text-[11px] tabular-nums" style={{ color: "var(--text-muted)", fontFamily: "var(--font-mono)" }}>
                {data?.ranked.length}
              </span>
            </div>
            <StockTable stocks={data?.ranked ?? []} onSelect={setSelected} />
            {selectedStock && (
              <div className="mt-2"><StockCard stock={selectedStock} /></div>
            )}
          </section>
        )}
      </main>
    </div>
  );
}

function Stat({ label, value, color }: { label: string; value: number | string; color?: string }) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="text-[10px] uppercase tracking-[0.08em]" style={{ color: "var(--text-muted)" }}>
        {label}
      </span>
      <span
        className="text-[13px] font-bold tabular-nums"
        style={{ color: color || "var(--text-primary)", fontFamily: "var(--font-mono)" }}
      >
        {value}
      </span>
    </div>
  );
}
