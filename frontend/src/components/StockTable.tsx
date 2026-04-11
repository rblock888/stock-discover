"use client";

import { StockResult } from "@/lib/api";
import { useState } from "react";

const BUCKET_KEYS = [
  "fundamentals",
  "momentum",
  "catalyst",
  "insider",
  "sentiment",
] as const;

function scoreColor(score: number): string {
  if (score >= 75) return "var(--green)";
  if (score >= 60) return "#4ade80";
  if (score >= 40) return "var(--amber)";
  return "var(--red)";
}

function scoreBg(score: number): string {
  if (score >= 75) return "var(--green-dim)";
  if (score >= 60) return "rgba(74, 222, 128, 0.12)";
  if (score >= 40) return "var(--amber-dim)";
  return "var(--red-dim)";
}

type SortKey = "composite" | typeof BUCKET_KEYS[number] | "signals";

export function StockTable({
  stocks,
  onSelect,
}: {
  stocks: StockResult[];
  onSelect?: (ticker: string) => void;
}) {
  const [sortKey, setSortKey] = useState<SortKey>("composite");
  const [sortAsc, setSortAsc] = useState(false);

  const sorted = [...stocks].sort((a, b) => {
    let av: number, bv: number;
    if (sortKey === "composite") {
      av = a.composite;
      bv = b.composite;
    } else if (sortKey === "signals") {
      av = a.signals_above_60;
      bv = b.signals_above_60;
    } else {
      av = a.breakdown[sortKey]?.raw ?? 0;
      bv = b.breakdown[sortKey]?.raw ?? 0;
    }
    return sortAsc ? av - bv : bv - av;
  });

  function handleSort(key: SortKey) {
    if (sortKey === key) setSortAsc(!sortAsc);
    else {
      setSortKey(key);
      setSortAsc(false);
    }
  }

  const thClass =
    "px-3 py-2 text-[11px] uppercase tracking-[0.06em] cursor-pointer select-none whitespace-nowrap";
  const arrow = (key: SortKey) =>
    sortKey === key ? (sortAsc ? " ↑" : " ↓") : "";

  return (
    <div className="overflow-x-auto rounded-lg" style={{ border: "1px solid var(--border)" }}>
      <table className="w-full text-sm">
        <thead>
          <tr style={{ backgroundColor: "var(--bg-surface)" }}>
            <th className={`${thClass} text-left`} style={{ color: "var(--text-secondary)" }}>
              Ticker
            </th>
            <th
              className={`${thClass} text-right`}
              style={{ color: "var(--text-secondary)" }}
              onClick={() => handleSort("composite")}
            >
              Score{arrow("composite")}
            </th>
            {BUCKET_KEYS.map((key) => (
              <th
                key={key}
                className={`${thClass} text-right`}
                style={{ color: "var(--text-secondary)" }}
                onClick={() => handleSort(key)}
              >
                {key.slice(0, 4).toUpperCase()}{arrow(key)}
              </th>
            ))}
            <th
              className={`${thClass} text-center`}
              style={{ color: "var(--text-secondary)" }}
              onClick={() => handleSort("signals")}
            >
              Signals{arrow("signals")}
            </th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((stock, i) => (
            <tr
              key={stock.ticker}
              className="cursor-pointer transition-colors duration-100"
              style={{
                backgroundColor:
                  i % 2 === 0 ? "var(--bg-primary)" : "var(--bg-surface)",
                borderBottom: "1px solid var(--border)",
              }}
              onMouseEnter={(e) =>
                (e.currentTarget.style.backgroundColor =
                  "var(--bg-surface-hover)")
              }
              onMouseLeave={(e) =>
                (e.currentTarget.style.backgroundColor =
                  i % 2 === 0 ? "var(--bg-primary)" : "var(--bg-surface)")
              }
              onClick={() => onSelect?.(stock.ticker)}
            >
              <td className="px-3 py-2.5">
                <div className="flex items-center gap-2">
                  <span className="font-semibold text-sm">{stock.ticker}</span>
                  {stock.multi_signal_alert && (
                    <span
                      className="w-1.5 h-1.5 rounded-full animate-pulse"
                      style={{ backgroundColor: "var(--amber)" }}
                    />
                  )}
                </div>
              </td>
              <td className="px-3 py-2.5 text-right">
                <span
                  className="font-bold font-mono tabular-nums text-sm px-2 py-0.5 rounded"
                  style={{
                    color: scoreColor(stock.composite),
                    backgroundColor: scoreBg(stock.composite),
                  }}
                >
                  {stock.composite.toFixed(1)}
                </span>
              </td>
              {BUCKET_KEYS.map((key) => {
                const raw = stock.breakdown[key]?.raw ?? 0;
                return (
                  <td
                    key={key}
                    className="px-3 py-2.5 text-right font-mono tabular-nums text-xs"
                    style={{ color: scoreColor(raw) }}
                  >
                    {raw.toFixed(0)}
                  </td>
                );
              })}
              <td className="px-3 py-2.5 text-center">
                <span
                  className="text-xs font-mono tabular-nums"
                  style={{
                    color:
                      stock.signals_above_60 >= 3
                        ? "var(--amber)"
                        : "var(--text-secondary)",
                  }}
                >
                  {stock.signals_above_60}/5
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
