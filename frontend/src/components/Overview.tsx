"use client";

import { useCallback, useEffect, useState, type ReactNode } from "react";
import {
  Brief,
  CapitalFlow,
  DashboardResponse,
  MacroAsset,
  MacroDesk,
  MarketRegimeResponse,
  SectorHeat,
  SetupStat,
  SqueezeCandidate,
  StockResult,
  WatchlistItem,
  getBrief,
  getMarketRegime,
  getSqueezeScan,
  getWatchlist,
} from "@/lib/api";
import { ArcGauge, DivergingBar, HBar, ScaleGauge } from "./gauges";
import { StockCard } from "./StockCard";
import { TickerLogo } from "./TickerLogo";
import { openTicker } from "./TickerDrawer";

// ─── Colors ───────────────────────────────────────────────────────────────────

const MOOD_COLORS: Record<string, string> = {
  "RISK-ON": "var(--green)",
  NEUTRAL: "var(--amber)",
  "RISK-OFF": "var(--red)",
};
const VOL_COLORS: Record<string, string> = {
  QUIET: "var(--accent-bright)",
  TRADABLE: "var(--green)",
  WILD: "var(--red)",
};
const SMALL_COLORS: Record<string, string> = {
  HOT: "var(--green)",
  NEUTRAL: "var(--amber)",
  COLD: "var(--red)",
};
const BULLET_MARKERS: Record<string, [string, string]> = {
  new: ["●", "var(--accent-bright)"],
  improving: ["▲", "var(--green)"],
  decaying: ["▼", "var(--red)"],
  squeeze: ["⚡", "#ec4899"],
  pick: ["★", "var(--accent-bright)"],
  watchlist: ["⚠", "var(--amber)"],
};

// ─── Shared chrome ────────────────────────────────────────────────────────────

function Card({ title, right, children, accent, tint, strong }: {
  title: string;
  right?: ReactNode;
  children: ReactNode;
  accent?: string;
  tint?: string;
  strong?: boolean;
}) {
  return (
    <div
      className={`${strong ? "glass-strong" : "glass"} glass-hover glow-top rounded-2xl p-4 relative overflow-hidden`}
      style={{ ["--glow-color" as string]: accent ?? "var(--accent-bright)" }}
    >
      {tint && (
        <div
          className="absolute inset-0 pointer-events-none"
          style={{ background: `radial-gradient(95% 80% at 50% 0%, ${tint}, transparent 72%)` }}
        />
      )}
      <div className="relative">
        <div className="flex items-center justify-between mb-3">
          <span className="text-[9px] uppercase tracking-[0.14em] font-bold" style={{ color: "var(--text-secondary)" }}>
            {title}
          </span>
          {right}
        </div>
        {children}
      </div>
    </div>
  );
}

function SectionHeader({ label, color, count, action }: {
  label: string;
  color: string;
  count?: number;
  action?: ReactNode;
}) {
  return (
    <div className="flex items-baseline gap-2 mb-2">
      <span className="w-[3px] h-[14px] rounded-full shrink-0 self-center" style={{ backgroundColor: color }} />
      <span className="text-[13px] font-semibold" style={{ letterSpacing: "-0.02em" }}>{label}</span>
      {count !== undefined && (
        <span className="text-[11px] tabular-nums" style={{ color: "var(--text-muted)", fontFamily: "var(--font-mono)" }}>
          {count}
        </span>
      )}
      <span className="ml-auto">{action}</span>
    </div>
  );
}

function Placeholder({ text = "Waiting for market data…" }: { text?: string }) {
  return (
    <div className="flex items-center justify-center h-[110px] text-[11px]" style={{ color: "var(--text-muted)" }}>
      {text}
    </div>
  );
}

// ─── Regime band cards ────────────────────────────────────────────────────────

function MoodCard({ regime }: { regime: MarketRegimeResponse | null }) {
  const mood = regime?.available ? regime.mood : undefined;
  const color = mood ? MOOD_COLORS[mood.label] : "var(--text-muted)";
  return (
    <Card
      title="Market Mood"
      accent={color}
      tint={`color-mix(in srgb, ${color} 18%, transparent)`}
      right={regime?.stale ? <StaleBadge asOf={regime.as_of} /> : undefined}
    >
      {mood ? (
        <div className="flex flex-col items-center">
          <ArcGauge value={mood.score} color={color} />
          <div className="text-[13px] font-bold tracking-[0.08em] mt-0.5" style={{ color }}>
            {mood.label}
          </div>
          {regime?.strip && regime.strip.length > 1 && (
            <div className="flex items-center gap-[5px] mt-2.5" title="Last 10 days">
              {regime.strip.map((d) => (
                <div
                  key={d.snap_date}
                  title={`${d.snap_date}: ${d.label} ${Math.round(d.mood_score)}`}
                  className="w-[7px] h-[7px] rounded-full"
                  style={{ backgroundColor: MOOD_COLORS[d.label] ?? "var(--text-muted)" }}
                />
              ))}
            </div>
          )}
        </div>
      ) : (
        <Placeholder />
      )}
    </Card>
  );
}

function VolatilityCard({ regime }: { regime: MarketRegimeResponse | null }) {
  const vol = regime?.available ? regime.volatility : undefined;
  const color = vol ? VOL_COLORS[vol.state] : "var(--text-muted)";
  const pos = vol ? ((vol.vix - 10) / 25) * 100 : 0; // VIX 10–35 mapped onto the track
  const active = vol?.state === "QUIET" ? 0 : vol?.state === "WILD" ? 2 : 1;
  return (
    <Card title="Volatility" accent="var(--accent-cyan)" tint="color-mix(in srgb, var(--accent-cyan) 16%, transparent)">
      {vol ? (
        <div>
          <div className="flex items-baseline gap-2 mb-3">
            <span className="text-[26px] font-bold tabular-nums leading-none" style={{ fontFamily: "var(--font-mono)", color: "var(--text-primary)" }}>
              {vol.vix.toFixed(1)}
            </span>
            <span className="text-[10px] uppercase tracking-[0.08em]" style={{ color: "var(--text-muted)" }}>VIX</span>
            {vol.change_5d_pct != null && (
              <span
                className="text-[11px] font-semibold tabular-nums ml-auto"
                style={{ fontFamily: "var(--font-mono)", color: vol.change_5d_pct >= 0 ? "var(--red)" : "var(--green)" }}
              >
                {vol.change_5d_pct >= 0 ? "+" : ""}{vol.change_5d_pct.toFixed(0)}% 5d
              </span>
            )}
          </div>
          <ScaleGauge stops={["Quiet", "Tradable", "Wild"]} activeIndex={active} position={pos} color={color} />
          <div className="text-[10px] mt-2.5" style={{ color: "var(--text-muted)" }}>
            Higher than {vol.percentile}% of the past year
          </div>
        </div>
      ) : (
        <Placeholder />
      )}
    </Card>
  );
}

function SmallcapCard({ regime }: { regime: MarketRegimeResponse | null }) {
  const sc = regime?.available ? regime.smallcap : undefined;
  const color = sc ? SMALL_COLORS[sc.state] : "var(--text-muted)";
  return (
    <Card title="Small-Cap Appetite" accent={color} tint={`color-mix(in srgb, ${color} 16%, transparent)`}>
      {sc && sc.rel_1m_pct != null ? (
        <div>
          <div className="flex items-baseline justify-between mb-3">
            <span className="text-[15px] font-bold tracking-[0.06em]" style={{ color }}>{sc.state}</span>
            <span className="text-[11px] font-semibold tabular-nums" style={{ fontFamily: "var(--font-mono)", color }}>
              {sc.rel_1m_pct >= 0 ? "+" : ""}{sc.rel_1m_pct.toFixed(1)}% vs SPY
            </span>
          </div>
          <DivergingBar value={sc.rel_1m_pct} max={5} color={color} />
          <div className="flex justify-between text-[8px] uppercase tracking-[0.08em] mt-1.5" style={{ color: "var(--text-muted)" }}>
            <span>Lagging</span>
            <span>Leading</span>
          </div>
          <div className="text-[10px] mt-2.5" style={{ color: "var(--text-muted)" }}>
            IWM vs SPY · 1 month{sc.rel_3m_pct != null && ` · 3m ${sc.rel_3m_pct >= 0 ? "+" : ""}${sc.rel_3m_pct.toFixed(1)}%`}
          </div>
        </div>
      ) : (
        <Placeholder />
      )}
    </Card>
  );
}

function BreadthCard({ regime, data }: { regime: MarketRegimeResponse | null; data: DashboardResponse | null }) {
  const uniPct = data?.breadth?.pct_above_20ma ?? regime?.breadth?.universe_pct ?? null;
  const uniN = data?.breadth?.n ?? regime?.breadth?.universe_n ?? null;
  const secPct = regime?.available ? regime.breadth?.sectors_pct : undefined;
  const colorOf = (p: number) => (p >= 60 ? "var(--green)" : p >= 40 ? "var(--amber)" : "var(--red)");
  return (
    <Card title="Breadth" accent="var(--accent-bright)" tint="color-mix(in srgb, var(--accent-bright) 15%, transparent)">
      {uniPct != null || secPct != null ? (
        <div className="space-y-3.5">
          {uniPct != null && (
            <div>
              <div className="flex items-baseline justify-between mb-1.5">
                <span className="text-[20px] font-bold tabular-nums leading-none" style={{ fontFamily: "var(--font-mono)", color: colorOf(uniPct) }}>
                  {uniPct.toFixed(0)}%
                </span>
                <span className="text-[10px]" style={{ color: "var(--text-muted)" }}>
                  of {uniN ?? "—"} tracked names
                </span>
              </div>
              <HBar pct={uniPct} color={colorOf(uniPct)} />
              <div className="text-[9px] mt-1" style={{ color: "var(--text-muted)" }}>Universe above 20-day MA</div>
            </div>
          )}
          {secPct != null && (
            <div>
              <div className="flex items-baseline justify-between mb-1.5">
                <span className="text-[13px] font-bold tabular-nums leading-none" style={{ fontFamily: "var(--font-mono)", color: colorOf(secPct) }}>
                  {secPct.toFixed(0)}%
                </span>
                <span className="text-[10px]" style={{ color: "var(--text-muted)" }}>of sector ETFs</span>
              </div>
              <HBar pct={secPct} color={colorOf(secPct)} height={4} />
            </div>
          )}
        </div>
      ) : (
        <Placeholder text="Breadth arrives with the first scan" />
      )}
    </Card>
  );
}

function StaleBadge({ asOf }: { asOf?: string }) {
  return (
    <span className="text-[9px] px-1.5 py-[1px] rounded" style={{ backgroundColor: "var(--amber-dim)", color: "var(--amber)" }}>
      stale{asOf ? ` · ${new Date(asOf).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}` : ""}
    </span>
  );
}

// ─── AI Brief ─────────────────────────────────────────────────────────────────

function BriefCard({ brief }: { brief: Brief | null }) {
  if (!brief) {
    return (
      <Card title="Daily Brief" strong accent="var(--accent)" tint="color-mix(in srgb, var(--accent) 16%, transparent)">
        <Placeholder text="The brief composes after the first scan completes" />
      </Card>
    );
  }
  return (
    <Card
      title="Daily Brief"
      strong
      accent="var(--accent)"
      tint="color-mix(in srgb, var(--accent) 16%, transparent)"
      right={
        <span className="flex items-center gap-2">
          {brief.source === "llm" && (
            <span className="text-[9px] font-bold px-1.5 py-[1px] rounded" style={{ backgroundColor: "var(--accent-dim)", color: "var(--accent-bright)" }}>
              AI
            </span>
          )}
          <span className="text-[10px]" style={{ color: "var(--text-muted)" }}>
            {new Date(brief.generated_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
          </span>
        </span>
      }
    >
      <div className="text-[15px] font-bold mb-1.5" style={{ letterSpacing: "-0.02em" }}>
        {brief.headline}
      </div>
      {brief.paragraph && (
        <p className="text-[12px] leading-relaxed" style={{ color: "var(--text-secondary)" }}>
          {brief.paragraph}
        </p>
      )}
      {brief.bullets.length > 0 && (
        <div className="mt-3 space-y-1.5">
          {brief.bullets.map((b, i) => {
            const [marker, color] = BULLET_MARKERS[b.type] ?? ["·", "var(--text-muted)"];
            return (
              <div key={i} className="flex items-start gap-2 text-[12px]">
                <span className="shrink-0 w-[14px] text-center" style={{ color }}>{marker}</span>
                <span style={{ color: "var(--text-secondary)" }}>{b.text}</span>
              </div>
            );
          })}
        </div>
      )}
    </Card>
  );
}

// ─── AI Macro Desk + Capital Flow ─────────────────────────────────────────────

const BIAS_COLOR: Record<string, string> = {
  BULLISH: "var(--green)", NEUTRAL: "var(--amber)", BEARISH: "var(--red)",
  "RISK-ON": "var(--green)", "RISK-OFF": "var(--red)",
  "RISK-SEEKING": "var(--green)", DEFENSIVE: "var(--red)", BALANCED: "var(--amber)",
};
const BIAS_ARROW: Record<string, string> = { BULLISH: "▲", NEUTRAL: "‒", BEARISH: "▼" };

function BiasChip({ label }: { label: string }) {
  const c = BIAS_COLOR[label] ?? "var(--text-muted)";
  return (
    <span className="text-[10px] font-bold uppercase tracking-[0.06em] px-2 py-[2px] rounded-full"
      style={{ backgroundColor: `color-mix(in srgb, ${c} 18%, transparent)`, color: c }}>
      {label}
    </span>
  );
}

function AssetRow({ a }: { a: MacroAsset }) {
  const c = BIAS_COLOR[a.bias];
  const r = a.ret_1m_pct;
  return (
    <div className="flex items-center gap-2">
      <span style={{ color: c, fontSize: 9 }}>{BIAS_ARROW[a.bias]}</span>
      <span className="text-[11px] flex-1 truncate" style={{ color: "var(--text-secondary)" }}>{a.name}</span>
      <span className="text-[10px] tabular-nums w-[46px] text-right"
        style={{ fontFamily: "var(--font-mono)", color: (r ?? 0) >= 0 ? "var(--green)" : "var(--red)" }}>
        {r != null ? `${r >= 0 ? "+" : ""}${r.toFixed(1)}%` : "—"}
      </span>
    </div>
  );
}

function MacroDeskCard({ desk }: { desk?: MacroDesk }) {
  if (!desk?.available) {
    return <Card title="AI Macro Desk"><Placeholder text="Macro data loading…" /></Card>;
  }
  return (
    <Card
      title="AI Macro Desk"
      accent={BIAS_COLOR[desk.bias_label]}
      tint={`color-mix(in srgb, ${BIAS_COLOR[desk.bias_label]} 13%, transparent)`}
      right={<BiasChip label={desk.bias_label} />}
    >
      <p className="text-[11px] leading-relaxed mb-3" style={{ color: "var(--text-secondary)" }}>
        {desk.narrative}
      </p>
      <div className="grid grid-cols-2 gap-x-5 gap-y-[7px]">
        {desk.assets.map((a) => <AssetRow key={a.key} a={a} />)}
      </div>
      <div className="text-[9px] mt-2.5" style={{ color: "var(--text-muted)" }}>1-month trend bias · cross-asset</div>
    </Card>
  );
}

function MoverList({ title, movers, positive }: { title: string; movers?: { symbol: string; name: string; ret_5d_pct: number }[]; positive?: boolean }) {
  return (
    <div>
      <div className="text-[9px] uppercase tracking-[0.08em] mb-1.5" style={{ color: positive ? "var(--green)" : "var(--red)" }}>{title}</div>
      <div className="space-y-1">
        {(movers ?? []).map((m) => (
          <div key={m.symbol} className="flex items-center justify-between text-[10px]">
            <span className="truncate" style={{ color: "var(--text-secondary)" }}>{m.name}</span>
            <span className="tabular-nums" style={{ fontFamily: "var(--font-mono)", color: m.ret_5d_pct >= 0 ? "var(--green)" : "var(--red)" }}>
              {m.ret_5d_pct >= 0 ? "+" : ""}{m.ret_5d_pct.toFixed(1)}%
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function CapitalFlowCard({ flow }: { flow?: CapitalFlow }) {
  if (!flow?.available) {
    return <Card title="Capital Flow"><Placeholder text="Flow data loading…" /></Card>;
  }
  const color = BIAS_COLOR[flow.flow_label ?? "BALANCED"];
  const active = flow.flow_label === "DEFENSIVE" ? 0 : flow.flow_label === "RISK-SEEKING" ? 2 : 1;
  return (
    <Card
      title="Capital Flow"
      accent={color}
      tint={`color-mix(in srgb, ${color} 13%, transparent)`}
      right={<BiasChip label={flow.flow_label ?? "BALANCED"} />}
    >
      <div className="mb-3.5">
        <ScaleGauge stops={["Defensive", "Balanced", "Risk-on"]} activeIndex={active} position={flow.flow_score ?? 50} color={color} />
      </div>
      <div className="space-y-1.5 mb-3.5">
        <div className="flex items-center justify-between text-[10px]">
          <span style={{ color: "var(--text-muted)" }}>Into risk · QQQ·IWM·SMH·HY·BTC</span>
          <span className="tabular-nums font-semibold" style={{ fontFamily: "var(--font-mono)", color: (flow.risk_on_ret_5d ?? 0) >= 0 ? "var(--green)" : "var(--red)" }}>
            {(flow.risk_on_ret_5d ?? 0) >= 0 ? "+" : ""}{flow.risk_on_ret_5d?.toFixed(1)}% 5d
          </span>
        </div>
        <div className="flex items-center justify-between text-[10px]">
          <span style={{ color: "var(--text-muted)" }}>Into safety · Util·Staples·TLT·Gold</span>
          <span className="tabular-nums font-semibold" style={{ fontFamily: "var(--font-mono)", color: (flow.risk_off_ret_5d ?? 0) >= 0 ? "var(--green)" : "var(--red)" }}>
            {(flow.risk_off_ret_5d ?? 0) >= 0 ? "+" : ""}{flow.risk_off_ret_5d?.toFixed(1)}% 5d
          </span>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-4 pt-2.5" style={{ borderTop: "1px solid var(--border-subtle)" }}>
        <MoverList title="Inflows ›" movers={flow.leaders} positive />
        <MoverList title="‹ Outflows" movers={flow.laggards} />
      </div>
    </Card>
  );
}

// ─── What changed ─────────────────────────────────────────────────────────────

function DeltaRow({ ticker, oldScore, newScore, change }: { ticker: string; oldScore: number; newScore: number; change: number }) {
  const up = change >= 0;
  return (
    <div className="flex items-center gap-2 py-1">
      <TickerLogo ticker={ticker} size={18} />
      <span className="text-[12px] font-bold">{ticker}</span>
      <span className="ml-auto text-[11px] tabular-nums" style={{ fontFamily: "var(--font-mono)", color: "var(--text-muted)" }}>
        {oldScore.toFixed(0)} → {newScore.toFixed(0)}
      </span>
      <span className="text-[11px] font-bold tabular-nums w-[34px] text-right" style={{ fontFamily: "var(--font-mono)", color: up ? "var(--green)" : "var(--red)" }}>
        {up ? "+" : ""}{change.toFixed(0)}
      </span>
    </div>
  );
}

function WhatChanged({ data, squeeze, onNavigate }: {
  data: DashboardResponse | null;
  squeeze: SqueezeCandidate[];
  onNavigate?: (tab: string) => void;
}) {
  const newTickers = data?.new_tickers ?? [];
  const improving = data?.improving ?? [];
  const decaying = data?.decaying ?? [];
  const empty = !newTickers.length && !improving.length && !decaying.length && !squeeze.length;

  return (
    <div className="glass glow-top rounded-2xl p-4" style={{ ["--glow-color" as string]: "var(--accent-bright)" }}>
      <div className="flex items-center justify-between mb-3">
        <span className="text-[9px] uppercase tracking-[0.1em] font-bold" style={{ color: "var(--text-muted)" }}>
          What Changed
        </span>
        <span className="text-[10px]" style={{ color: "var(--text-muted)" }}>since previous scan</span>
      </div>

      {empty && (
        <div className="text-[11px] py-6 text-center" style={{ color: "var(--text-muted)" }}>
          No notable changes — universe is stable
        </div>
      )}

      <div className="space-y-4">
        {newTickers.length > 0 && (
          <div>
            <SectionHeader label="New on Radar" color="var(--accent-bright)" count={newTickers.length} />
            <div className="flex flex-wrap gap-1.5">
              {newTickers.map((t) => (
                <span key={t} className="flex items-center gap-1.5 text-[11px] font-bold px-2 py-1 rounded"
                  style={{ backgroundColor: "var(--accent-dim)", color: "var(--accent-bright)", border: "1px solid var(--accent)30" }}>
                  <TickerLogo ticker={t} size={14} />
                  {t}
                </span>
              ))}
            </div>
          </div>
        )}

        {improving.length > 0 && (
          <div>
            <SectionHeader label="Heating Up" color="var(--green)" count={improving.length} />
            {improving.slice(0, 5).map((d) => (
              <DeltaRow key={d.ticker} ticker={d.ticker} oldScore={d.old_score} newScore={d.new_score} change={d.change} />
            ))}
          </div>
        )}

        {decaying.length > 0 && (
          <div>
            <SectionHeader label="Cooling Off" color="var(--red)" count={decaying.length} />
            {decaying.slice(0, 5).map((d) => (
              <DeltaRow key={d.ticker} ticker={d.ticker} oldScore={d.old_score} newScore={d.new_score} change={d.change} />
            ))}
          </div>
        )}

        {squeeze.length > 0 && (
          <div>
            <SectionHeader
              label="Squeeze Watch"
              color="#ec4899"
              count={squeeze.length}
              action={
                onNavigate && (
                  <button onClick={() => onNavigate("squeeze")} className="text-[10px]" style={{ color: "#ec4899" }}>
                    view all →
                  </button>
                )
              }
            />
            {squeeze.map((c) => (
              <div key={c.ticker} className="flex items-center gap-2 py-1">
                <TickerLogo ticker={c.ticker} size={18} />
                <span className="text-[12px] font-bold">{c.ticker}</span>
                <span className="text-[14px] font-bold tabular-nums" style={{ fontFamily: "var(--font-mono)", color: "#ec4899" }}>
                  {c.score.toFixed(0)}
                </span>
                <span className="ml-auto text-[10px] tabular-nums" style={{ fontFamily: "var(--font-mono)", color: "var(--text-muted)" }}>
                  {c.short_pct_float > 0 ? `${c.short_pct_float.toFixed(0)}% SI` : ""}
                  {c.days_to_cover > 0 ? ` · ${c.days_to_cover.toFixed(0)}d cover` : ""}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Sector heat ──────────────────────────────────────────────────────────────

const NICHE_ETFS = new Set(["SMH", "XBI"]);

function SectorHeatPanel({ sectors }: { sectors: SectorHeat[] }) {
  const valid = sectors.filter((s) => s.ret_1m_pct != null);
  if (!valid.length) {
    return (
      <div className="glass glow-top rounded-2xl p-4" style={{ ["--glow-color" as string]: "var(--accent-bright)" }}>
        <span className="text-[9px] uppercase tracking-[0.1em] font-bold" style={{ color: "var(--text-muted)" }}>Sector Heat</span>
        <Placeholder />
      </div>
    );
  }
  const maxAbs = Math.max(...valid.map((s) => Math.abs(s.ret_1m_pct!)), 1);
  return (
    <div className="glass glow-top rounded-2xl p-4" style={{ ["--glow-color" as string]: "var(--accent-bright)" }}>
      <div className="flex items-center justify-between mb-3">
        <span className="text-[9px] uppercase tracking-[0.1em] font-bold" style={{ color: "var(--text-muted)" }}>
          Sector Heat
        </span>
        <span className="text-[10px]" style={{ color: "var(--text-muted)" }}>1-month return</span>
      </div>
      <div className="space-y-[7px]">
        {valid.map((s) => {
          const ret = s.ret_1m_pct!;
          const color = ret >= 0 ? "var(--green)" : "var(--red)";
          const niche = NICHE_ETFS.has(s.etf);
          return (
            <div key={s.etf} className="flex items-center gap-2">
              <span
                className="w-[86px] shrink-0 text-[10px] truncate font-medium"
                style={{ color: niche ? "var(--accent-bright)" : "var(--text-secondary)" }}
                title={`${s.name} (${s.etf})${niche ? " — your hunting ground" : ""}`}
              >
                {niche ? "◆ " : ""}{s.name}
              </span>
              <div className="flex-1">
                <DivergingBar value={ret} max={maxAbs} color={color} />
              </div>
              <span className="w-[44px] shrink-0 text-right text-[10px] font-semibold tabular-nums" style={{ fontFamily: "var(--font-mono)", color }}>
                {ret >= 0 ? "+" : ""}{ret.toFixed(1)}%
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─── Top conviction ───────────────────────────────────────────────────────────

function TopConviction({ ranked }: { ranked: StockResult[] }) {
  const top = ranked
    .filter((s) => s.edge?.bearing?.state !== "DOWN")
    .map((s) => ({ s, blend: (s.composite + (s.ml_score ?? s.composite)) / 2 }))
    .sort((a, b) => b.blend - a.blend)
    .slice(0, 3)
    .map((x) => x.s);

  if (!top.length) return null;
  return (
    <div>
      <SectionHeader label="Top Conviction Today" color="var(--accent)" count={top.length} />
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
        {top.map((s) => (
          <StockCard key={s.ticker} stock={s} />
        ))}
      </div>
    </div>
  );
}

// ─── Position health ──────────────────────────────────────────────────────────

function PositionHealth({ items, ranked }: { items: WatchlistItem[]; ranked: StockResult[] }) {
  if (!items.length) return null;

  return (
    <div>
      <SectionHeader label="Position Health" color="var(--amber)" count={items.length} />
      <div className="glass rounded-2xl overflow-hidden">
        {items.map((item, i) => {
          const price = item.current_price || item.quote?.price || 0;
          const r = ranked.find((x) => x.ticker === item.ticker);
          const pulse = r?.edge?.pulse;
          const bearing = r?.edge?.bearing;

          const nearStop = !!(item.stop_loss && price > 0 && price > item.stop_loss && (price - item.stop_loss) / price <= 0.05);
          const breachedStop = !!(item.stop_loss && price > 0 && price <= item.stop_loss);
          const nearTarget = !!(item.target_price && price > 0 && price < item.target_price && (item.target_price - price) / price <= 0.05);

          // Position of current price between stop and target
          let rangePos: number | null = null;
          if (item.stop_loss && item.target_price && item.target_price > item.stop_loss && price > 0) {
            rangePos = Math.max(0, Math.min(1, (price - item.stop_loss) / (item.target_price - item.stop_loss))) * 100;
          }

          return (
            <div
              key={item.ticker}
              className="flex items-center gap-3 px-3 py-2.5"
              style={{
                backgroundColor: i % 2 === 1 ? "rgba(255,255,255,0.02)" : "transparent",
                borderTop: i > 0 ? "1px solid var(--border-subtle)" : "none",
              }}
            >
              <TickerLogo ticker={item.ticker} size={22} />
              <div className="w-[70px]">
                <div className="text-[12px] font-bold leading-none">{item.ticker}</div>
                {item.shares > 0 && (
                  <div className="text-[9px] mt-0.5" style={{ color: "var(--text-muted)" }}>{item.shares} sh</div>
                )}
              </div>
              <span className="text-[12px] tabular-nums w-[64px]" style={{ fontFamily: "var(--font-mono)", color: "var(--text-secondary)" }}>
                {price > 0 ? `$${price.toFixed(2)}` : "—"}
              </span>
              <span
                className="text-[12px] font-bold tabular-nums w-[58px]"
                style={{ fontFamily: "var(--font-mono)", color: item.pnl_pct >= 0 ? "var(--green)" : "var(--red)" }}
              >
                {item.pnl_pct >= 0 ? "+" : ""}{item.pnl_pct.toFixed(1)}%
              </span>

              {rangePos != null ? (
                <div className="flex-1 flex items-center gap-1.5 min-w-[120px]">
                  <span className="text-[9px] tabular-nums" style={{ fontFamily: "var(--font-mono)", color: "var(--red)" }}>
                    ${item.stop_loss!.toFixed(2)}
                  </span>
                  <div className="relative flex-1 h-[5px] rounded-full" style={{ background: "linear-gradient(90deg, var(--red-dim), var(--bg-elevated) 30%, var(--green-dim))" }}>
                    <div
                      className="absolute top-1/2 w-[9px] h-[9px] rounded-full"
                      style={{
                        left: `${rangePos}%`,
                        transform: "translate(-50%, -50%)",
                        backgroundColor: rangePos < 25 ? "var(--red)" : rangePos > 75 ? "var(--green)" : "var(--amber)",
                        border: "2px solid var(--bg-surface)",
                      }}
                    />
                  </div>
                  <span className="text-[9px] tabular-nums" style={{ fontFamily: "var(--font-mono)", color: "var(--green)" }}>
                    ${item.target_price!.toFixed(2)}
                  </span>
                </div>
              ) : (
                <div className="flex-1" />
              )}

              <div className="flex items-center gap-1.5 shrink-0">
                {breachedStop && <Badge text="STOP HIT" bg="var(--red-dim)" fg="var(--red)" />}
                {nearStop && !breachedStop && <Badge text="NEAR STOP" bg="var(--red-dim)" fg="var(--red)" />}
                {nearTarget && <Badge text="NEAR TARGET" bg="var(--green-dim)" fg="var(--green)" />}
                {pulse?.state === "WILD" && <Badge text="WILD VOL" bg="var(--amber-dim)" fg="var(--amber)" />}
                {bearing?.state === "DOWN" && <Badge text="DOWNTREND" bg="var(--red-dim)" fg="var(--red)" />}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Badge({ text, bg, fg }: { text: string; bg: string; fg: string }) {
  return (
    <span className="text-[8px] font-bold uppercase tracking-[0.06em] px-1.5 py-[2px] rounded" style={{ backgroundColor: bg, color: fg }}>
      {text}
    </span>
  );
}

// ─── Top Setups (the synthesized answer) ──────────────────────────────────────

const GRADE_COLOR: Record<string, string> = {
  A: "var(--green)",
  B: "var(--accent-cyan)",
  C: "var(--amber)",
};

function fmtPx(n?: number) {
  if (!n) return "—";
  return n >= 1 ? `$${n.toFixed(2)}` : `$${n.toFixed(3)}`;
}

function TopSetups({ ranked, stats }: { ranked: StockResult[]; stats?: Record<string, SetupStat> | null }) {
  const setups = ranked
    .filter((s) => ["A", "B", "C"].includes(s.setup?.grade ?? ""))
    .sort((a, b) => (b.setup?.score ?? 0) - (a.setup?.score ?? 0))
    .slice(0, 8);
  const n = { A: 0, B: 0, C: 0 } as Record<string, number>;
  ranked.forEach((s) => { const g = s.setup?.grade; if (g && g in n) n[g]++; });

  return (
    <div className="glass-strong glow-top rounded-2xl p-4" style={{ ["--glow-color" as string]: "var(--green)" }}>
      <div className="flex items-center justify-between mb-3">
        <div>
          <div className="text-[15px] font-bold" style={{ letterSpacing: "-0.02em" }}>Top Setups Today</div>
          <div className="text-[11px] mt-0.5" style={{ color: "var(--text-muted)" }}>
            The synthesized answer — graded, with the action. Everything else is filtered out.
          </div>
        </div>
        <div className="flex gap-1.5 text-[11px]">
          {(["A", "B", "C"] as const).map((g) => (
            <span key={g} className="px-2 py-[3px] rounded-md font-bold tabular-nums"
              style={{ backgroundColor: `color-mix(in srgb, ${GRADE_COLOR[g]} 16%, transparent)`, color: GRADE_COLOR[g] }}>
              {n[g]} {g}
            </span>
          ))}
        </div>
      </div>

      {setups.length === 0 ? (
        <div className="h-20 flex items-center justify-center text-[12px]" style={{ color: "var(--text-muted)" }}>
          No A/B/C setups right now — the tape is between opportunities.
        </div>
      ) : (
        <div className="space-y-1.5">
          {setups.map((s) => {
            const v = s.setup!;
            const color = GRADE_COLOR[v.grade] ?? "var(--text-muted)";
            return (
              <button
                key={s.ticker}
                onClick={() => openTicker(s)}
                className="w-full flex items-center gap-3 rounded-xl px-3 py-2.5 text-left transition-colors hover:bg-[rgba(255,255,255,0.03)]"
                style={{ background: "rgba(255,255,255,0.02)", border: "1px solid var(--border-subtle)" }}
              >
                <span className="shrink-0 w-7 h-7 rounded-lg flex items-center justify-center text-[15px] font-bold"
                  style={{ backgroundColor: `color-mix(in srgb, ${color} 18%, transparent)`, color }}>
                  {v.grade}
                </span>
                <TickerLogo ticker={s.ticker} size={22} />
                <div className="w-[88px] shrink-0">
                  <div className="text-[13px] font-bold leading-none">{s.ticker}</div>
                  <div className="text-[10px] tabular-nums mt-0.5" style={{ fontFamily: "var(--font-mono)", color: "var(--text-muted)" }}>{fmtPx(s.quote?.price)}</div>
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5">
                    <span className="text-[11px] font-semibold" style={{ color }}>{v.setup}</span>
                    {(() => {
                      const st = stats?.[v.setup];
                      if (!st || st.n < 8) return null;
                      const good = st.avg_r > 0;
                      return (
                        <span className="text-[9px] px-1 py-[1px] rounded tabular-nums"
                          title={`Historical backtest: ${st.win_rate}% hit target, ${st.avg_r > 0 ? "+" : ""}${st.avg_r}R expectancy over ${st.n} past setups`}
                          style={{ backgroundColor: good ? "color-mix(in srgb, var(--green) 14%, transparent)" : "color-mix(in srgb, var(--red) 14%, transparent)", color: good ? "var(--green)" : "var(--red)" }}>
                          {st.win_rate}% · {st.avg_r > 0 ? "+" : ""}{st.avg_r}R
                        </span>
                      );
                    })()}
                  </div>
                  <div className="text-[11px] truncate" style={{ color: "var(--text-secondary)" }}>{v.thesis}</div>
                  {v.action && (
                    <div className="text-[10px] truncate mt-0.5" style={{ color: "var(--accent-bright)" }}>→ {v.action}</div>
                  )}
                </div>
                <span className="shrink-0 text-[16px] font-bold tabular-nums" style={{ fontFamily: "var(--font-mono)", color }}>{v.score}</span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ─── Root ─────────────────────────────────────────────────────────────────────

export function Overview({ data, onNavigate }: {
  data: DashboardResponse | null;
  onNavigate?: (tab: string) => void;
}) {
  const [regime, setRegime] = useState<MarketRegimeResponse | null>(null);
  const [brief, setBrief] = useState<Brief | null>(null);
  const [squeeze, setSqueeze] = useState<SqueezeCandidate[]>([]);
  const [watchlist, setWatchlist] = useState<WatchlistItem[]>([]);

  const refresh = useCallback(() => {
    getMarketRegime().then(setRegime).catch(() => {});
    getBrief().then((r) => setBrief(r.brief)).catch(() => {});
    getSqueezeScan()
      .then((r) => setSqueeze((r.results ?? []).filter((c) => c.score >= 60).slice(0, 5)))
      .catch(() => {});
    getWatchlist().then((r) => setWatchlist(r.items ?? [])).catch(() => {});
  }, []);

  // Refresh when the scan turns over, plus a 5-minute heartbeat
  useEffect(() => { refresh(); }, [refresh, data?.last_scan]);
  useEffect(() => {
    const i = setInterval(refresh, 5 * 60_000);
    return () => clearInterval(i);
  }, [refresh]);

  const ranked = data?.ranked ?? [];

  return (
    <div className="p-5 max-w-[1200px] space-y-4">
      {/* THE answer — what's actually a good pick right now */}
      <TopSetups ranked={ranked} stats={data?.setup_stats} />

      {/* Regime band */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <MoodCard regime={regime} />
        <VolatilityCard regime={regime} />
        <SmallcapCard regime={regime} />
        <BreadthCard regime={regime} data={data} />
      </div>

      {/* Daily brief */}
      <BriefCard brief={brief} />

      {/* AI Macro Desk + Capital Flow */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 items-start">
        <MacroDeskCard desk={regime?.available ? regime.macro_desk : undefined} />
        <CapitalFlowCard flow={regime?.available ? regime.capital_flow : undefined} />
      </div>

      {/* What changed + sector heat */}
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_340px] gap-4 items-start">
        <WhatChanged data={data} squeeze={squeeze} onNavigate={onNavigate} />
        <SectorHeatPanel sectors={regime?.available ? regime.sectors ?? [] : []} />
      </div>

      {/* Top conviction */}
      <TopConviction ranked={ranked} />

      {/* Position health */}
      <PositionHealth items={watchlist} ranked={ranked} />
    </div>
  );
}
