"use client";

import { StockResult, BucketScore } from "@/lib/api";
import { TickerLogo } from "./TickerLogo";
import { useState } from "react";

const BUCKETS = [
  { key: "fundamentals", label: "Fundamentals" },
  { key: "momentum", label: "Momentum" },
  { key: "catalyst", label: "Catalyst" },
  { key: "insider", label: "Insider" },
  { key: "sentiment", label: "Sentiment" },
] as const;

function scoreColor(s: number) {
  if (s >= 75) return "var(--green)";
  if (s >= 60) return "var(--green-bright)";
  if (s >= 40) return "var(--amber)";
  return "var(--red)";
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
  const early = stock.early_detection?.score ?? 0;
  const comp = stock.competitors;
  const { pros, cons } = extractReasons(stock.breakdown, early);
  const thesis = buildThesis(stock);

  return (
    <div
      className="rounded-lg overflow-hidden transition-all"
      style={{
        backgroundColor: "var(--bg-surface)",
        border: `1px solid ${stock.multi_signal_alert ? "var(--amber)" : "var(--border)"}`,
      }}
    >
      {/* ── Top: logo + ticker + composite ── */}
      <div className="flex items-center gap-3 px-4 pt-4 pb-3">
        <TickerLogo ticker={stock.ticker} size={40} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-[17px] font-bold" style={{ letterSpacing: "-0.02em" }}>
              {stock.ticker}
            </span>
            {stock.multi_signal_alert && (
              <span
                className="text-[9px] font-bold uppercase tracking-[0.1em] px-1.5 py-[2px] rounded"
                style={{ backgroundColor: "var(--amber-dim)", color: "var(--amber)" }}
              >
                Alert
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
          </div>
          <p className="text-[11px] truncate" style={{ color: "var(--text-secondary)" }}>
            {thesis}
          </p>
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
        </div>
      </div>

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
              AI Prediction
            </span>
            {stock.ml_score !== undefined && (
              <span
                className="text-[11px] font-bold tabular-nums px-1.5 py-[1px] rounded"
                style={{
                  color: scoreColor(stock.ml_score),
                  backgroundColor: stock.ml_score >= 60 ? scoreColor(stock.ml_score) + "20" : "var(--bg-primary)",
                  fontFamily: "var(--font-mono)",
                }}
              >
                {stock.ml_score.toFixed(0)}
              </span>
            )}
          </div>

          {/* Breakout probability */}
          {stock.breakout && stock.breakout.score >= 20 && (
            <div className="flex items-baseline gap-2 text-[11px]">
              <span style={{ color: "var(--text-muted)" }}>Breakout 60d:</span>
              <span
                className="font-bold tabular-nums"
                style={{
                  color: stock.breakout.score >= 60 ? "var(--green)" : stock.breakout.score >= 40 ? "var(--amber)" : "var(--text-secondary)",
                  fontFamily: "var(--font-mono)",
                }}
              >
                {stock.breakout.score.toFixed(0)}% prob
              </span>
              {stock.breakout.expected_return_pct > 0 && (
                <span style={{ color: "var(--green)" }}>
                  +{stock.breakout.expected_return_pct}% exp
                </span>
              )}
              <span className="text-[10px]" style={{ color: "var(--text-muted)" }}>
                ({stock.breakout.confidence} conf)
              </span>
            </div>
          )}

          {/* Pattern match */}
          {stock.pattern_match && stock.pattern_match.best_match && stock.pattern_match.score >= 50 && (
            <div className="text-[11px]">
              <div className="flex items-center gap-1.5 mb-1">
                <span style={{ color: "var(--text-muted)" }}>Looks like:</span>
                <div className="flex items-center gap-1">
                  <span className="font-bold" style={{ color: "var(--text-primary)" }}>
                    {stock.pattern_match.best_match}
                  </span>
                  <span style={{ color: "var(--green)" }}>
                    +{stock.pattern_match.matches[0]?.move_pct}%
                  </span>
                  <span className="text-[10px]" style={{ color: "var(--text-muted)" }}>
                    in {stock.pattern_match.matches[0]?.move_days}d
                  </span>
                </div>
                <span className="text-[10px]" style={{ color: "var(--accent)" }}>
                  {stock.pattern_match.score.toFixed(0)}% match
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
              <span style={{ color: "var(--text-muted)" }}>Catch-up:</span>
              <span className="font-bold tabular-nums" style={{ color: "var(--amber)", fontFamily: "var(--font-mono)" }}>
                {stock.sector_momentum.score.toFixed(0)}%
              </span>
              {stock.sector_momentum.expected_catch_up_pct > 0 && (
                <span style={{ color: "var(--green)" }}>
                  +{stock.sector_momentum.expected_catch_up_pct}% exp
                </span>
              )}
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
