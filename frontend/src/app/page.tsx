"use client";

import { useEffect, useState, useCallback, type ReactNode } from "react";
import {
  getDashboard,
  forceScan,
  getSqueezeScan,
  rescanSqueeze,
  StockResult,
  DashboardResponse,
  SqueezeScanResponse,
} from "@/lib/api";
import { StockTable } from "@/components/StockTable";
import { StockCard } from "@/components/StockCard";
import { SourceBadges } from "@/components/SourceBadges";
import { WatchlistPanel } from "@/components/WatchlistPanel";
import { BacktestPanel } from "@/components/BacktestPanel";
import { ManualLookup } from "@/components/ManualLookup";
import { PhotonicsCycle } from "@/components/PhotonicsCycle";
import { Overview } from "@/components/Overview";
import { ScorecardPanel } from "@/components/Scorecard";
import { TickerDrawer } from "@/components/TickerDrawer";

// ─── Types ───────────────────────────────────────────────────────────────────

type Tab = "overview" | "picks" | "squeeze" | "photonics" | "portfolio" | "tools";

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
    "coiled",
    "Coiled Springs",
    "Breaking out · coiled · basing — caught before/at the launch (the opposite of chasing)",
    "var(--accent-cyan)",
    (s) => ["BREAKING", "COILED", "BASING"].includes(s.coiled?.state ?? "") && (s.coiled?.coiled_score ?? 0) >= 55,
    (a, b) => (b.coiled?.coiled_score ?? 0) - (a.coiled?.coiled_score ?? 0),
  );

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

// ─── Tab views ────────────────────────────────────────────────────────────────

function PicksView({
  segments,
  ranked,
}: {
  segments: Segment[];
  ranked: StockResult[];
}) {
  const shownTickers = new Set(segments.flatMap((s) => s.stocks.map((x) => x.ticker)));
  const tailStocks = ranked.filter((s) => !shownTickers.has(s.ticker) && s.composite >= 40);

  const tabs = [
    ...segments.map((s) => ({ id: s.id, label: s.title, count: s.stocks.length, color: s.color })),
    ...(tailStocks.length > 0 ? [{ id: "watch", label: "On Watch", count: tailStocks.length, color: "var(--text-muted)" }] : []),
  ];

  const [activeTab, setActiveTab] = useState(tabs[0]?.id ?? "");
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null);

  // Reset card selection when tab changes
  const handleTab = (id: string) => { setActiveTab(id); setSelectedTicker(null); };

  const activeSeg = segments.find((s) => s.id === activeTab);
  const selectedStock = selectedTicker ? ranked.find((r) => r.ticker === selectedTicker) ?? null : null;

  const cols = activeSeg?.stocks.length === 1 ? 1 : activeSeg?.id === "ai" ? 3 : 2;

  return (
    <div className="flex flex-col h-full">
      {/* Tab bar — sticky at top of content pane */}
      <div
        className="flex items-center gap-1 px-4 overflow-x-auto shrink-0"
        style={{
          height: 44,
          borderBottom: "1px solid var(--border)",
          backgroundColor: "var(--bg-primary)",
          position: "sticky",
          top: 0,
          zIndex: 10,
        }}
      >
        {tabs.map((t) => {
          const active = t.id === activeTab;
          return (
            <button
              key={t.id}
              onClick={() => handleTab(t.id)}
              className="flex items-center gap-1.5 px-3 py-1 rounded-md shrink-0 transition-colors text-[12px] font-medium"
              style={{
                backgroundColor: active ? t.color + "18" : "transparent",
                color: active ? t.color : "var(--text-muted)",
                border: active ? `1px solid ${t.color}30` : "1px solid transparent",
              }}
            >
              {t.label}
              <span
                className="text-[10px] tabular-nums"
                style={{
                  color: active ? t.color : "var(--text-muted)",
                  fontFamily: "var(--font-mono)",
                  opacity: active ? 1 : 0.7,
                }}
              >
                {t.count}
              </span>
            </button>
          );
        })}
      </div>

      {/* Content */}
      <div className="p-5 max-w-[1200px]">
        {activeSeg && (
          <>
            <div className="text-[11px] mb-4" style={{ color: "var(--text-muted)" }}>
              {activeSeg.subtitle}
            </div>
            <div className={`grid gap-3 ${cols === 3 ? "grid-cols-1 lg:grid-cols-3" : cols === 2 ? "grid-cols-1 lg:grid-cols-2" : "grid-cols-1"}`}>
              {activeSeg.stocks.map((s) => (
                <StockCard key={s.ticker} stock={s} />
              ))}
            </div>
          </>
        )}

        {activeTab === "watch" && (
          <>
            <div className="text-[11px] mb-4" style={{ color: "var(--text-muted)" }}>
              Composite ≥ 40 · not in any named segment
            </div>
            <StockTable stocks={tailStocks} onSelect={setSelectedTicker} />
            {selectedStock && (
              <div className="mt-3">
                <StockCard stock={selectedStock} />
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

// ─── Squeeze row helpers ─────────────────────────────────────────────────────

const SQUEEZE_HEADERS = ["Ticker", "Price", "Short Float", "Days to Cover", "Float", "Level", "Score", "Catalyst", "Insider"];

function SqueezeLevelBadge({ level }: { level: string }) {
  const colors: Record<string, [string, string]> = {
    extreme: ["#ec489930", "#ec4899"],
    high:    ["#f9731620", "#f97316"],
    moderate:["#eab30820", "#eab308"],
    low:     ["var(--bg-elevated)", "var(--text-muted)"],
  };
  const [bg, fg] = colors[level] ?? colors.low;
  return (
    <span className="text-[10px] font-bold uppercase tracking-[0.06em] px-1.5 py-[2px] rounded"
      style={{ backgroundColor: bg, color: fg }}>
      {level}
    </span>
  );
}

function SqueezeTableRow({ ticker, name, price, changePct, shortPct, dtc, floatShares, level, squeezScore, catalyst, insider }: {
  ticker: string; name: string; price: number; changePct: number;
  shortPct: number; dtc: number; floatShares: number;
  level: string; squeezScore: number; catalyst?: string; insider?: string;
}) {
  const pink = "#ec4899";
  const amber = "var(--amber)";
  return (
    <tr style={{ borderBottom: "1px solid var(--border)" }} className="hover:bg-[var(--bg-elevated)] transition-colors">
      <td className="px-3 py-2.5">
        <div className="font-bold text-[13px]">{ticker}</div>
        <div className="text-[10px] truncate max-w-[140px]" style={{ color: "var(--text-muted)" }}>{name}</div>
      </td>
      <td className="px-3 py-2.5 tabular-nums text-[12px]" style={{ fontFamily: "var(--font-mono)", color: "var(--text-secondary)" }}>
        <div>{price > 0 ? `$${price.toFixed(2)}` : "—"}</div>
        {changePct !== 0 && (
          <div className="text-[10px]" style={{ color: changePct >= 0 ? "var(--green)" : "var(--red)" }}>
            {changePct >= 0 ? "+" : ""}{changePct.toFixed(1)}%
          </div>
        )}
      </td>
      <td className="px-3 py-2.5 tabular-nums font-bold text-[14px]" style={{ color: pink, fontFamily: "var(--font-mono)" }}>
        {shortPct > 0 ? `${shortPct.toFixed(1)}%` : "—"}
      </td>
      <td className="px-3 py-2.5 tabular-nums font-bold text-[13px]" style={{ color: dtc >= 20 ? pink : amber, fontFamily: "var(--font-mono)" }}>
        {dtc > 0 ? `${dtc.toFixed(1)}d` : "—"}
      </td>
      <td className="px-3 py-2.5 text-[11px] tabular-nums" style={{ color: "var(--text-secondary)", fontFamily: "var(--font-mono)" }}>
        {floatShares > 0 ? `${(floatShares / 1e6).toFixed(1)}M` : "—"}
      </td>
      <td className="px-3 py-2.5"><SqueezeLevelBadge level={level} /></td>
      <td className="px-3 py-2.5 tabular-nums font-bold text-[18px]" style={{ color: pink, fontFamily: "var(--font-mono)" }}>
        {squeezScore.toFixed(0)}
      </td>
      <td className="px-3 py-2.5 text-[10px]" style={{ color: "var(--text-secondary)" }}>
        {catalyst ?? "—"}
      </td>
      <td className="px-3 py-2.5 text-[10px]" style={{ color: insider === "Selling pressure" ? "var(--red)" : insider ? "var(--green)" : "var(--text-muted)" }}>
        {insider ?? "—"}
      </td>
    </tr>
  );
}

function SqueezeSection({ title, count, children }: { title: string; count: number; children: ReactNode }) {
  return (
    <div>
      <div className="flex items-baseline gap-2 mb-2">
        <span className="w-[3px] h-[16px] rounded-full shrink-0" style={{ backgroundColor: "#ec4899" }} />
        <span className="text-[13px] font-semibold" style={{ letterSpacing: "-0.02em" }}>{title}</span>
        <span className="text-[11px] tabular-nums" style={{ color: "var(--text-muted)", fontFamily: "var(--font-mono)" }}>{count}</span>
      </div>
      <div className="rounded-lg overflow-hidden" style={{ border: "1px solid var(--border)" }}>
        <table className="w-full border-collapse">
          <thead>
            <tr style={{ backgroundColor: "var(--bg-surface)", borderBottom: "1px solid var(--border)" }}>
              {SQUEEZE_HEADERS.map((h) => (
                <th key={h} className="px-3 py-2 text-left text-[9px] uppercase tracking-[0.08em] font-medium" style={{ color: "var(--text-muted)" }}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>{children}</tbody>
        </table>
      </div>
    </div>
  );
}

function SqueezeView({ segments }: { segments: Segment[] }) {
  const [scanData, setScanData] = useState<SqueezeScanResponse | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchScan = useCallback(async () => {
    try {
      const d = await getSqueezeScan();
      setScanData(d);
    } catch { /* ignore */ }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { fetchScan(); }, [fetchScan]);

  // Poll while scan is running
  useEffect(() => {
    if (!scanData?.scan_in_progress) return;
    const id = setInterval(async () => {
      const d = await getSqueezeScan();
      setScanData(d);
      if (!d.scan_in_progress) clearInterval(id);
    }, 6000);
    return () => clearInterval(id);
  }, [scanData?.scan_in_progress]);

  async function handleRescan() {
    await rescanSqueeze();
    setScanData((prev) => prev ? { ...prev, scan_in_progress: true } : null);
  }

  // From main scan universe (existing squeeze segment)
  const mainSqueeze = segments.find((s) => s.id === "squeeze")?.stocks ?? [];
  const discoveredTickers = new Set((scanData?.results ?? []).map((d) => d.ticker));

  // Rows from discovery scan
  const discoveryRows = scanData?.results ?? [];
  // Rows from main scan not already in discovery
  const mainOnlyRows = mainSqueeze.filter((s) => !discoveredTickers.has(s.ticker));

  const totalFound = discoveryRows.length + mainOnlyRows.length;

  return (
    <div className="p-5 space-y-5 max-w-[1200px]">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <div className="text-[15px] font-bold" style={{ letterSpacing: "-0.02em" }}>Squeeze Scanner</div>
          <div className="text-[11px] mt-0.5" style={{ color: "var(--text-muted)" }}>
            Proactively scans Finviz for high short-interest setups — independent of the main discovery universe
          </div>
        </div>
        <div className="flex items-center gap-3">
          {scanData?.last_scan && (
            <span className="text-[10px]" style={{ color: "var(--text-muted)" }}>
              {new Date(scanData.last_scan).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
            </span>
          )}
          {scanData?.scan_in_progress && (
            <div className="flex items-center gap-1.5 text-[10px]" style={{ color: "var(--amber)" }}>
              <span className="w-1.5 h-1.5 rounded-full animate-pulse" style={{ backgroundColor: "var(--amber)" }} />
              Scanning…
            </div>
          )}
          <button
            onClick={handleRescan}
            disabled={scanData?.scan_in_progress}
            className="text-[11px] px-3 py-1.5 rounded-md transition-colors"
            style={{
              backgroundColor: scanData?.scan_in_progress ? "var(--bg-elevated)" : "#ec489918",
              color: scanData?.scan_in_progress ? "var(--text-muted)" : "#ec4899",
              border: "1px solid " + (scanData?.scan_in_progress ? "var(--border)" : "#ec489940"),
            }}
          >
            {scanData?.scan_in_progress ? "Scanning…" : "Rescan"}
          </button>
        </div>
      </div>

      {loading && (
        <div className="flex items-center justify-center h-40 text-[12px]" style={{ color: "var(--text-muted)" }}>
          Loading…
        </div>
      )}

      {!loading && totalFound === 0 && (
        <div className="flex flex-col items-center justify-center h-40 gap-2">
          <div className="text-[13px]" style={{ color: "var(--text-muted)" }}>
            {scanData?.scan_in_progress ? "Scan in progress — check back shortly" : "No squeeze setups found yet"}
          </div>
          {!scanData?.last_scan && !scanData?.scan_in_progress && (
            <button onClick={handleRescan} className="text-[11px] px-3 py-1.5 rounded-md"
              style={{ backgroundColor: "#ec489918", color: "#ec4899", border: "1px solid #ec489940" }}>
              Run First Scan
            </button>
          )}
        </div>
      )}

      {/* Discovery results */}
      {discoveryRows.length > 0 && (
        <SqueezeSection title="Discovered by Scanner" count={discoveryRows.length}>
          {discoveryRows.map((c) => (
            <SqueezeTableRow
              key={c.ticker}
              ticker={c.ticker}
              name={c.name}
              price={c.price}
              changePct={c.change_pct}
              shortPct={c.short_pct_float}
              dtc={c.days_to_cover}
              floatShares={c.float_shares}
              level={c.level}
              squeezScore={c.score}
              catalyst={c.components?.catalyst}
              insider={c.components?.insiders}
            />
          ))}
        </SqueezeSection>
      )}

      {/* Main scan stocks not in discovery */}
      {mainOnlyRows.length > 0 && (
        <SqueezeSection title="Also in Main Scan" count={mainOnlyRows.length}>
          {mainOnlyRows.map((s) => {
            const sq = s.short_squeeze!;
            return (
              <SqueezeTableRow
                key={s.ticker}
                ticker={s.ticker}
                name={s.quote?.name ?? s.ticker}
                price={s.quote?.price ?? 0}
                changePct={s.quote?.change_pct ?? 0}
                shortPct={sq.short_pct_float}
                dtc={sq.days_to_cover}
                floatShares={sq.float_shares}
                level={sq.level}
                squeezScore={sq.score}
                catalyst={sq.components?.catalyst as string | undefined}
                insider={sq.components?.insiders as string | undefined}
              />
            );
          })}
        </SqueezeSection>
      )}

      {/* Cards for top discovered candidates */}
      {discoveryRows.filter((c) => c.score >= 60).length > 0 && (
        <div>
          <div className="flex items-baseline gap-2 mb-3">
            <span className="w-[3px] h-[16px] rounded-full shrink-0" style={{ backgroundColor: "#ec4899" }} />
            <span className="text-[13px] font-semibold" style={{ letterSpacing: "-0.02em" }}>High / Extreme Setups</span>
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-3">
            {mainSqueeze.map((s) => <StockCard key={s.ticker} stock={s} />)}
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Sidebar ──────────────────────────────────────────────────────────────────

const NAV: { id: Tab; label: string; icon: string }[] = [
  { id: "overview",  label: "Overview",  icon: "◉" },
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
        background: "linear-gradient(180deg, rgba(255,255,255,0.055), rgba(255,255,255,0.015))",
        backdropFilter: "blur(20px) saturate(1.3)",
        WebkitBackdropFilter: "blur(20px) saturate(1.3)",
        borderRight: "1px solid var(--glass-border)",
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
  const [tab, setTab] = useState<Tab>("overview");
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
          <div className="w-8 h-8 border-2 border-[var(--accent-bright)] border-t-transparent rounded-full animate-spin" />
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
      <div className="flex-1 overflow-y-auto" style={{ backgroundColor: "transparent" }}>
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
        {tab === "overview" && (
          <Overview data={data} onNavigate={(t) => setTab(t as Tab)} />
        )}

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
            <ScorecardPanel />
            <ManualLookup />
            <BacktestPanel />
          </div>
        )}
      </div>

      {/* Per-ticker deep-dive drawer (opens via openTicker events) */}
      <TickerDrawer />
    </div>
  );
}
