"use client";

import { StockResult, BucketScore, EdgeGauge, HistoryResponse, addToWatchlist, getHistory } from "@/lib/api";
import { TickerLogo } from "./TickerLogo";
import { Sparkline } from "./gauges";
import { openTicker } from "./TickerDrawer";
import { useEffect, useState } from "react";

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
    case "HEALTHY":
    case "CLEAN UP":
    case "TRADABLE":
      return "var(--green)";
    case "CROWDED":
    case "CHOPPY UP":
      return "var(--amber)";
    case "WILD":
    case "CHOPPY DOWN":
    case "DOWN":
      return "var(--red)";
    case "QUIET":
      return "var(--accent-bright)";
    default: // THIN, FLAT, UNKNOWN
      return "var(--text-muted)";
  }
}

function EdgePill({ name, gauge }: { name: string; gauge?: EdgeGauge }) {
  if (!gauge) return null;
  const color = edgeColor(gauge.state);
  return (
    <div
      className="flex-1 rounded px-2 py-1.5 cursor-help"
      style={{ backgroundColor: "var(--bg-primary)", border: `1px solid ${color}30` }}
      title={`${gauge.summary}\n${gauge.advice.map((a) => `• ${a}`).join("\n")}`}
    >
      <div className="text-[8px] uppercase tracking-[0.08em]" style={{ color: "var(--text-muted)" }}>
        {name}
      </div>
      <div className="text-[10px] font-bold mt-0.5 truncate" style={{ color }}>
        {gauge.state}
      </div>
    </div>
  );
}

function formatMcap(n: number): string {
  if (!n) return "";
  if (n >= 1e12) return `$${(n / 1e12).toFixed(1)}T`;
  if (n >= 1e9) return `$${(n / 1e9).toFixed(1)}B`;
  if (n >= 1e6) return `$${(n / 1e6).toFixed(0)}M`;
  return `$${(n / 1e3).toFixed(0)}K`;
}

function formatPrice(n: number): string {
  if (!n) return "—";
  if (n >= 100) return `$${n.toFixed(2)}`;
  if (n >= 1) return `$${n.toFixed(2)}`;
  return `$${n.toFixed(3)}`;
}

function buildThesis(stock: StockResult): string {
  const bits: string[] = [];
  const early = stock.early_detection?.score ?? 0;
  const bd = stock.breakdown;
  const comp = stock.competitors;

  if (early >= 70) bits.push("Early-stage setup");
  if (bd.fundamentals.raw >= 70 && bd.momentum.raw < 50) bits.push("strong fundamentals, price hasn't caught up");
  else if (bd.fundamentals.raw >= 70) bits.push("solid fundamentals");
  if (bd.momentum.raw >= 70) bits.push("momentum breakout");
  if (bd.catalyst.raw >= 70) bits.push("near-term catalyst");
  if (bd.insider.raw >= 70) bits.push("insider buying");
  if (comp?.lagging && comp.gap_3m > 20) bits.push(`lagging peers by ${comp.gap_3m}%`);

  return bits.length > 0 ? bits.join(" · ") : "Watchlist candidate";
}

function extractReasons(bd: Record<string, BucketScore>, early?: number) {
  const pros: string[] = [];
  const cons: string[] = [];

  if (bd.fundamentals.raw >= 65) {
    const c = bd.fundamentals.components;
    if (c.revenue_growth) pros.push(`Revenue ${c.revenue_growth}`);
    if (c.gross_margin) pros.push(`Margin ${c.gross_margin}`);
    if (c.cash && String(c.cash).includes("positive")) pros.push("Cash-flow positive");
  }
  if (bd.momentum.raw >= 60) {
    const c = bd.momentum.components;
    if (c.breakout && String(c.breakout).includes("golden")) pros.push("Golden cross");
    else if (c.breakout && String(c.breakout).includes("Above")) pros.push("Above 20/50 MA");
    if (c.rel_strength) pros.push(`RS ${c.rel_strength}`);
  }
  if (bd.catalyst.raw >= 60) {
    const c = bd.catalyst.components;
    if (c.earnings) pros.push(`Earnings ${String(c.earnings).toLowerCase()}`);
    if (c.target_upside) pros.push(`Target ${c.target_upside}`);
  }
  if (bd.insider.raw >= 60) {
    const c = bd.insider.components;
    if (c.insider_txns && String(c.insider_txns).includes("buying")) pros.push("Insider buys");
  }
  if (bd.sentiment.raw >= 60) {
    const c = bd.sentiment.components;
    if (c.mentions) pros.push(`${c.mentions} mentions`);
  }

  if (bd.fundamentals.raw < 40) {
    const c = bd.fundamentals.components;
    if (c.dilution) cons.push(`Dilution ${c.dilution}`);
  }
  if (bd.momentum.raw < 40) cons.push("Weak price action");
  if (bd.insider.raw < 35) {
    const c = bd.insider.components;
    if (c.insider_txns && String(c.insider_txns).includes("selling")) cons.push("Insider selling");
  }
  if (bd.catalyst.raw < 40) cons.push("No catalyst");

  return { pros: pros.slice(0, 3), cons: cons.slice(0, 2) };
}

export function StockCard({ stock }: { stock: StockResult }) {
  const [expanded, setExpanded] = useState(false);
  const [added, setAdded] = useState(false);
  const [adding, setAdding] = useState(false);
  const [history, setHistory] = useState<HistoryResponse | null>(null);
  const early = stock.early_detection?.score ?? 0;
  const comp = stock.competitors;
  const { pros, cons } = extractReasons(stock.breakdown, early);
  const thesis = buildThesis(stock);

  // Lazy-load score history the first time the card is expanded
  useEffect(() => {
    if (expanded && history === null) {
      getHistory(stock.ticker)
        .then(setHistory)
        .catch(() => setHistory({ ticker: stock.ticker, points: [], count: 0 }));
    }
  }, [expanded, history, stock.ticker]);

  async function handleAdd(e: React.MouseEvent) {
    e.stopPropagation();
    if (added || adding) return;
    setAdding(true);
    try {
      await addToWatchlist({
        ticker: stock.ticker,
        entry_price: stock.quote?.price,
      });
      setAdded(true);
    } catch {
      // ignore
    }
    setAdding(false);
  }

  return (
    <div className={`glass glass-hover rounded-2xl overflow-hidden${stock.multi_signal_alert ? " alert-ring" : ""}`}>
      {/* ── Top: logo + ticker + composite ── */}
      <div className="flex items-center gap-3 px-4 pt-4 pb-3">
        <TickerLogo ticker={stock.ticker} size={40} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <button
              onClick={() => openTicker(stock)}
              className="text-[17px] font-bold transition-colors hover:underline"
              style={{ letterSpacing: "-0.02em", textUnderlineOffset: 3 }}
              title="Open deep-dive"
            >
              {stock.ticker}
            </button>
            {stock.quote?.price ? (
              <span
                className="text-[13px] font-semibold tabular-nums"
                style={{ fontFamily: "var(--font-mono)", color: "var(--text-primary)" }}
              >
                {formatPrice(stock.quote.price)}
              </span>
            ) : null}
            {stock.quote?.change_pct !== undefined && stock.quote.change_pct !== 0 && (
              <span
                className="text-[11px] font-semibold tabular-nums"
                style={{
                  fontFamily: "var(--font-mono)",
                  color: stock.quote.change_pct >= 0 ? "var(--green)" : "var(--red)",
                }}
              >
                {stock.quote.change_pct >= 0 ? "+" : ""}
                {stock.quote.change_pct.toFixed(2)}%
              </span>
            )}
            {stock.multi_signal_alert && (
              <span
                className="text-[9px] font-bold uppercase tracking-[0.1em] px-1.5 py-[2px] rounded"
                style={{ backgroundColor: "var(--amber-dim)", color: "var(--amber)" }}
              >
                Alert
              </span>
            )}
            {stock.tilt && Math.abs(stock.tilt.factor - 1) >= 0.04 && (
              <span
                className="text-[9px] font-bold uppercase tracking-[0.08em] px-1.5 py-[2px] rounded cursor-help"
                style={{
                  backgroundColor: stock.tilt.factor >= 1 ? "var(--green-dim)" : "var(--red-dim)",
                  color: stock.tilt.factor >= 1 ? "var(--green)" : "var(--red)",
                }}
                title={`Regime tilt — ranked ${stock.tilt.factor >= 1 ? "up" : "down"} ${Math.abs((stock.tilt.factor - 1) * 100).toFixed(0)}% by current conditions:\n${stock.tilt.reasons.join("\n")}`}
              >
                {stock.tilt.factor >= 1 ? "▲" : "▼"} regime {stock.tilt.factor >= 1 ? "+" : "−"}{Math.abs((stock.tilt.factor - 1) * 100).toFixed(0)}%
              </span>
            )}
            {early >= 65 && (
              <span
                className="text-[9px] font-bold uppercase tracking-[0.1em] px-1.5 py-[2px] rounded"
                style={{ backgroundColor: "var(--green-dim)", color: "var(--green)" }}
              >
                Early
              </span>
            )}
            {stock.short_squeeze && stock.short_squeeze.score >= 60 && (
              <span
                className="text-[9px] font-bold uppercase tracking-[0.1em] px-1.5 py-[2px] rounded"
                style={{ backgroundColor: "#ec489920", color: "#ec4899" }}
                title={`Short squeeze score ${stock.short_squeeze.score} — ${stock.short_squeeze.short_pct_float}% float shorted, ${stock.short_squeeze.days_to_cover}d to cover`}
              >
                {stock.short_squeeze.level === "extreme" ? "Squeeze⚡" : "Squeeze"}
              </span>
            )}
          </div>
          {stock.quote?.name && stock.quote.name !== stock.ticker && (
            <p className="text-[11px] truncate mt-0.5" style={{ color: "var(--text-primary)" }}>
              {stock.quote.name}
            </p>
          )}
          <p className="text-[11px] mt-0.5" style={{ color: "var(--accent-bright)" }}>
            {thesis}
          </p>
          {stock.quote && (
            <div className="flex items-center gap-2 mt-1 text-[10px] flex-wrap" style={{ color: "var(--text-muted)" }}>
              {stock.quote.market_cap > 0 && (
                <span style={{ fontFamily: "var(--font-mono)" }}>
                  {formatMcap(stock.quote.market_cap)} mcap
                </span>
              )}
              {stock.quote.industry && <span>· {stock.quote.industry}</span>}
              {!stock.quote.industry && stock.quote.sector && <span>· {stock.quote.sector}</span>}
              {stock.quote.year_low > 0 && stock.quote.year_high > 0 && (
                <span style={{ fontFamily: "var(--font-mono)" }}>
                  · {formatPrice(stock.quote.year_low)}–{formatPrice(stock.quote.year_high)}
                </span>
              )}
            </div>
          )}
        </div>
        <div className="flex gap-3 shrink-0">
          <div className="text-right">
            <div
              className="text-[24px] font-bold tabular-nums leading-none"
              style={{
                color: scoreColor(stock.composite),
                fontFamily: "var(--font-mono)",
                letterSpacing: "-0.02em",
              }}
            >
              {stock.composite.toFixed(0)}
            </div>
            <div className="text-[9px] uppercase tracking-[0.1em] mt-0.5" style={{ color: "var(--text-muted)" }}>
              Score
            </div>
          </div>
          {stock.ml_score !== undefined && stock.ml_score > 0 && (
            <div className="text-right pl-3" style={{ borderLeft: "1px solid var(--border)" }}>
              <div
                className="text-[20px] font-bold tabular-nums leading-none"
                style={{
                  color: scoreColor(stock.ml_score),
                  fontFamily: "var(--font-mono)",
                  letterSpacing: "-0.02em",
                }}
              >
                {stock.ml_score.toFixed(0)}
              </div>
              <div className="text-[9px] uppercase tracking-[0.1em] mt-0.5" style={{ color: "var(--accent)" }}>
                AI
              </div>
            </div>
          )}
          <button
            onClick={handleAdd}
            disabled={added || adding}
            className="self-center w-7 h-7 rounded flex items-center justify-center text-[14px] transition-colors"
            style={{
              backgroundColor: added ? "var(--green-dim)" : "var(--bg-elevated)",
              color: added ? "var(--green)" : "var(--text-secondary)",
              border: "1px solid var(--border)",
            }}
            title={added ? "Added to watchlist" : "Add to watchlist"}
          >
            {added ? "✓" : adding ? "…" : "+"}
          </button>
        </div>
      </div>

      {/* ── Company description ── */}
      {stock.quote?.description && (
        <div className="px-4 pb-3 -mt-1">
          <p className="text-[11px] leading-snug" style={{ color: "var(--text-secondary)" }}>
            {stock.quote.description}
          </p>
        </div>
      )}

      {/* ── Score pills in a row ── */}
      <div className="flex gap-1.5 px-4 pb-3">
        {BUCKETS.map((b) => {
          const raw = stock.breakdown[b.key]?.raw ?? 0;
          return (
            <div
              key={b.key}
              className="flex-1 rounded px-2 py-1.5"
              style={{
                backgroundColor: "var(--bg-primary)",
                border: `1px solid ${raw >= 60 ? scoreColor(raw) + "40" : "var(--border)"}`,
              }}
            >
              <div
                className="text-[14px] font-bold tabular-nums leading-none"
                style={{ color: scoreColor(raw), fontFamily: "var(--font-mono)" }}
              >
                {raw.toFixed(0)}
              </div>
              <div className="text-[9px] mt-0.5" style={{ color: "var(--text-muted)" }}>
                {b.label}
              </div>
            </div>
          );
        })}
      </div>

      {/* ── Trading regime gauges (FLOW / BEARING / PULSE) ── */}
      {stock.edge?.available && (
        <div className="flex gap-1.5 px-4 pb-3 -mt-1">
          <EdgePill name="Flow" gauge={stock.edge.flow} />
          <EdgePill name="Bearing" gauge={stock.edge.bearing} />
          <EdgePill name="Pulse" gauge={stock.edge.pulse} />
        </div>
      )}

      {/* ── Why section ── */}
      {(pros.length > 0 || cons.length > 0) && (
        <div className="px-4 py-2.5 space-y-1" style={{ borderTop: "1px solid var(--border)" }}>
          {pros.map((p, i) => (
            <div key={i} className="flex items-center gap-1.5 text-[11px]">
              <span style={{ color: "var(--green)" }}>▲</span>
              <span style={{ color: "var(--text-secondary)" }}>{p}</span>
            </div>
          ))}
          {cons.map((c, i) => (
            <div key={i} className="flex items-center gap-1.5 text-[11px]">
              <span style={{ color: "var(--red)" }}>▼</span>
              <span style={{ color: "var(--text-secondary)" }}>{c}</span>
            </div>
          ))}
        </div>
      )}

      {/* ── ML Predictions ── */}
      {(stock.breakout || stock.pattern_match) && (
        <div className="px-4 py-3 space-y-2" style={{ borderTop: "1px solid var(--border)" }}>
          <div className="flex items-center gap-2">
            <span className="text-[9px] uppercase tracking-[0.1em] font-bold" style={{ color: "var(--accent)" }}>
              Model Signals
            </span>
            {/* The honest, measured number when calibration exists */}
            {stock.calibrated_p_win != null ? (
              <span
                className="text-[10px] font-bold tabular-nums px-1.5 py-[1px] rounded"
                style={{ color: "var(--green)", backgroundColor: "var(--green-dim)", fontFamily: "var(--font-mono)" }}
                title="Measured historical hit-rate (≥+10% in 5 trading days) for stocks at this composite score"
              >
                {(stock.calibrated_p_win * 100).toFixed(0)}% measured win
              </span>
            ) : (
              <span className="text-[9px]" style={{ color: "var(--text-muted)" }}>uncalibrated</span>
            )}
          </div>

          {/* Breakout model — relabeled: this is a heuristic score, not a probability */}
          {stock.breakout && stock.breakout.score >= 20 && (
            <div className="flex items-baseline gap-2 text-[11px]">
              <span style={{ color: "var(--text-muted)" }}>Breakout model:</span>
              <span
                className="font-bold tabular-nums"
                style={{
                  color: stock.breakout.score >= 60 ? "var(--green)" : stock.breakout.score >= 40 ? "var(--amber)" : "var(--text-secondary)",
                  fontFamily: "var(--font-mono)",
                }}
              >
                {stock.breakout.score.toFixed(0)}/100
              </span>
              <span className="text-[10px]" style={{ color: "var(--text-muted)" }}>
                ({stock.breakout.confidence} conf{stock.calibrated_p_win == null ? ", uncalibrated" : ""})
              </span>
            </div>
          )}

          {/* Closest historical setup — relabeled: cosine proximity, not a calibrated match */}
          {stock.pattern_match && stock.pattern_match.best_match && stock.pattern_match.score >= 50 && (
            <div className="text-[11px]">
              <div className="flex items-center gap-1.5 mb-1">
                <span style={{ color: "var(--text-muted)" }}>Closest setup:</span>
                <div className="flex items-center gap-1">
                  <span className="font-bold" style={{ color: "var(--text-primary)" }}>
                    {stock.pattern_match.best_match}
                  </span>
                  <span style={{ color: "var(--text-secondary)" }}>
                    (+{stock.pattern_match.matches[0]?.move_pct}% in {stock.pattern_match.matches[0]?.move_days}d)
                  </span>
                </div>
                <span className="text-[10px]" style={{ color: "var(--text-muted)" }} title="Feature-vector proximity to a hand-curated historical setup — not a probability">
                  {Math.min(99, stock.pattern_match.score).toFixed(0)} proximity
                </span>
              </div>
              {stock.pattern_match.matches[0]?.thesis && (
                <p className="text-[10px] italic" style={{ color: "var(--text-muted)" }}>
                  &ldquo;{stock.pattern_match.matches[0].thesis}&rdquo;
                </p>
              )}
            </div>
          )}

          {/* Sector catch-up */}
          {stock.sector_momentum && stock.sector_momentum.score >= 30 && (
            <div className="flex items-baseline gap-2 text-[11px]">
              <span style={{ color: "var(--text-muted)" }}>Catch-up model:</span>
              <span className="font-bold tabular-nums" style={{ color: "var(--amber)", fontFamily: "var(--font-mono)" }}>
                {stock.sector_momentum.score.toFixed(0)}/100
              </span>
            </div>
          )}

          {/* Breakout factors */}
          {stock.breakout?.factors && stock.breakout.factors.length > 0 && (
            <div className="flex flex-wrap gap-1 pt-1">
              {stock.breakout.factors.slice(0, 3).map((f, i) => (
                <span
                  key={i}
                  className="text-[9px] px-1.5 py-[2px] rounded"
                  style={{
                    backgroundColor: "var(--accent-dim)",
                    color: "var(--accent-bright)",
                    border: `1px solid var(--accent)40`,
                  }}
                >
                  {f}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── Short Squeeze ── */}
      {stock.short_squeeze && stock.short_squeeze.score >= 45 && (
        <div className="px-4 py-3 space-y-1.5" style={{ borderTop: "1px solid var(--border)" }}>
          <div className="flex items-center gap-2">
            <span className="text-[9px] uppercase tracking-[0.1em] font-bold" style={{ color: "#ec4899" }}>
              Short Squeeze
            </span>
            <span
              className="text-[11px] font-bold tabular-nums px-1.5 py-[1px] rounded"
              style={{
                color: stock.short_squeeze.score >= 75 ? "#ec4899" : stock.short_squeeze.score >= 60 ? "#f9a8d4" : "var(--text-muted)",
                backgroundColor: "#ec489915",
                fontFamily: "var(--font-mono)",
              }}
            >
              {stock.short_squeeze.score.toFixed(0)}
            </span>
            <span className="text-[10px] font-semibold uppercase tracking-[0.05em]" style={{ color: "#ec489980" }}>
              {stock.short_squeeze.level}
            </span>
          </div>
          <div className="flex flex-wrap gap-3 text-[11px]">
            {stock.short_squeeze.short_pct_float > 0 && (
              <span>
                <span style={{ color: "var(--text-muted)" }}>Float short: </span>
                <span className="font-bold tabular-nums" style={{ color: "#ec4899", fontFamily: "var(--font-mono)" }}>
                  {stock.short_squeeze.short_pct_float}%
                </span>
              </span>
            )}
            {stock.short_squeeze.days_to_cover > 0 && (
              <span>
                <span style={{ color: "var(--text-muted)" }}>DTC: </span>
                <span className="font-bold tabular-nums" style={{ color: "#ec4899", fontFamily: "var(--font-mono)" }}>
                  {stock.short_squeeze.days_to_cover}d
                </span>
              </span>
            )}
            {stock.short_squeeze.float_shares > 0 && (
              <span style={{ color: "var(--text-muted)" }}>
                {(stock.short_squeeze.float_shares / 1e6).toFixed(1)}M float
              </span>
            )}
          </div>
          {Object.keys(stock.short_squeeze.components).length > 0 && (
            <div className="flex flex-wrap gap-1 pt-0.5">
              {Object.entries(stock.short_squeeze.components).map(([k, v]) => (
                <span
                  key={k}
                  className="text-[9px] px-1.5 py-[2px] rounded"
                  style={{ backgroundColor: "#ec489912", color: "#f9a8d4", border: "1px solid #ec489930" }}
                >
                  {String(v)}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── Peers ── */}
      {comp?.has_peers && comp.peers.length > 0 && (
        <div className="px-4 py-2.5" style={{ borderTop: "1px solid var(--border)" }}>
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-[9px] uppercase tracking-[0.08em]" style={{ color: "var(--text-muted)" }}>
              Sector peers (3m)
            </span>
            {comp.lagging && (
              <span className="text-[10px]" style={{ color: "var(--amber)" }}>
                Lagging {comp.gap_3m}%
              </span>
            )}
          </div>
          <div className="flex gap-1.5 overflow-x-auto">
            {comp.peers.slice(0, 4).map((peer) => (
              <div
                key={peer.ticker}
                className="flex items-center gap-1.5 shrink-0 px-2 py-1 rounded"
                style={{ backgroundColor: "var(--bg-primary)", border: "1px solid var(--border)" }}
              >
                <TickerLogo ticker={peer.ticker} size={16} />
                <div>
                  <div className="text-[10px] font-medium leading-none">{peer.ticker}</div>
                  <div
                    className="text-[10px] tabular-nums leading-none mt-0.5"
                    style={{
                      color: peer.ret_3m >= 0 ? "var(--green)" : "var(--red)",
                      fontFamily: "var(--font-mono)",
                    }}
                  >
                    {peer.ret_3m >= 0 ? "+" : ""}{peer.ret_3m}%
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Expand ── */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full h-7 text-[10px] uppercase tracking-[0.08em] transition-colors hover:bg-[var(--bg-elevated)]"
        style={{
          color: "var(--text-muted)",
          borderTop: "1px solid var(--border)",
        }}
      >
        {expanded ? "Hide details" : "Show details"}
      </button>

      {expanded && (
        <div className="px-4 py-3 space-y-2.5" style={{ borderTop: "1px solid var(--border)" }}>
          {/* Score trajectory across past scans */}
          {history && history.points.length >= 3 && (
            <div>
              <div className="flex items-center justify-between mb-1">
                <span className="text-[11px] font-medium" style={{ color: "var(--text-secondary)" }}>
                  Score trajectory
                </span>
                <span className="flex items-center gap-2 text-[9px]" style={{ color: "var(--text-muted)" }}>
                  <span className="flex items-center gap-1">
                    <span className="w-[10px] h-[2px] rounded" style={{ backgroundColor: "var(--accent-bright)" }} />
                    Score
                  </span>
                  <span className="flex items-center gap-1">
                    <span className="w-[10px] h-[2px] rounded" style={{ backgroundColor: "#ec4899" }} />
                    AI
                  </span>
                  <span>{history.points.length} scans</span>
                </span>
              </div>
              <Sparkline
                height={40}
                series={[
                  { points: history.points.map((p) => p.composite), color: "var(--accent-bright)" },
                  { points: history.points.map((p) => p.ml_score), color: "#ec4899", dashed: true },
                ]}
              />
            </div>
          )}

          {BUCKETS.map((b) => {
            const bucket = stock.breakdown[b.key];
            if (!bucket) return null;
            return (
              <div key={b.key}>
                <div className="flex items-center justify-between mb-1">
                  <span className="text-[11px] font-medium" style={{ color: "var(--text-secondary)" }}>
                    {b.label}
                  </span>
                  <span className="text-[10px] tabular-nums" style={{ fontFamily: "var(--font-mono)", color: "var(--text-muted)" }}>
                    {bucket.raw.toFixed(1)} × {(bucket.weight * 100).toFixed(0)}% = {bucket.weighted.toFixed(1)}
                  </span>
                </div>
                {Object.keys(bucket.components).length > 0 && (
                  <div className="flex flex-wrap gap-1">
                    {Object.entries(bucket.components).map(([ck, cv]) => (
                      <span
                        key={ck}
                        className="text-[10px] px-1.5 py-[2px] rounded"
                        style={{
                          backgroundColor: "var(--bg-primary)",
                          color: "var(--text-secondary)",
                          border: "1px solid var(--border)",
                        }}
                      >
                        <span style={{ color: "var(--text-muted)" }}>{ck}:</span> {String(cv)}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
