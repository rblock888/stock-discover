"use client";

import { StockResult } from "@/lib/api";
import { TickerLogo } from "./TickerLogo";
import { useState } from "react";

const BUCKET_KEYS = [
  "fundamentals",
  "momentum",
  "catalyst",
  "insider",
] as const;

const COL_LABELS: Record<string, string> = {
  fundamentals: "FUNDAMENTALS",
  momentum: "MOMENTUM",
  catalyst: "CATALYST",
  insider: "INSIDER",
  sentiment: "SENTIMENT",
};

function scoreColor(score: number): string {
  if (score >= 75) return "var(--green)";
  if (score >= 60) return "var(--green-bright)";
  if (score >= 40) return "var(--amber)";
  return "var(--red)";
}

type SortKey = "composite" | typeof BUCKET_KEYS[number] | "signals" | "early";

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
      av = a.composite; bv = b.composite;
    } else if (sortKey === "signals") {
      av = a.signals_above_60; bv = b.signals_above_60;
    } else if (sortKey === "early") {
      av = a.early_detection?.score ?? 0; bv = b.early_detection?.score ?? 0;
    } else {
      av = a.breakdown[sortKey]?.raw ?? 0; bv = b.breakdown[sortKey]?.raw ?? 0;
    }
    return sortAsc ? av - bv : bv - av;
  });

  function handleSort(key: SortKey) {
    if (sortKey === key) setSortAsc(!sortAsc);
    else { setSortKey(key); setSortAsc(false); }
  }

  const arrow = (key: SortKey) =>
    sortKey === key ? (sortAsc ? " ↑" : " ↓") : "";

  return (
    <div className="overflow-x-auto rounded" style={{ border: "1px solid var(--border)" }}>
      <table className="w-full" style={{ fontSize: "12px" }}>
        <thead>
          <tr style={{ backgroundColor: "var(--bg-surface)", borderBottom: "1px solid var(--border)" }}>
            <Th align="left">Ticker</Th>
            <Th align="right">Price</Th>
            <Th align="right">MCap</Th>
            <Th align="right" onClick={() => handleSort("composite")}>
              Score{arrow("composite")}
            </Th>
            {BUCKET_KEYS.map((key) => (
              <Th key={key} align="right" onClick={() => handleSort(key)} muted>
                {COL_LABELS[key]}{arrow(key)}
              </Th>
            ))}
            <Th align="right" onClick={() => handleSort("early")} accent>
              Early{arrow("early")}
            </Th>
            <Th align="center" onClick={() => handleSort("signals")} muted>
              Sig{arrow("signals")}
            </Th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((stock, i) => (
            <tr
              key={stock.ticker}
              className="cursor-pointer transition-colors duration-75"
              style={{
                borderBottom: "1px solid var(--border-subtle)",
              }}
              onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = "var(--bg-surface-hover)")}
              onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = "transparent")}
              onClick={() => onSelect?.(stock.ticker)}
            >
              <td className="px-3 py-[7px]">
                <div className="flex items-center gap-2">
                  <TickerLogo ticker={stock.ticker} size={20} />
                  <span className="font-semibold text-[12px]" style={{ color: "var(--text-primary)" }}>
                    {stock.ticker}
                  </span>
                  {stock.multi_signal_alert && (
                    <span
                      className="w-[5px] h-[5px] rounded-full"
                      style={{ backgroundColor: "var(--amber)" }}
                    />
                  )}
                </div>
              </td>
              <td className="px-3 py-[7px] text-right tabular-nums text-[11px]" style={{ fontFamily: "var(--font-mono)", color: "var(--text-secondary)" }}>
                {stock.quote?.price ? `$${stock.quote.price < 10 ? stock.quote.price.toFixed(2) : stock.quote.price.toFixed(1)}` : "—"}
              </td>
              <td className="px-3 py-[7px] text-right tabular-nums text-[11px]" style={{ fontFamily: "var(--font-mono)", color: "var(--text-muted)" }}>
                {stock.quote?.market_cap ? (
                  stock.quote.market_cap >= 1e9
                    ? `${(stock.quote.market_cap / 1e9).toFixed(1)}B`
                    : `${(stock.quote.market_cap / 1e6).toFixed(0)}M`
                ) : "—"}
              </td>
              <td className="px-3 py-[7px] text-right">
                <span
                  className="font-bold tabular-nums text-[12px] px-1.5 py-[2px] rounded"
                  style={{
                    color: scoreColor(stock.composite),
                    backgroundColor: stock.composite >= 60
                      ? `${scoreColor(stock.composite)}18`
                      : "transparent",
                    fontFamily: "var(--font-mono)",
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
                    className="px-3 py-[7px] text-right tabular-nums"
                    style={{ color: scoreColor(raw), fontFamily: "var(--font-mono)", fontSize: "11px" }}
                  >
                    {raw.toFixed(0)}
                  </td>
                );
              })}
              <td className="px-3 py-[7px] text-right">
                {(() => {
                  const early = stock.early_detection?.score ?? 0;
                  return (
                    <span
                      className="tabular-nums text-[11px] font-bold"
                      style={{
                        color: early >= 65 ? "var(--green)" : "var(--text-muted)",
                        fontFamily: "var(--font-mono)",
                      }}
                    >
                      {early.toFixed(0)}
                    </span>
                  );
                })()}
              </td>
              <td className="px-3 py-[7px] text-center">
                <span
                  className="tabular-nums text-[11px]"
                  style={{
                    color: stock.signals_above_60 >= 3 ? "var(--amber)" : "var(--text-muted)",
                    fontFamily: "var(--font-mono)",
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

function Th({
  children,
  align = "left",
  onClick,
  muted,
  accent,
}: {
  children: React.ReactNode;
  align?: "left" | "right" | "center";
  onClick?: () => void;
  muted?: boolean;
  accent?: boolean;
}) {
  return (
    <th
      className={`px-3 py-[6px] text-[10px] uppercase tracking-[0.08em] font-medium whitespace-nowrap ${onClick ? "cursor-pointer select-none" : ""}`}
      style={{
        textAlign: align,
        color: accent ? "var(--green)" : muted ? "var(--text-muted)" : "var(--text-secondary)",
      }}
      onClick={onClick}
    >
      {children}
    </th>
  );
}
