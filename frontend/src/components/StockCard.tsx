"use client";

import { StockResult, BucketScore } from "@/lib/api";
import { ScoreBar } from "./ScoreBar";
import { useState } from "react";

const BUCKET_LABELS: Record<string, string> = {
  fundamentals: "Fundamentals",
  momentum: "Momentum",
  catalyst: "Catalyst",
  insider: "Insider",
  sentiment: "Sentiment",
};

function extractPros(bd: Record<string, BucketScore>): string[] {
  const pros: string[] = [];
  if (bd.fundamentals.raw >= 70) {
    const c = bd.fundamentals.components;
    if (c.revenue_growth) pros.push(`Rev growth ${c.revenue_growth}`);
    if (c.gross_margin) pros.push(`GM ${c.gross_margin}`);
    if (c.cash && String(c.cash).includes("positive")) pros.push("CF positive");
  }
  if (bd.momentum.raw >= 60) {
    const c = bd.momentum.components;
    if (c.breakout && String(c.breakout).includes("golden")) pros.push("Golden cross");
    else if (c.breakout && String(c.breakout).includes("Above 20/50")) pros.push("Above key MAs");
    if (c.volume && parseFloat(String(c.volume)) > 1.5) pros.push(`Vol ${c.volume}`);
    if (c.rel_strength || c.return) pros.push(String(c.rel_strength || c.return));
  }
  if (bd.catalyst.raw >= 60) {
    const c = bd.catalyst.components;
    if (c.earnings) pros.push(`Earnings ${String(c.earnings).toLowerCase()}`);
    if (c.target_upside && !String(c.target_upside).includes("-")) pros.push(`Target ${c.target_upside}`);
  }
  if (bd.insider.raw >= 60) {
    const c = bd.insider.components;
    if (c.insider_txns && String(c.insider_txns).includes("buying")) pros.push(String(c.insider_txns));
  }
  if (bd.sentiment.raw >= 60) {
    const c = bd.sentiment.components;
    if (c.mentions) pros.push(`${c.mentions} mentions`);
  }
  return pros.slice(0, 4);
}

function extractCons(bd: Record<string, BucketScore>): string[] {
  const cons: string[] = [];
  if (bd.fundamentals.raw < 40) {
    const c = bd.fundamentals.components;
    if (c.dilution) cons.push(`Dilution ${c.dilution}`);
  }
  if (bd.momentum.raw < 40) {
    const c = bd.momentum.components;
    if (c.breakout && String(c.breakout).includes("Below")) cons.push("Below key MAs");
    if (c.rel_strength && String(c.rel_strength).startsWith("-")) cons.push(String(c.rel_strength));
  }
  if (bd.insider.raw < 40) {
    const c = bd.insider.components;
    if (c.insider_txns && String(c.insider_txns).includes("selling")) cons.push(String(c.insider_txns));
  }
  if (bd.catalyst.raw < 40) cons.push("No near-term catalyst");
  if (bd.sentiment.raw < 35) cons.push("Low social attention");
  return cons.slice(0, 3);
}

function scoreColor(s: number) {
  if (s >= 75) return "var(--green)";
  if (s >= 60) return "var(--green-bright)";
  if (s >= 40) return "var(--amber)";
  return "var(--red)";
}

export function StockCard({ stock }: { stock: StockResult }) {
  const [expanded, setExpanded] = useState(false);
  const pros = extractPros(stock.breakdown);
  const cons = extractCons(stock.breakdown);
  const early = stock.early_detection?.score ?? 0;
  const comp = stock.competitors;

  return (
    <div
      className="rounded overflow-hidden"
      style={{
        backgroundColor: "var(--bg-surface)",
        border: `1px solid ${stock.multi_signal_alert ? "var(--amber)" : "var(--border)"}`,
      }}
    >
      {/* Header row */}
      <div className="flex items-center justify-between px-3 py-2" style={{ borderBottom: "1px solid var(--border)" }}>
        <div className="flex items-center gap-2">
          <span className="text-[14px] font-bold" style={{ letterSpacing: "-0.02em" }}>
            {stock.ticker}
          </span>
          {stock.multi_signal_alert && (
            <span className="text-[8px] font-bold uppercase tracking-[0.1em] px-1 py-[1px] rounded"
              style={{ backgroundColor: "var(--amber-dim)", color: "var(--amber)" }}>
              Alert
            </span>
          )}
          {early >= 65 && (
            <span className="text-[8px] font-bold uppercase tracking-[0.1em] px-1 py-[1px] rounded"
              style={{ backgroundColor: "var(--green-dim)", color: "var(--green)" }}>
              Early {early.toFixed(0)}
            </span>
          )}
          {comp?.position && comp.position !== "unknown" && (
            <span className="text-[9px]" style={{ color: "var(--text-muted)" }}>
              {comp.position} {comp.mcap_rank}
            </span>
          )}
        </div>
        <div className="flex items-center gap-1">
          <span className="text-[18px] font-bold tabular-nums" style={{
            color: scoreColor(stock.composite),
            fontFamily: "var(--font-mono)",
            letterSpacing: "-0.02em",
          }}>
            {stock.composite.toFixed(1)}
          </span>
        </div>
      </div>

      {/* Score bars */}
      <div className="px-3 py-2 space-y-[5px]">
        {Object.entries(stock.breakdown).map(([key, bucket]) => (
          <ScoreBar key={key} score={bucket.raw} label={BUCKET_LABELS[key]} size="sm" />
        ))}
      </div>

      {/* Early detection highlights */}
      {early >= 50 && stock.early_detection?.components && (
        <div className="px-3 py-1.5 flex flex-wrap gap-1" style={{ borderTop: "1px solid var(--border)" }}>
          {Object.entries(stock.early_detection.components).map(([k, v]) => (
            <span key={k} className="text-[9px] px-1 py-[1px] rounded"
              style={{ backgroundColor: "var(--green-dim)", color: "var(--text-secondary)" }}>
              {String(v)}
            </span>
          ))}
        </div>
      )}

      {/* Pros / Cons */}
      <div className="px-3 py-2 grid grid-cols-2 gap-2" style={{ borderTop: "1px solid var(--border)" }}>
        <div>
          {pros.map((p, i) => (
            <div key={i} className="text-[10px] flex items-start gap-1 mb-[2px]" style={{ color: "var(--text-secondary)" }}>
              <span style={{ color: "var(--green)" }}>+</span>{p}
            </div>
          ))}
          {pros.length === 0 && <span className="text-[10px]" style={{ color: "var(--text-muted)" }}>No strong signals</span>}
        </div>
        <div>
          {cons.map((c, i) => (
            <div key={i} className="text-[10px] flex items-start gap-1 mb-[2px]" style={{ color: "var(--text-secondary)" }}>
              <span style={{ color: "var(--red)" }}>-</span>{c}
            </div>
          ))}
          {cons.length === 0 && <span className="text-[10px]" style={{ color: "var(--text-muted)" }}>No red flags</span>}
        </div>
      </div>

      {/* Competitors */}
      {comp?.has_peers && comp.peers.length > 0 && (
        <div className="px-3 py-1.5" style={{ borderTop: "1px solid var(--border)" }}>
          <div className="flex items-center gap-2 mb-1">
            <span className="text-[9px] uppercase tracking-[0.08em]" style={{ color: "var(--text-muted)" }}>
              Peers 3m
            </span>
            {comp.lagging && (
              <span className="text-[9px]" style={{ color: "var(--amber)" }}>
                {comp.gap_3m}% behind
              </span>
            )}
            {comp.biggest_competitor && (
              <span className="text-[9px]" style={{ color: "var(--text-muted)" }}>
                {comp.biggest_competitor.ticker} {comp.biggest_competitor.ratio}x bigger
              </span>
            )}
          </div>
          <div className="flex gap-1">
            {comp.peers.slice(0, 5).map((peer) => (
              <div key={peer.ticker} className="text-center px-1.5 py-[3px] rounded min-w-[48px]"
                style={{ backgroundColor: "var(--bg-primary)", border: "1px solid var(--border)" }}>
                <div className="text-[9px] font-medium">{peer.ticker}</div>
                <div className="text-[10px] font-bold tabular-nums"
                  style={{ color: peer.ret_3m >= 0 ? "var(--green)" : "var(--red)", fontFamily: "var(--font-mono)" }}>
                  {peer.ret_3m >= 0 ? "+" : ""}{peer.ret_3m}%
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Expand toggle */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full h-6 text-[9px] uppercase tracking-[0.08em] transition-colors"
        style={{ color: "var(--text-muted)", borderTop: "1px solid var(--border)",
          backgroundColor: expanded ? "var(--bg-elevated)" : "transparent" }}
      >
        {expanded ? "Hide ▲" : "Details ▼"}
      </button>

      {expanded && (
        <div className="px-3 py-2 space-y-2" style={{ borderTop: "1px solid var(--border)" }}>
          {Object.entries(stock.breakdown).map(([key, bucket]) => (
            <div key={key}>
              <div className="flex justify-between mb-[2px]">
                <span className="text-[10px]" style={{ color: "var(--text-muted)" }}>{BUCKET_LABELS[key]}</span>
                <span className="text-[10px] tabular-nums" style={{ fontFamily: "var(--font-mono)", color: "var(--text-secondary)" }}>
                  {bucket.raw.toFixed(1)} × {(bucket.weight * 100).toFixed(0)}% = {bucket.weighted.toFixed(1)}
                </span>
              </div>
              <div className="flex flex-wrap gap-1">
                {Object.entries(bucket.components).map(([ck, cv]) => (
                  <span key={ck} className="text-[9px] px-1 py-[1px] rounded"
                    style={{ backgroundColor: "var(--bg-primary)", color: "var(--text-secondary)", border: "1px solid var(--border)" }}>
                    <span style={{ color: "var(--text-muted)" }}>{ck}:</span> {String(cv)}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
