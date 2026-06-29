"use client";

import { useCallback, useEffect, useState } from "react";
import {
  EdgeGauge,
  HistoryResponse,
  PriceHistory,
  StockResult,
  getHistory,
  getPriceHistory,
} from "@/lib/api";
import { Sparkline } from "./gauges";
import { TickerLogo } from "./TickerLogo";

// ─── Open the drawer from anywhere via a custom event ────────────────────────

export function openTicker(stock: StockResult) {
  window.dispatchEvent(new CustomEvent<StockResult>("open-ticker", { detail: stock }));
}

// ─── Helpers (mirror StockCard) ──────────────────────────────────────────────

const BUCKETS = [
  { key: "fundamentals", label: "Fundamentals" },
  { key: "momentum", label: "Momentum" },
  { key: "catalyst", label: "Catalyst" },
  { key: "insider", label: "Insider" },
  { key: "sentiment", label: "News" },
] as const;

function scoreColor(s: number) {
  if (s >= 75) return "var(--green)";
  if (s >= 60) return "var(--green-bright)";
  if (s >= 40) return "var(--amber)";
  return "var(--red)";
}
function edgeColor(state: string): string {
  switch (state) {
    case "HEALTHY": case "CLEAN UP": case "TRADABLE": return "var(--green)";
    case "CROWDED": case "CHOPPY UP": return "var(--amber)";
    case "WILD": case "CHOPPY DOWN": case "DOWN": return "var(--red)";
    case "QUIET": return "var(--accent-bright)";
    default: return "var(--text-muted)";
  }
}
function fmtPrice(n?: number) {
  if (!n) return "—";
  return n >= 1 ? `$${n.toFixed(2)}` : `$${n.toFixed(3)}`;
}
function fmtMcap(n?: number) {
  if (!n) return "";
  if (n >= 1e12) return `$${(n / 1e12).toFixed(1)}T`;
  if (n >= 1e9) return `$${(n / 1e9).toFixed(1)}B`;
  if (n >= 1e6) return `$${(n / 1e6).toFixed(0)}M`;
  return `$${(n / 1e3).toFixed(0)}K`;
}

// ─── Price chart (daily closes) ──────────────────────────────────────────────

function PriceChart({ ph }: { ph: PriceHistory | null }) {
  if (!ph || ph.points.length < 2) {
    return <div className="h-[120px] flex items-center justify-center text-[11px]" style={{ color: "var(--text-muted)" }}>No price history</div>;
  }
  const pts = ph.points;
  const closes = pts.map((p) => p.close);
  const min = Math.min(...closes), max = Math.max(...closes);
  const range = max - min || 1;
  const W = 320, H = 120, padB = 16, padT = 6;
  const up = closes[closes.length - 1] >= closes[0];
  const color = up ? "var(--green)" : "var(--red)";
  const sx = (i: number) => (i / (pts.length - 1)) * W;
  const sy = (c: number) => H - padB - ((c - min) / range) * (H - padB - padT);
  const line = pts.map((p, i) => `${sx(i).toFixed(1)},${sy(p.close).toFixed(1)}`).join(" ");
  const area = `M 0,${H - padB} L ${line.replace(/ /g, " L ")} L ${W},${H - padB} Z`;
  const chg = ((closes[closes.length - 1] - closes[0]) / closes[0]) * 100;

  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto" }}>
        <defs>
          <linearGradient id="pchart" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity="0.28" />
            <stop offset="100%" stopColor={color} stopOpacity="0" />
          </linearGradient>
        </defs>
        <path d={area} fill="url(#pchart)" />
        <polyline points={line} fill="none" stroke={color} strokeWidth={1.8} strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
      </svg>
      <div className="flex justify-between text-[9px] mt-1" style={{ color: "var(--text-muted)" }}>
        <span>{pts[0].date}</span>
        <span style={{ color }}>{chg >= 0 ? "+" : ""}{chg.toFixed(1)}% · {pts.length}d</span>
        <span>{pts[pts.length - 1].date}</span>
      </div>
    </div>
  );
}

// ─── Edge gauge detail ───────────────────────────────────────────────────────

function GaugeBlock({ name, gauge }: { name: string; gauge?: EdgeGauge }) {
  if (!gauge) return null;
  const color = edgeColor(gauge.state);
  return (
    <div className="rounded-xl p-3" style={{ background: "rgba(255,255,255,0.025)", border: `1px solid ${color}25` }}>
      <div className="flex items-center justify-between mb-1">
        <span className="text-[9px] uppercase tracking-[0.08em]" style={{ color: "var(--text-muted)" }}>{name}</span>
        <span className="text-[12px] font-bold" style={{ color }}>{gauge.state}</span>
      </div>
      <div className="text-[10px] mb-1.5" style={{ color: "var(--text-secondary)" }}>{gauge.summary}</div>
      {gauge.advice.map((a, i) => (
        <div key={i} className="flex gap-1.5 text-[10px] leading-snug" style={{ color: "var(--text-muted)" }}>
          <span style={{ color }}>›</span><span>{a}</span>
        </div>
      ))}
    </div>
  );
}

const COILED_COLOR: Record<string, string> = {
  BREAKING: "var(--green-bright)",
  COILED: "var(--accent-cyan)",
  BASING: "var(--green)",
  EXTENDED: "var(--amber)",
  "NO SETUP": "var(--text-muted)",
};

function CoiledBlockView({ c }: { c: NonNullable<StockResult["coiled"]> }) {
  const color = COILED_COLOR[c.state] ?? "var(--text-muted)";
  return (
    <div className="rounded-xl p-3" style={{ background: "rgba(255,255,255,0.025)", border: `1px solid ${color}30` }}>
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-[14px] font-bold tracking-[0.04em]" style={{ color }}>{c.state}</span>
        <span className="text-[13px] font-bold tabular-nums" style={{ fontFamily: "var(--font-mono)", color }}>{c.coiled_score.toFixed(0)}<span className="text-[9px]" style={{ color: "var(--text-muted)" }}>/100</span></span>
      </div>
      <div className="text-[10px] mb-2" style={{ color: "var(--text-secondary)" }}>{c.summary}</div>
      <div className="grid grid-cols-4 gap-2 mb-2">
        <Metric label="compress" value={c.squeeze_pctile != null ? `${c.squeeze_pctile}%ile` : "—"} />
        <Metric label="base" value={c.range_pct != null ? `${c.range_pct.toFixed(0)}%` : "—"} />
        <Metric label="vs 50MA" value={c.ext_pct != null ? `${c.ext_pct >= 0 ? "+" : ""}${c.ext_pct.toFixed(0)}%` : "—"} />
        <Metric label="3m move" value={c.ret_3m_pct != null ? `${c.ret_3m_pct >= 0 ? "+" : ""}${c.ret_3m_pct.toFixed(0)}%` : "—"} />
      </div>
      {c.reasons && c.reasons.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {c.reasons.map((r, i) => (
            <span key={i} className="text-[9px] px-1.5 py-[2px] rounded" style={{ background: `color-mix(in srgb, ${color} 12%, transparent)`, color }}>{r}</span>
          ))}
        </div>
      )}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="text-center">
      <div className="text-[12px] font-bold tabular-nums leading-none" style={{ fontFamily: "var(--font-mono)", color: "var(--text-primary)" }}>{value}</div>
      <div className="text-[8px] uppercase tracking-[0.04em] mt-1" style={{ color: "var(--text-muted)" }}>{label}</div>
    </div>
  );
}

const SMAD_COLOR: Record<string, string> = {
  SPRING: "var(--green-bright)",
  "BOS IMPULSE": "var(--green)",
  "DEMAND RETEST": "var(--accent-cyan)",
  ACCUMULATION: "var(--accent-bright)",
  "BULL TRAP": "var(--red)",
  NONE: "var(--text-muted)",
};

function SmadView({ s }: { s: NonNullable<StockResult["smad"]> }) {
  const color = SMAD_COLOR[s.state] ?? "var(--text-muted)";
  const comp = s.components;
  const bars: [string, number][] = comp
    ? [["base", comp.base], ["sweep", comp.sweep_reclaim], ["impulse", comp.impulse_bos], ["retest", comp.zone_retest]]
    : [];
  return (
    <div className="rounded-xl p-3" style={{ background: "rgba(255,255,255,0.025)", border: `1px solid ${color}30` }}>
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-[14px] font-bold tracking-[0.04em]" style={{ color }}>{s.state}</span>
        <span className="text-[13px] font-bold tabular-nums" style={{ fontFamily: "var(--font-mono)", color }}>
          {s.smad_score.toFixed(0)}<span className="text-[9px]" style={{ color: "var(--text-muted)" }}>/100</span>
        </span>
      </div>
      <div className="text-[10px] mb-2.5" style={{ color: "var(--text-secondary)" }}>{s.summary}</div>
      {bars.length > 0 && (
        <div className="space-y-1 mb-2">
          {bars.map(([k, val]) => (
            <div key={k} className="flex items-center gap-2">
              <span className="w-[52px] text-[9px] uppercase" style={{ color: "var(--text-muted)" }}>{k}</span>
              <div className="flex-1 h-[5px] rounded-full" style={{ backgroundColor: "rgba(255,255,255,0.06)" }}>
                <div className="h-full rounded-full" style={{ width: `${val * 100}%`, backgroundColor: val > 0 ? color : "transparent" }} />
              </div>
              <span className="w-[26px] text-right text-[9px] tabular-nums" style={{ fontFamily: "var(--font-mono)", color: "var(--text-muted)" }}>{(val * 100).toFixed(0)}</span>
            </div>
          ))}
        </div>
      )}
      {s.demand_zone && (
        <div className="text-[10px] mb-1.5" style={{ color: "var(--text-secondary)" }}>
          Demand zone <b style={{ color }}>${s.demand_zone[0]}–${s.demand_zone[1]}</b> (buy the retest, stop below)
        </div>
      )}
      {s.reasons && s.reasons.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {s.reasons.map((r, i) => (
            <span key={i} className="text-[9px] px-1.5 py-[2px] rounded" style={{ background: `color-mix(in srgb, ${color} 12%, transparent)`, color }}>{r}</span>
          ))}
        </div>
      )}
    </div>
  );
}

function Section({ title, children, right }: { title: string; children: React.ReactNode; right?: React.ReactNode }) {
  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <span className="text-[10px] uppercase tracking-[0.1em] font-bold" style={{ color: "var(--text-muted)" }}>{title}</span>
        {right}
      </div>
      {children}
    </div>
  );
}

// ─── Drawer ──────────────────────────────────────────────────────────────────

export function TickerDrawer() {
  const [stock, setStock] = useState<StockResult | null>(null);
  const [price, setPrice] = useState<PriceHistory | null>(null);
  const [hist, setHist] = useState<HistoryResponse | null>(null);

  const close = useCallback(() => setStock(null), []);

  useEffect(() => {
    function onOpen(e: Event) {
      const s = (e as CustomEvent<StockResult>).detail;
      setStock(s);
      setPrice(null);
      setHist(null);
      getPriceHistory(s.ticker).then(setPrice).catch(() => {});
      getHistory(s.ticker).then(setHist).catch(() => {});
    }
    window.addEventListener("open-ticker", onOpen as EventListener);
    return () => window.removeEventListener("open-ticker", onOpen as EventListener);
  }, []);

  useEffect(() => {
    function onKey(e: KeyboardEvent) { if (e.key === "Escape") close(); }
    if (stock) window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [stock, close]);

  if (!stock) return null;

  const q = stock.quote;
  const edge = stock.edge;
  const tilt = stock.tilt;
  const sq = stock.short_squeeze;
  const comp = stock.competitors;

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end"
      style={{ background: "rgba(2,5,14,0.72)", backdropFilter: "blur(6px)", WebkitBackdropFilter: "blur(6px)" }}
      onClick={close}
    >
      <div
        className="h-full overflow-y-auto glow-top"
        style={{
          width: "min(460px, 92vw)",
          borderRadius: "20px 0 0 20px",
          // Dashboard's navy gradient — opaque, so content is readable (was translucent glass)
          background:
            "radial-gradient(120% 55% at 50% 0%, rgba(109,93,252,0.16), transparent 60%), " +
            "linear-gradient(165deg, #141c38 0%, #0b1124 55%, #0d1226 100%)",
          borderLeft: "1px solid var(--glass-border-strong)",
          boxShadow: "-26px 0 64px rgba(2,6,20,0.6)",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header — opaque so scrolling content doesn't bleed through */}
        <div className="sticky top-0 z-10 px-5 pt-4 pb-3" style={{ background: "linear-gradient(180deg, #161e3c, #121a36)", borderBottom: "1px solid var(--glass-border-strong)" }}>
          <div className="flex items-start gap-3">
            <TickerLogo ticker={stock.ticker} size={40} />
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-[20px] font-bold" style={{ letterSpacing: "-0.02em" }}>{stock.ticker}</span>
                {q?.price ? <span className="text-[14px] font-semibold tabular-nums" style={{ fontFamily: "var(--font-mono)" }}>{fmtPrice(q.price)}</span> : null}
                {q?.change_pct != null && q.change_pct !== 0 && (
                  <span className="text-[12px] font-semibold tabular-nums" style={{ fontFamily: "var(--font-mono)", color: q.change_pct >= 0 ? "var(--green)" : "var(--red)" }}>
                    {q.change_pct >= 0 ? "+" : ""}{q.change_pct.toFixed(2)}%
                  </span>
                )}
              </div>
              <div className="text-[11px] truncate" style={{ color: "var(--text-secondary)" }}>{q?.name ?? stock.ticker}</div>
              <div className="text-[10px] mt-0.5" style={{ color: "var(--text-muted)" }}>
                {fmtMcap(q?.market_cap)} {q?.industry || q?.sector || ""}
              </div>
            </div>
            <button onClick={close} className="w-7 h-7 rounded-full flex items-center justify-center text-[15px] shrink-0" style={{ background: "var(--bg-elevated)", color: "var(--text-secondary)" }}>✕</button>
          </div>
          {/* Score row */}
          <div className="flex items-center gap-2 mt-3 flex-wrap">
            <Pill label="Composite" value={stock.composite.toFixed(0)} color={scoreColor(stock.composite)} />
            {stock.calibrated_p_win != null && (
              <Pill label="Measured win 5d" value={`${(stock.calibrated_p_win * 100).toFixed(0)}%`} color="var(--green)" />
            )}
            {tilt && Math.abs(tilt.factor - 1) >= 0.04 && (
              <Pill
                label="Regime"
                value={`${tilt.factor >= 1 ? "+" : "−"}${Math.abs((tilt.factor - 1) * 100).toFixed(0)}%`}
                color={tilt.factor >= 1 ? "var(--green)" : "var(--red)"}
              />
            )}
          </div>
        </div>

        <div className="px-5 py-4 space-y-5">
          {q?.description && (
            <p className="text-[11px] leading-snug" style={{ color: "var(--text-secondary)" }}>{q.description}</p>
          )}

          <Section title="Price · 6 months"><PriceChart ph={price} /></Section>

          {hist && hist.points.length >= 3 && (
            <Section title="Score trajectory" right={<span className="text-[9px]" style={{ color: "var(--text-muted)" }}>{hist.points.length} scans</span>}>
              <Sparkline height={44} series={[
                { points: hist.points.map((p) => p.composite), color: "var(--accent-bright)" },
                { points: hist.points.map((p) => p.ml_score), color: "#ec4899", dashed: true },
              ]} />
            </Section>
          )}

          {stock.coiled?.available && (
            <Section title="Pre-breakout setup">
              <CoiledBlockView c={stock.coiled} />
            </Section>
          )}

          {stock.smad?.available && stock.smad.state !== "NONE" && (
            <Section title="Smart-money · supply/demand">
              <SmadView s={stock.smad} />
            </Section>
          )}

          <Section title="Signal breakdown">
            <div className="grid grid-cols-5 gap-1.5">
              {BUCKETS.map((b) => {
                const raw = stock.breakdown[b.key]?.raw ?? 0;
                return (
                  <div key={b.key} className="rounded-lg px-1.5 py-2 text-center" style={{ background: "rgba(255,255,255,0.025)", border: `1px solid ${raw >= 60 ? scoreColor(raw) + "40" : "var(--border-subtle)"}` }}>
                    <div className="text-[15px] font-bold tabular-nums leading-none" style={{ color: scoreColor(raw), fontFamily: "var(--font-mono)" }}>{raw.toFixed(0)}</div>
                    <div className="text-[8px] mt-1" style={{ color: "var(--text-muted)" }}>{b.label}</div>
                  </div>
                );
              })}
            </div>
          </Section>

          {edge?.available && (
            <Section title="Trading regime">
              <div className="space-y-2">
                <GaugeBlock name="Flow" gauge={edge.flow} />
                <GaugeBlock name="Bearing" gauge={edge.bearing} />
                <GaugeBlock name="Pulse" gauge={edge.pulse} />
              </div>
            </Section>
          )}

          {tilt && tilt.reasons.length > 0 && (
            <Section title="Why it ranks here (regime tilt)">
              <div className="rounded-xl p-3 space-y-1" style={{ background: "rgba(255,255,255,0.025)", border: "1px solid var(--border-subtle)" }}>
                {tilt.reasons.map((r, i) => {
                  const pos = r.trim().startsWith("+");
                  return (
                    <div key={i} className="flex gap-1.5 text-[11px]">
                      <span style={{ color: pos ? "var(--green)" : "var(--red)" }}>{pos ? "▲" : "▼"}</span>
                      <span style={{ color: "var(--text-secondary)" }}>{r.replace(/^[+−]\s*/, "")}</span>
                    </div>
                  );
                })}
              </div>
            </Section>
          )}

          {sq && sq.score >= 45 && (
            <Section title="Short squeeze">
              <div className="rounded-xl p-3" style={{ background: "#ec489912", border: "1px solid #ec489930" }}>
                <div className="flex items-center gap-2 mb-1.5">
                  <span className="text-[16px] font-bold tabular-nums" style={{ color: "#ec4899", fontFamily: "var(--font-mono)" }}>{sq.score.toFixed(0)}</span>
                  <span className="text-[10px] uppercase font-semibold" style={{ color: "#ec489990" }}>{sq.level}</span>
                </div>
                <div className="flex flex-wrap gap-3 text-[11px]" style={{ color: "var(--text-secondary)" }}>
                  {sq.short_pct_float > 0 && <span>Float short <b style={{ color: "#ec4899" }}>{sq.short_pct_float}%</b></span>}
                  {sq.days_to_cover > 0 && <span>DTC <b style={{ color: "#ec4899" }}>{sq.days_to_cover}d</b></span>}
                  {sq.float_shares > 0 && <span>{(sq.float_shares / 1e6).toFixed(1)}M float</span>}
                </div>
              </div>
            </Section>
          )}

          {comp?.has_peers && comp.peers.length > 0 && (
            <Section title="Sector peers · 3-month" right={comp.lagging ? <span className="text-[10px]" style={{ color: "var(--amber)" }}>Lagging {comp.gap_3m}%</span> : undefined}>
              <div className="flex flex-wrap gap-1.5">
                {comp.peers.slice(0, 6).map((p) => (
                  <div key={p.ticker} className="flex items-center gap-1.5 px-2 py-1 rounded-lg" style={{ background: "rgba(255,255,255,0.025)", border: "1px solid var(--border-subtle)" }}>
                    <TickerLogo ticker={p.ticker} size={14} />
                    <span className="text-[10px] font-medium">{p.ticker}</span>
                    <span className="text-[10px] tabular-nums" style={{ fontFamily: "var(--font-mono)", color: p.ret_3m >= 0 ? "var(--green)" : "var(--red)" }}>{p.ret_3m >= 0 ? "+" : ""}{p.ret_3m}%</span>
                  </div>
                ))}
              </div>
            </Section>
          )}
        </div>
      </div>
    </div>
  );
}

function Pill({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div className="rounded-lg px-2.5 py-1" style={{ background: `color-mix(in srgb, ${color} 14%, transparent)`, border: `1px solid color-mix(in srgb, ${color} 30%, transparent)` }}>
      <span className="text-[14px] font-bold tabular-nums" style={{ fontFamily: "var(--font-mono)", color }}>{value}</span>
      <span className="text-[9px] ml-1.5 uppercase tracking-[0.05em]" style={{ color: "var(--text-muted)" }}>{label}</span>
    </div>
  );
}
