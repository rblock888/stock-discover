"use client";

import { useEffect, useState, useCallback } from "react";
import { getWatchlist, removeFromWatchlist, WatchlistItem } from "@/lib/api";
import { TickerLogo } from "./TickerLogo";

export function WatchlistPanel() {
  const [items, setItems] = useState<WatchlistItem[]>([]);
  const [loading, setLoading] = useState(true);

  const fetch = useCallback(async () => {
    try {
      const r = await getWatchlist();
      setItems(r.items);
    } catch {
      // ignore
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    fetch();
    const i = setInterval(fetch, 60_000);
    return () => clearInterval(i);
  }, [fetch]);

  async function handleRemove(ticker: string) {
    await removeFromWatchlist(ticker);
    setItems((prev) => prev.filter((it) => it.ticker !== ticker));
  }

  if (loading) return null;

  if (items.length === 0) {
    return (
      <div
        className="rounded-lg p-4 text-[12px]"
        style={{ backgroundColor: "var(--bg-surface)", border: "1px solid var(--border)", color: "var(--text-muted)" }}
      >
        Your watchlist is empty. Click + on any stock to track it.
      </div>
    );
  }

  const totalPnl = items.reduce((sum, it) => sum + (it.pnl_dollars || 0), 0);
  const avgPnl = items.length > 0
    ? items.filter((it) => it.entry_price).reduce((sum, it) => sum + it.pnl_pct, 0) / items.filter((it) => it.entry_price).length
    : 0;

  return (
    <div className="rounded-lg overflow-hidden" style={{ border: "1px solid var(--border)" }}>
      <div className="px-4 py-2.5 flex items-center justify-between" style={{ backgroundColor: "var(--bg-surface)", borderBottom: "1px solid var(--border)" }}>
        <div className="flex items-center gap-3">
          <span className="text-[12px] font-semibold">Watchlist</span>
          <span className="text-[10px] tabular-nums" style={{ color: "var(--text-muted)" }}>{items.length} stocks</span>
        </div>
        {items.some((it) => it.entry_price) && (
          <div className="flex items-center gap-3 text-[11px]">
            <span style={{ color: "var(--text-muted)" }}>Avg P&L:</span>
            <span
              className="font-bold tabular-nums"
              style={{ color: avgPnl >= 0 ? "var(--green)" : "var(--red)", fontFamily: "var(--font-mono)" }}
            >
              {avgPnl >= 0 ? "+" : ""}{avgPnl.toFixed(1)}%
            </span>
            {totalPnl !== 0 && (
              <span
                className="font-bold tabular-nums"
                style={{ color: totalPnl >= 0 ? "var(--green)" : "var(--red)", fontFamily: "var(--font-mono)" }}
              >
                ${totalPnl >= 0 ? "+" : ""}{totalPnl.toFixed(0)}
              </span>
            )}
          </div>
        )}
      </div>
      <table className="w-full" style={{ fontSize: "12px" }}>
        <thead>
          <tr style={{ backgroundColor: "var(--bg-surface)", borderBottom: "1px solid var(--border)" }}>
            <th className="px-3 py-1.5 text-left text-[10px] uppercase tracking-[0.08em] font-medium" style={{ color: "var(--text-muted)" }}>Ticker</th>
            <th className="px-3 py-1.5 text-right text-[10px] uppercase tracking-[0.08em] font-medium" style={{ color: "var(--text-muted)" }}>Now</th>
            <th className="px-3 py-1.5 text-right text-[10px] uppercase tracking-[0.08em] font-medium" style={{ color: "var(--text-muted)" }}>Entry</th>
            <th className="px-3 py-1.5 text-right text-[10px] uppercase tracking-[0.08em] font-medium" style={{ color: "var(--text-muted)" }}>P&L%</th>
            <th className="px-3 py-1.5 text-right text-[10px] uppercase tracking-[0.08em] font-medium" style={{ color: "var(--text-muted)" }}>Score</th>
            <th className="w-8"></th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.ticker} style={{ borderBottom: "1px solid var(--border-subtle)" }}>
              <td className="px-3 py-2">
                <div className="flex items-center gap-2">
                  <TickerLogo ticker={item.ticker} size={18} />
                  <span className="font-semibold text-[12px]">{item.ticker}</span>
                </div>
              </td>
              <td className="px-3 py-2 text-right tabular-nums text-[11px]" style={{ fontFamily: "var(--font-mono)" }}>
                ${item.current_price ? item.current_price.toFixed(2) : "—"}
              </td>
              <td className="px-3 py-2 text-right tabular-nums text-[11px]" style={{ fontFamily: "var(--font-mono)", color: "var(--text-muted)" }}>
                {item.entry_price ? `$${item.entry_price.toFixed(2)}` : "—"}
              </td>
              <td className="px-3 py-2 text-right tabular-nums text-[11px] font-bold" style={{ fontFamily: "var(--font-mono)", color: item.pnl_pct >= 0 ? "var(--green)" : "var(--red)" }}>
                {item.entry_price ? `${item.pnl_pct >= 0 ? "+" : ""}${item.pnl_pct.toFixed(1)}%` : "—"}
              </td>
              <td className="px-3 py-2 text-right tabular-nums text-[11px]" style={{ fontFamily: "var(--font-mono)", color: "var(--text-secondary)" }}>
                {item.composite ? item.composite.toFixed(0) : "—"}
              </td>
              <td className="pr-2">
                <button
                  onClick={() => handleRemove(item.ticker)}
                  className="w-5 h-5 text-[10px] rounded hover:bg-red-900/20"
                  style={{ color: "var(--text-muted)" }}
                  title="Remove"
                >
                  ✕
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
