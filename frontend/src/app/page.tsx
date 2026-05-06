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
import { ManualLookup } from "@/components/ManualLookup";
import { PhotonicsCycle } from "@/components/PhotonicsCycle";

// ─── Types ───────────────────────────────────────────────────────────────────

type Tab = "picks" | "squeeze" | "photonics" | "portfolio" | "tools";

type Segment = {
  id: string;
  title: string;
  subtitle: string;
  color: string;
  stocks: StockResult[];
};

// ─── Stock segmentation ───────────────────────────────────────────────────────

function buildSegments(stocks: StockResult[]): Segment[] {
  const used = new Set<string>();
  const segs: Segment[] = [];

  function take(
    id: string,
    title: string,
    subtitle: string,
    color: string,
    filter: (s: StockResult) => boolean,
    sort?: (a: StockResult, b: StockResult) => number,
    limit = 6,
  ) {
    let matched = stocks.filter((s) => !used.has(s.ticker) && filter(s));
    if (sort) matched = matched.sort(sort);
    matched = matched.slice(0, limit);
    if (matched.length) {
      segs.push({ id, title, subtitle, color, stocks: matched });
      matched.forEach((s) => used.add(s.ticker));
    }
  }

  take(
    "squeeze",
    "Squeeze Setups",
    "High short float · trapped DTC · catalyst incoming",
    "#ec4899",
    (s) => (s.short_squeeze?.score ?? 0) >= 60,
    (a, b) => (b.short_squeeze?.score ?? 0) - (a.short_squeeze?.score ?? 0),
  );

  take(
    "asymmetric",
    "Asymmetric Upside",
    "Sub-$500M · improving fundamentals · price hasn't moved",
    "#e11d48",
    (s) => {
      const mc = s.quote?.market_cap ?? 0;
      return (
        mc > 0 &&
        mc < 500_000_000 &&
        s.breakdown.fundamentals.raw >= 50 &&
        ((s.ml_score ?? 0) >= 50 ||
          (s.early_detection?.score ?? 0) >= 65 ||
          s.composite >= 55)
      );
    },
    (a, b) =>
      (b.ml_score ?? 0) +
      (b.early_detection?.score ?? 0) * 0.5 -
      ((a.ml_score ?? 0) + (a.early_detection?.score ?? 0) * 0.5),
  );

  take(
    "ai",
    "AI Top Picks",
    "Pattern match + breakout probability",
    "var(--accent)",
    (s) => (s.ml_score ?? 0) >= 55,
    (a, b) => (b.ml_score ?? 0) - (a.ml_score ?? 0),
    3,
  );

  take(
    "early",
    "Early Stage",
    "Fundamentals improving · price not yet moved",
    "var(--green)",
    (s) => (s.early_detection?.score ?? 0) >= 65,
    (a, b) => (b.early_detection?.score ?? 0) - (a.early_detection?.score ?? 0),
  );

  take(
    "lagging",
    "Lagging Peers",
    "Sector ran · these didn't · catch-up play",
    "#ff9800",
    (s) => !!s.competitors?.lagging && s.competitors.gap_3m > 20,
    (a, b) => (b.competitors?.gap_3m ?? 0) - (a.competitors?.gap_3m ?? 0),
  );

  take(
    "momentum",
    "Momentum",
    "Strong RS · breakout patterns",
    "var(--green-bright)",
    (s) => s.breakdown.momentum.raw >= 70,
    (a, b) => b.breakdown.momentum.raw - a.breakdown.momentum.raw,
  );

  take(
    "fundamentals",
    "Hidden Fundamentals",
    "Revenue growth · strong balance sheet · ignored",
    "var(--accent)",
    (s) => s.breakdown.fundamentals.raw >= 70,
    (a, b) => b.breakdown.fundamentals.raw - a.breakdown.fundamentals.raw,
  );

  return segs;
}

// ─── Segment block ────────────────────────────────────────────────────────────

function SegmentBlock({
  seg,
  cols = 2,
  maxCards = 4,
}: {
  seg: Segment;
  cols?: 1 | 2 | 3;
  maxCards?: number;
}) {
  const [expanded, setExpanded] = useState(false);
  const visible = expanded ? seg.stocks : seg.stocks.slice(0, maxCards);
  const hasMore = seg.stocks.length > maxCards;

  const gridCols =
    cols === 3
      ? "grid-cols-1 lg:grid-cols-3"
      : cols === 2
        ? "grid-cols-1 lg:grid-cols-2"
        : "grid-cols-1";

  return (
    <div>
      <div className="flex items-baseline gap-2 mb-3">
        <span
          className="w-[3px] h-[18px] rounded-full shrink-0"
          style={{ backgroundColor: seg.color }}
        />
        <span
          className="text-[14px] font-semibold"
          style={{ letterSpacing: "-0.02em" }}
        >
          {seg.title}
        </span>
        <span
          className="text-[11px] tabular-nums"
          style={{ color: "var(--text-muted)", fontFamily: "var(--font-mono)" }}
        >
          {seg.stocks.length}
        </span>
        <span className="text-[11px]" style={{ color: "var(--text-muted)" }}>
          {seg.subtitle}
        </span>
      </div>
      <div className={`grid ${gridCols} gap-3`}>
        {visible.map((s) => (
          <StockCard key={s.ticker} stock={s} />
        ))}
      </div>
      {hasMore && (
        <button
          onClick={() => setExpanded(!expanded)}
          className="mt-2 text-[11px] px-3 py-1 rounded transition-colors"
          style={{
            color: "var(--text-muted)",
            border: "1px solid var(--border)",
          }}
        >
          {expanded
            ? "Show less"
            : `Show ${seg.stocks.length - maxCards} more`}
        </button>
      )}
    </div>
  );
}

// ─── Tab views ────────────────────────────────────────────────────────────────

function PicksView({
  segments,
  ranked,
}: {
  segments: Segment[];
  ranked: StockResult[];
}) {
  const [selected, setSelected] = useState<string | null>(null);
  const selectedStock = selected
    ? ranked.find((r) => r.ticker === selected) ?? null
    : null;

  // Group segments into layout rows
  const squeeze = segments.find((s) => s.id === "squeeze");
  const asymmetric = segments.find((s) => s.id === "asymmetric");
  const ai = segments.find((s) => s.id === "ai");
  const rest = segments.filter(
    (s) => !["squeeze", "asymmetric", "ai"].includes(s.id),
  );
  // Everything else (early, lagging, momentum, fundamentals) shown as pairs
  const pairs: [Segment, Segment | undefined][] = [];
  for (let i = 0; i < rest.length; i += 2) {
    pairs.push([rest[i], rest[i + 1]]);
  }

  // Tail — stocks with composite >= 40 not already shown
  const shownTickers = new Set(segments.flatMap((s) => s.stocks.map((x) => x.ticker)));
  const tailStocks = ranked.filter(
    (s) => !shownTickers.has(s.ticker) && s.composite >= 40,
  );

  return (
    <div className="p-5 space-y-8 max-w-[1200px]">
      {/* Row 1: Squeeze (left) + Asymmetric (right) */}
      {(squeeze || asymmetric) && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {squeeze && <SegmentBlock seg={squeeze} cols={1} maxCards={2} />}
          {asymmetric && <SegmentBlock seg={asymmetric} cols={1} maxCards={2} />}
        </div>
      )}

      {/* Row 2: AI Picks full width — 3 col */}
      {ai && <SegmentBlock seg={ai} cols={3} maxCards={3} />}

      {/* Row 3+: Rest in pairs side by side */}
      {pairs.map(([left, right], i) => (
        <div key={i} className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <SegmentBlock seg={left} cols={1} maxCards={2} />
          {right && <SegmentBlock seg={right} cols={1} maxCards={2} />}
        </div>
      ))}

      {/* Tail table */}
      {tailStocks.length > 0 && (
        <div>
          <div className="flex items-baseline gap-2 mb-3">
            <span
              className="w-[3px] h-[18px] rounded-full shrink-0"
              style={{ backgroundColor: "var(--text-muted)" }}
            />
            <span
              className="text-[14px] font-semibold"
              style={{ letterSpacing: "-0.02em" }}
            >
              On Watch
            </span>
            <span
              className="text-[11px]"
              style={{ color: "var(--text-muted)", fontFamily: "var(--font-mono)" }}
            >
              {tailStocks.length}
            </span>
          </div>
          <StockTable stocks={tailStocks} onSelect={setSelected} />
          {selectedStock && (
            <div className="mt-3">
              <StockCard stock={selectedStock} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function SqueezeView({ segments }: { segments: Segment[] }) {
  const squeeze = segments.find((s) => s.id === "squeeze");
  if (!squeeze?.stocks.length) {
    return (
      <div className="p-5 flex items-center justify-center h-64 text-[13px]" style={{ color: "var(--text-muted)" }}>
        No squeeze setups detected in the current scan universe.
      </div>
    );
  }
  return (
    <div className="p-5 space-y-4 max-w-[1200px]">
      {/* Squeeze-specific metric table */}
      <div className="rounded-lg overflow-hidden" style={{ border: "1px solid var(--border)" }}>
        <table className="w-full border-collapse">
          <thead>
            <tr style={{ backgroundColor: "var(--bg-surface)", borderBottom: "1px solid var(--border)" }}>
              {["Ticker", "Short Float", "Days to Cover", "Float", "Level", "Squeeze Score", "Catalyst", "Insider"].map((h) => (
                <th key={h} className="px-3 py-2 text-left text-[9px] uppercase tracking-[0.08em] font-medium" style={{ color: "var(--text-muted)" }}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {squeeze.stocks.map((s) => {
              const sq = s.short_squeeze;
              if (!sq) return null;
              return (
                <tr key={s.ticker} style={{ borderBottom: "1px solid var(--border)" }} className="hover:bg-[var(--bg-elevated)]">
                  <td className="px-3 py-2">
                    <div className="font-bold text-[13px]">{s.ticker}</div>
                    <div className="text-[10px] truncate max-w-[120px]" style={{ color: "var(--text-muted)" }}>{s.quote?.name ?? ""}</div>
                  </td>
                  <td className="px-3 py-2 tabular-nums font-bold text-[13px]" style={{ color: "#ec4899", fontFamily: "var(--font-mono)" }}>
                    {sq.short_pct_float > 0 ? `${sq.short_pct_float}%` : "—"}
                  </td>
                  <td className="px-3 py-2 tabular-nums font-bold text-[13px]" style={{ color: sq.days_to_cover >= 20 ? "#ec4899" : "var(--amber)", fontFamily: "var(--font-mono)" }}>
                    {sq.days_to_cover > 0 ? `${sq.days_to_cover}d` : "—"}
                  </td>
                  <td className="px-3 py-2 text-[11px] tabular-nums" style={{ color: "var(--text-secondary)", fontFamily: "var(--font-mono)" }}>
                    {sq.float_shares > 0 ? `${(sq.float_shares / 1e6).toFixed(1)}M` : "—"}
                  </td>
                  <td className="px-3 py-2">
                    <span className="text-[10px] font-bold uppercase tracking-[0.06em] px-1.5 py-[2px] rounded"
                      style={{ backgroundColor: "#ec489920", color: "#ec4899" }}>
                      {sq.level}
                    </span>
                  </td>
                  <td className="px-3 py-2 tabular-nums font-bold text-[16px]" style={{ color: "#ec4899", fontFamily: "var(--font-mono)" }}>
                    {sq.score.toFixed(0)}
                  </td>
                  <td className="px-3 py-2 text-[10px]" style={{ color: "var(--text-secondary)" }}>
                    {sq.components?.catalyst ?? "—"}
                  </td>
                  <td className="px-3 py-2 text-[10px]" style={{ color: sq.components?.insiders === "Selling pressure" ? "var(--red)" : "var(--green)" }}>
                    {sq.components?.insiders ?? "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Cards below */}
      <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-3">
        {squeeze.stocks.map((s) => <StockCard key={s.ticker} stock={s} />)}
      </div>
    </div>
  );
}

// ─── Sidebar ──────────────────────────────────────────────────────────────────

const NAV: { id: Tab; label: string; icon: string }[] = [
  { id: "picks",     label: "Picks",     icon: "★" },
  { id: "squeeze",   label: "Squeeze",   icon: "⚡" },
  { id: "photonics", label: "Photonics", icon: "◎" },
  { id: "portfolio", label: "Portfolio", icon: "◈" },
  { id: "tools",     label: "Tools",     icon: "⊞" },
];

function Sidebar({
  tab,
  onTab,
  scanning,
  lastScan,
  stockCount,
  nextMin,
  onScan,
  sources,
  alerts,
  improving,
}: {
  tab: Tab;
  onTab: (t: Tab) => void;
  scanning: boolean;
  lastScan: string | null;
  stockCount: number;
  nextMin: number;
  onScan: () => void;
  sources?: Record<string, string[]>;
  alerts: string[];
  improving: { ticker: string; change: number }[];
}) {
  return (
    <aside
      className="flex flex-col shrink-0"
      style={{
        width: 168,
        backgroundColor: "var(--bg-surface)",
        borderRight: "1px solid var(--border)",
        height: "100vh",
        position: "sticky",
        top: 0,
      }}
    >
      {/* Logo */}
      <div className="px-4 py-4" style={{ borderBottom: "1px solid var(--border)" }}>
        <div className="flex items-center gap-2.5">
          <div
            className="w-6 h-6 rounded-md shrink-0"
            style={{ background: "linear-gradient(135deg, var(--accent), var(--green))" }}
          />
          <div>
            <div className="text-[13px] font-bold" style={{ letterSpacing: "-0.02em" }}>
              Discovery
            </div>
            <div className="text-[9px]" style={{ color: "var(--text-muted)" }}>
              {stockCount} stocks tracked
            </div>
          </div>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex flex-col gap-0.5 p-2 flex-1">
        {NAV.map((item) => {
          const active = tab === item.id;
          // Badge counts
          const badge =
            item.id === "squeeze" && alerts.length > 0 ? alerts.length : null;
          const improvingBadge =
            item.id === "picks" && improving.length > 0 ? improving.length : null;

          return (
            <button
              key={item.id}
              onClick={() => onTab(item.id)}
              className="flex items-center gap-2.5 px-3 py-2 rounded-lg text-left w-full transition-colors"
              style={{
                backgroundColor: active ? "var(--accent)" + "18" : "transparent",
                color: active ? "var(--accent-bright)" : "var(--text-muted)",
                border: active ? "1px solid var(--accent)30" : "1px solid transparent",
              }}
            >
              <span className="text-[14px] leading-none">{item.icon}</span>
              <span className="text-[12px] font-medium">{item.label}</span>
              {(badge || improvingBadge) && (
                <span
                  className="ml-auto text-[9px] font-bold px-1.5 py-[1px] rounded-full"
                  style={{ backgroundColor: "#ec489925", color: "#ec4899" }}
                >
                  {badge ?? improvingBadge}
                </span>
              )}
            </button>
          );
        })}
      </nav>

      {/* Alerts strip */}
      {(alerts.length > 0 || improving.length > 0) && (
        <div className="px-3 pb-2 space-y-1">
          {improving.slice(0, 3).map((item) => (
            <div key={item.ticker} className="flex items-center gap-1.5 text-[10px]">
              <span style={{ color: "var(--green)" }}>↑</span>
              <span className="font-bold" style={{ color: "var(--text-secondary)" }}>{item.ticker}</span>
              <span style={{ color: "var(--green)" }}>+{item.change}</span>
            </div>
          ))}
        </div>
      )}

      {/* Status + controls */}
      <div className="px-3 pb-4 pt-2 space-y-2" style={{ borderTop: "1px solid var(--border)" }}>
        {scanning && (
          <div className="flex items-center gap-1.5 text-[10px]" style={{ color: "var(--amber)" }}>
            <span className="w-1.5 h-1.5 rounded-full animate-pulse" style={{ backgroundColor: "var(--amber)" }} />
            Scanning…
          </div>
        )}
        {lastScan && (
          <div className="text-[10px]" style={{ color: "var(--text-muted)" }}>
            {new Date(lastScan).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
            {nextMin > 0 && ` · next ${nextMin}m`}
          </div>
        )}
        <button
          onClick={onScan}
          disabled={scanning}
          className="w-full text-[11px] px-3 py-1.5 rounded-md transition-colors"
          style={{
            backgroundColor: scanning ? "var(--bg-elevated)" : "var(--accent)",
            color: scanning ? "var(--text-muted)" : "#fff",
            opacity: scanning ? 0.6 : 1,
          }}
        >
          {scanning ? "Scanning…" : "Scan Now"}
        </button>
        {sources && (
          <div className="pt-1">
            <SourceBadges sources={sources} />
          </div>
        )}
      </div>
    </aside>
  );
}

// ─── Root ─────────────────────────────────────────────────────────────────────

export default function Home() {
  const [tab, setTab] = useState<Tab>("picks");
  const [data, setData] = useState<DashboardResponse | null>(null);
  const [segments, setSegments] = useState<Segment[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      const d = await getDashboard();
      setData(d);
      if (d.ranked.length > 0) setSegments(buildSegments(d.ranked));
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
        setSegments(buildSegments(d.ranked));
        clearInterval(poll);
      }
    }, 5000);
  }

  if (loading || (data?.scan_in_progress && !data?.ranked.length)) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="flex flex-col items-center gap-4">
          <div
            className="w-8 h-8 border-2 border-t-transparent rounded-full animate-spin"
            style={{ borderColor: "var(--accent)", borderTopColor: "transparent" }}
          />
          <p className="text-[12px]" style={{ color: "var(--text-muted)" }}>
            {data?.scan_in_progress ? "Running scan…" : "Connecting…"}
          </p>
        </div>
      </div>
    );
  }

  if (error && !data?.ranked.length) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="text-center space-y-3">
          <p className="text-[13px]" style={{ color: "var(--red)" }}>{error}</p>
          <button
            onClick={fetchData}
            className="px-4 py-1.5 rounded text-[12px]"
            style={{ backgroundColor: "var(--accent)", color: "#fff" }}
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  const nextMin = data?.next_scan_in ? Math.ceil(data.next_scan_in / 60) : 0;
  const squeezeTickers = segments.find((s) => s.id === "squeeze")?.stocks.map((s) => s.ticker) ?? [];
  const improvingItems = (data?.improving ?? []).map((i) => ({ ticker: i.ticker, change: i.change }));

  return (
    <div className="flex" style={{ height: "100vh", overflow: "hidden" }}>
      <Sidebar
        tab={tab}
        onTab={setTab}
        scanning={!!data?.scan_in_progress}
        lastScan={data?.last_scan ?? null}
        stockCount={data?.ranked.length ?? 0}
        nextMin={nextMin}
        onScan={handleScan}
        sources={data?.universe?.sources}
        alerts={squeezeTickers}
        improving={improvingItems}
      />

      {/* Main content — scrollable */}
      <div className="flex-1 overflow-y-auto" style={{ backgroundColor: "var(--bg-primary)" }}>
        {/* New-ticker banner */}
        {data?.new_tickers && data.new_tickers.length > 0 && (
          <div
            className="px-5 h-7 flex items-center gap-2 text-[11px] sticky top-0 z-10"
            style={{ backgroundColor: "var(--green-dim)", borderBottom: "1px solid var(--border)" }}
          >
            <span className="font-bold" style={{ color: "var(--green)" }}>NEW</span>
            <span style={{ color: "var(--text-secondary)" }}>{data.new_tickers.join(", ")}</span>
          </div>
        )}

        {/* Tab content */}
        {tab === "picks" && (
          <PicksView segments={segments} ranked={data?.ranked ?? []} />
        )}

        {tab === "squeeze" && (
          <SqueezeView segments={segments} />
        )}

        {tab === "photonics" && (
          <div className="p-5">
            <PhotonicsCycle />
          </div>
        )}

        {tab === "portfolio" && (
          <div className="p-5 max-w-[1200px]">
            <WatchlistPanel />
          </div>
        )}

        {tab === "tools" && (
          <div className="p-5 max-w-[1200px] space-y-5">
            <ManualLookup />
            <BacktestPanel />
          </div>
        )}
      </div>
    </div>
  );
}
