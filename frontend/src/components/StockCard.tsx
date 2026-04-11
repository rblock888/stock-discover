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

const BUCKET_ICONS: Record<string, string> = {
  fundamentals: "📊",
  momentum: "📈",
  catalyst: "⚡",
  insider: "👤",
  sentiment: "💬",
};

function extractPros(breakdown: Record<string, BucketScore>): string[] {
  const pros: string[] = [];
  const b = breakdown;

  if (b.fundamentals.raw >= 70) {
    const c = b.fundamentals.components;
    if (c.revenue_growth) pros.push(`Revenue growth ${c.revenue_growth}`);
    if (c.gross_margin) pros.push(`Gross margin ${c.gross_margin}`);
    if (c.cash && String(c.cash).includes("positive"))
      pros.push("Cash flow positive");
  }
  if (b.momentum.raw >= 60) {
    const c = b.momentum.components;
    if (c.rel_strength) pros.push(`Outperforming SPY: ${c.rel_strength}`);
    if (c.breakout && String(c.breakout).includes("golden"))
      pros.push("Golden cross pattern");
    else if (c.breakout && String(c.breakout).includes("Above 20/50"))
      pros.push("Above key moving averages");
    if (c.volume && parseFloat(String(c.volume)) > 1.5)
      pros.push(`Volume expanding: ${c.volume}`);
  }
  if (b.catalyst.raw >= 60) {
    const c = b.catalyst.components;
    if (c.earnings) pros.push(`Earnings ${String(c.earnings).toLowerCase()}`);
    if (c.target_upside && !String(c.target_upside).includes("-"))
      pros.push(`Analyst upside: ${c.target_upside}`);
    if (c.recommendation)
      pros.push(`Analyst rating: ${c.recommendation}`);
  }
  if (b.insider.raw >= 60) {
    const c = b.insider.components;
    if (c.insider_txns && String(c.insider_txns).includes("buying"))
      pros.push(`${c.insider_txns}`);
    if (c.insider_own) pros.push(`Insider ownership: ${c.insider_own}`);
  }
  if (b.sentiment.raw >= 60) {
    const c = b.sentiment.components;
    if (c.mentions) pros.push(`${c.mentions} Reddit mentions`);
    if (c.subreddits && Number(c.subreddits) >= 3)
      pros.push(`Discussed in ${c.subreddits} subreddits`);
  }

  return pros.slice(0, 5);
}

function extractCons(breakdown: Record<string, BucketScore>): string[] {
  const cons: string[] = [];
  const b = breakdown;

  if (b.fundamentals.raw < 40) {
    const c = b.fundamentals.components;
    if (c.dilution && String(c.dilution).includes("heavy"))
      cons.push(`Heavy dilution: ${c.dilution}`);
    else if (c.dilution) cons.push(`Dilution: ${c.dilution}`);
    if (c.debt && parseFloat(String(c.debt).replace(/[^0-9.]/g, "")) > 30)
      cons.push(`High debt: ${c.debt}`);
  }
  if (b.momentum.raw < 40) {
    const c = b.momentum.components;
    if (c.breakout && String(c.breakout).includes("Below"))
      cons.push("Below key moving averages");
    if (c.rel_strength && String(c.rel_strength).startsWith("-"))
      cons.push(`Underperforming SPY: ${c.rel_strength}`);
  }
  if (b.catalyst.raw < 40) {
    cons.push("No near-term catalysts identified");
  }
  if (b.insider.raw < 40) {
    const c = b.insider.components;
    if (c.insider_txns && String(c.insider_txns).includes("selling"))
      cons.push(`${c.insider_txns}`);
    if (c.dilution_risk && String(c.dilution_risk).includes("heavy"))
      cons.push(`Dilution risk: ${c.dilution_risk}`);
  }
  if (b.sentiment.raw < 40) {
    cons.push("Low social attention");
  }

  return cons.slice(0, 4);
}

function MiniChart({ score, size = 80 }: { score: number; size?: number }) {
  // Radial score chart
  const radius = (size - 8) / 2;
  const circumference = 2 * Math.PI * radius;
  const progress = (score / 100) * circumference;
  const color =
    score >= 75
      ? "var(--green)"
      : score >= 60
        ? "#4ade80"
        : score >= 40
          ? "var(--amber)"
          : "var(--red)";

  return (
    <svg width={size} height={size} className="shrink-0">
      <circle
        cx={size / 2}
        cy={size / 2}
        r={radius}
        fill="none"
        stroke="var(--border)"
        strokeWidth="4"
      />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={radius}
        fill="none"
        stroke={color}
        strokeWidth="4"
        strokeLinecap="round"
        strokeDasharray={`${progress} ${circumference}`}
        transform={`rotate(-90 ${size / 2} ${size / 2})`}
        className="transition-all duration-700"
      />
      <text
        x={size / 2}
        y={size / 2 - 4}
        textAnchor="middle"
        fill={color}
        fontSize="18"
        fontWeight="700"
        fontFamily="var(--font-mono), monospace"
      >
        {score.toFixed(0)}
      </text>
      <text
        x={size / 2}
        y={size / 2 + 12}
        textAnchor="middle"
        fill="var(--text-muted)"
        fontSize="9"
      >
        /100
      </text>
    </svg>
  );
}

function BucketRadial({
  label,
  icon,
  score,
}: {
  label: string;
  icon: string;
  score: number;
}) {
  const color =
    score >= 75
      ? "var(--green)"
      : score >= 60
        ? "#4ade80"
        : score >= 40
          ? "var(--amber)"
          : "var(--red)";
  const radius = 18;
  const circumference = 2 * Math.PI * radius;
  const progress = (score / 100) * circumference;

  return (
    <div className="flex flex-col items-center gap-1">
      <svg width="44" height="44">
        <circle
          cx="22"
          cy="22"
          r={radius}
          fill="none"
          stroke="var(--border)"
          strokeWidth="3"
        />
        <circle
          cx="22"
          cy="22"
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth="3"
          strokeLinecap="round"
          strokeDasharray={`${progress} ${circumference}`}
          transform="rotate(-90 22 22)"
        />
        <text x="22" y="26" textAnchor="middle" fontSize="12" fontWeight="700" fill={color}>
          {score.toFixed(0)}
        </text>
      </svg>
      <span className="text-[10px]" style={{ color: "var(--text-muted)" }}>
        {icon} {label}
      </span>
    </div>
  );
}

export function StockCard({ stock }: { stock: StockResult }) {
  const [expanded, setExpanded] = useState(false);

  const pros = extractPros(stock.breakdown);
  const cons = extractCons(stock.breakdown);

  return (
    <div
      className="rounded-lg transition-colors duration-150"
      style={{
        backgroundColor: "var(--bg-surface)",
        borderWidth: "1px",
        borderColor: stock.multi_signal_alert
          ? "var(--amber)"
          : "var(--border)",
        borderStyle: "solid",
      }}
    >
      {/* Header with chart */}
      <div className="px-4 pt-4 pb-3 flex gap-4">
        <div className="flex flex-col items-center gap-1">
          <MiniChart score={stock.composite} />
          {stock.early_detection && stock.early_detection.score >= 60 && (
            <span
              className="text-[9px] font-bold uppercase tracking-[0.1em] px-1.5 py-0.5 rounded"
              style={{
                backgroundColor: "rgba(34, 197, 94, 0.15)",
                color: "#22c55e",
              }}
            >
              Early {stock.early_detection.score.toFixed(0)}
            </span>
          )}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-lg font-bold tracking-tight">
              {stock.ticker}
            </span>
            {stock.multi_signal_alert && (
              <span
                className="text-[10px] font-semibold uppercase tracking-[0.08em] px-1.5 py-0.5 rounded"
                style={{
                  backgroundColor: "var(--amber-dim)",
                  color: "var(--amber)",
                }}
              >
                Alert
              </span>
            )}
            <span
              className="text-[11px] ml-auto"
              style={{ color: "var(--text-muted)" }}
            >
              {stock.signals_above_60}/5 signals
            </span>
          </div>

          {/* Bucket radials */}
          <div className="flex gap-2 mt-2">
            {Object.entries(stock.breakdown).map(([key, bucket]) => (
              <BucketRadial
                key={key}
                label={BUCKET_LABELS[key] || key}
                icon={BUCKET_ICONS[key] || ""}
                score={bucket.raw}
              />
            ))}
          </div>
        </div>
      </div>

      {/* Early Detection Banner */}
      {stock.early_detection && stock.early_detection.score >= 50 && (
        <div
          className="px-4 py-2 flex flex-wrap gap-1.5"
          style={{ borderTop: "1px solid var(--border)", backgroundColor: "rgba(34, 197, 94, 0.04)" }}
        >
          <span className="text-[10px] font-semibold uppercase tracking-[0.08em] mr-1" style={{ color: "#22c55e" }}>
            Potential
          </span>
          {Object.entries(stock.early_detection.components).map(([k, v]) => (
            <span
              key={k}
              className="text-[10px] px-1.5 py-0.5 rounded"
              style={{ backgroundColor: "rgba(34, 197, 94, 0.1)", color: "var(--text-secondary)" }}
            >
              {String(v)}
            </span>
          ))}
        </div>
      )}

      {/* Pros and Cons */}
      <div
        className="px-4 py-3 grid grid-cols-2 gap-3"
        style={{ borderTop: "1px solid var(--border)" }}
      >
        <div>
          <p
            className="text-[10px] uppercase tracking-[0.08em] font-semibold mb-1.5"
            style={{ color: "var(--green)" }}
          >
            Bullish
          </p>
          {pros.length > 0 ? (
            <ul className="space-y-1">
              {pros.map((pro, i) => (
                <li
                  key={i}
                  className="text-[11px] flex items-start gap-1.5"
                  style={{ color: "var(--text-secondary)" }}
                >
                  <span style={{ color: "var(--green)" }}>+</span>
                  {pro}
                </li>
              ))}
            </ul>
          ) : (
            <p
              className="text-[11px]"
              style={{ color: "var(--text-muted)" }}
            >
              No strong bullish signals
            </p>
          )}
        </div>
        <div>
          <p
            className="text-[10px] uppercase tracking-[0.08em] font-semibold mb-1.5"
            style={{ color: "var(--red)" }}
          >
            Bearish
          </p>
          {cons.length > 0 ? (
            <ul className="space-y-1">
              {cons.map((con, i) => (
                <li
                  key={i}
                  className="text-[11px] flex items-start gap-1.5"
                  style={{ color: "var(--text-secondary)" }}
                >
                  <span style={{ color: "var(--red)" }}>-</span>
                  {con}
                </li>
              ))}
            </ul>
          ) : (
            <p
              className="text-[11px]"
              style={{ color: "var(--text-muted)" }}
            >
              No major red flags
            </p>
          )}
        </div>
      </div>

      {/* Expand for details */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full px-4 py-2 text-[11px] text-center transition-colors"
        style={{
          color: "var(--text-muted)",
          borderTop: "1px solid var(--border)",
          backgroundColor: expanded ? "var(--bg-surface-hover)" : "transparent",
        }}
      >
        {expanded ? "Hide details ▲" : "Show details ▼"}
      </button>

      {/* Expanded details */}
      {expanded && (
        <div
          className="px-4 pb-4 pt-2 space-y-3"
          style={{ borderTop: "1px solid var(--border)" }}
        >
          {Object.entries(stock.breakdown).map(([key, bucket]) => (
            <div key={key}>
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs font-medium" style={{ color: "var(--text-secondary)" }}>
                  {BUCKET_ICONS[key]} {BUCKET_LABELS[key]}
                </span>
                <span className="text-xs font-mono tabular-nums">
                  {bucket.raw.toFixed(1)} × {(bucket.weight * 100).toFixed(0)}%
                  ={" "}
                  <span style={{ color: "var(--text-primary)" }}>
                    {bucket.weighted.toFixed(1)}
                  </span>
                </span>
              </div>
              <ScoreBar score={bucket.raw} size="sm" />
              <div className="flex flex-wrap gap-1.5 mt-1.5">
                {Object.entries(bucket.components).map(([ck, cv]) => (
                  <span
                    key={ck}
                    className="text-[11px] px-2 py-0.5 rounded"
                    style={{
                      backgroundColor: "var(--bg-primary)",
                      color: "var(--text-secondary)",
                      border: "1px solid var(--border)",
                    }}
                  >
                    <span style={{ color: "var(--text-muted)" }}>{ck}:</span>{" "}
                    {String(cv)}
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
