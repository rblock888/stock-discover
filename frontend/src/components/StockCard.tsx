"use client";

import { StockResult } from "@/lib/api";
import { ScoreBar } from "./ScoreBar";
import { useState } from "react";

const BUCKET_LABELS: Record<string, string> = {
  fundamentals: "Fundamentals",
  momentum: "Momentum",
  catalyst: "Catalyst",
  insider: "Insider",
  sentiment: "Sentiment",
};

export function StockCard({ stock }: { stock: StockResult }) {
  const [expanded, setExpanded] = useState(false);

  const alertBorder = stock.multi_signal_alert
    ? "border-l-2"
    : "border-l-2 border-l-transparent";
  const alertColor = stock.multi_signal_alert
    ? "var(--amber)"
    : "transparent";

  return (
    <div
      className={`rounded-lg cursor-pointer transition-colors duration-150 ${alertBorder}`}
      style={{
        backgroundColor: "var(--bg-surface)",
        borderColor: "var(--border)",
        borderWidth: "1px",
        borderLeftColor: alertColor,
        borderLeftWidth: stock.multi_signal_alert ? "3px" : "1px",
      }}
      onClick={() => setExpanded(!expanded)}
    >
      {/* Header */}
      <div className="px-4 py-3 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-base font-semibold tracking-tight">
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
              Multi-Signal
            </span>
          )}
          <span
            className="text-[11px] tracking-wide"
            style={{ color: "var(--text-secondary)" }}
          >
            {stock.signals_above_60}/5 signals
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span
            className="text-2xl font-bold tabular-nums tracking-tight"
            style={{
              color:
                stock.composite >= 70
                  ? "var(--green)"
                  : stock.composite >= 50
                    ? "var(--text-primary)"
                    : "var(--red)",
            }}
          >
            {stock.composite.toFixed(1)}
          </span>
          <span
            className="text-xs"
            style={{ color: "var(--text-muted)" }}
          >
            /100
          </span>
        </div>
      </div>

      {/* Score bars */}
      <div className="px-4 pb-3 space-y-1.5">
        {Object.entries(stock.breakdown).map(([key, bucket]) => (
          <ScoreBar
            key={key}
            score={bucket.raw}
            label={BUCKET_LABELS[key] || key}
            size="sm"
          />
        ))}
      </div>

      {/* Expanded details */}
      {expanded && (
        <div
          className="px-4 pb-4 pt-2 space-y-3"
          style={{ borderTop: "1px solid var(--border)" }}
        >
          {Object.entries(stock.breakdown).map(([key, bucket]) => (
            <div key={key}>
              <div className="flex items-center justify-between mb-1">
                <span
                  className="text-xs font-medium"
                  style={{ color: "var(--text-secondary)" }}
                >
                  {BUCKET_LABELS[key]}
                </span>
                <span className="text-xs font-mono tabular-nums">
                  {bucket.raw.toFixed(1)} × {(bucket.weight * 100).toFixed(0)}%
                  ={" "}
                  <span style={{ color: "var(--text-primary)" }}>
                    {bucket.weighted.toFixed(1)}
                  </span>
                </span>
              </div>
              <div className="flex flex-wrap gap-1.5">
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
