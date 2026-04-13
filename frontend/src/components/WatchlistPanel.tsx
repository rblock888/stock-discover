"use client";

import { useEffect, useState, useCallback } from "react";
import { addToWatchlist, getWatchlist, removeFromWatchlist, WatchlistItem } from "@/lib/api";
import { TickerLogo } from "./TickerLogo";

export function WatchlistPanel() {
  const [items, setItems] = useState<WatchlistItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [addTicker, setAddTicker] = useState("");
  const [addShares, setAddShares] = useState("");
  const [addEntry, setAddEntry] = useState("");
  const [adding, setAdding] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);

  const fetch = useCallback(async () => {
    try {
      const r = await getWatchlist();
      setItems(r.items);
    } catch {
      // ignore
    }
    setLoading(false);
  }, []);

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    const ticker = addTicker.trim().toUpperCase();
    const shares = parseFloat(addShares);
    const entry = addEntry.trim() === "" ? undefined : parseFloat(addEntry);
    if (!ticker || !/^[A-Z.-]+$/.test(ticker)) {
      setAddError("Enter a valid ticker");
      return;
    }
    if (!shares || shares <= 0) {
      setAddError("Enter a share count > 0");
      return;
    }
    if (entry !== undefined && (isNaN(entry) || entry <= 0)) {
      setAddError("Entry price must be > 0");
      return;
    }
    setAdding(true);
    setAddError(null);
    try {
      await addToWatchlist({ ticker, shares, entry_price: entry });
      setAddTicker("");
      setAddShares("");
      setAddEntry("");
      setShowAdd(false);
      await fetch();
    } catch {
      setAddError("Failed to add — check ticker and try again");
    } finally {
      setAdding(false);
    }
  }

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

  const addForm = showAdd ? (
    <form
      onSubmit={handleAdd}
      className="px-4 py-3 flex flex-wrap items-end gap-2"
      style={{ backgroundColor: "var(--bg-elevated)", borderBottom: "1px solid var(--border)" }}
    >
      <div className="flex flex-col">
        <label className="text-[9px] uppercase tracking-[0.08em]" style={{ color: "var(--text-muted)" }}>Ticker</label>
        <input
          autoFocus
          value={addTicker}
          onChange={(e) => setAddTicker(e.target.value.toUpperCase())}
          placeholder="AAPL"
          className="w-20 px-2 py-1 text-[12px] rounded tabular-nums uppercase"
          style={{ backgroundColor: "var(--bg-surface)", border: "1px solid var(--border)", color: "var(--text)", fontFamily: "var(--font-mono)" }}
        />
      </div>
      <div className="flex flex-col">
        <label className="text-[9px] uppercase tracking-[0.08em]" style={{ color: "var(--text-muted)" }}>Shares</label>
        <input
          value={addShares}
          onChange={(e) => setAddShares(e.target.value)}
          placeholder="10"
          inputMode="decimal"
          className="w-20 px-2 py-1 text-[12px] rounded tabular-nums"
          style={{ backgroundColor: "var(--bg-surface)", border: "1px solid var(--border)", color: "var(--text)", fontFamily: "var(--font-mono)" }}
        />
      </div>
      <div className="flex flex-col">
        <label className="text-[9px] uppercase tracking-[0.08em]" style={{ color: "var(--text-muted)" }}>Entry $ (optional)</label>
        <input
          value={addEntry}
          onChange={(e) => setAddEntry(e.target.value)}
          placeholder="market"
          inputMode="decimal"
          className="w-24 px-2 py-1 text-[12px] rounded tabular-nums"
          style={{ backgroundColor: "var(--bg-surface)", border: "1px solid var(--border)", color: "var(--text)", fontFamily: "var(--font-mono)" }}
        />
      </div>
      <button
        type="submit"
        disabled={adding}
        className="px-3 py-1 text-[11px] rounded font-semibold disabled:opacity-50"
        style={{ backgroundColor: "var(--accent)", color: "#fff" }}
      >
        {adding ? "Adding..." : "Add"}
      </button>
      <button
        type="button"
        onClick={() => { setShowAdd(false); setAddError(null); }}
        className="px-2 py-1 text-[11px] rounded"
        style={{ color: "var(--text-muted)" }}
      >
        Cancel
      </button>
      {addError && (
        <span className="text-[10px] w-full" style={{ color: "var(--red)" }}>{addError}</span>
      )}
    </form>
  ) : null;

  if (items.length === 0) {
    return (
      <div className="rounded-lg overflow-hidden" style={{ border: "1px solid var(--border)" }}>
        <div
          className="px-4 py-2.5 flex items-center justify-between"
          style={{ backgroundColor: "var(--bg-surface)", borderBottom: "1px solid var(--border)" }}
        >
          <span className="text-[12px] font-semibold">Watchlist</span>
          <button
            onClick={() => setShowAdd((v) => !v)}
            className="text-[11px] px-2 py-0.5 rounded font-semibold"
            style={{ backgroundColor: "var(--accent)", color: "#fff" }}
          >
            {showAdd ? "×" : "+ Add"}
          </button>
        </div>
        {addForm}
        {!showAdd && (
          <div className="p-4 text-[12px]" style={{ backgroundColor: "var(--bg-surface)", color: "var(--text-muted)" }}>
            Your watchlist is empty. Click <span style={{ color: "var(--accent)" }}>+ Add</span> to track a stock you own.
          </div>
        )}
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
        <div className="flex items-center gap-3">
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
          <button
            onClick={() => setShowAdd((v) => !v)}
            className="text-[11px] px-2 py-0.5 rounded font-semibold"
            style={{ backgroundColor: "var(--accent)", color: "#fff" }}
          >
            {showAdd ? "×" : "+ Add"}
          </button>
        </div>
      </div>
      {addForm}
      <table className="w-full" style={{ fontSize: "12px" }}>
        <thead>
          <tr style={{ backgroundColor: "var(--bg-surface)", borderBottom: "1px solid var(--border)" }}>
            <th className="px-3 py-1.5 text-left text-[10px] uppercase tracking-[0.08em] font-medium" style={{ color: "var(--text-muted)" }}>Ticker</th>
            <th className="px-3 py-1.5 text-right text-[10px] uppercase tracking-[0.08em] font-medium" style={{ color: "var(--text-muted)" }}>Shares</th>
            <th className="px-3 py-1.5 text-right text-[10px] uppercase tracking-[0.08em] font-medium" style={{ color: "var(--text-muted)" }}>Now</th>
            <th className="px-3 py-1.5 text-right text-[10px] uppercase tracking-[0.08em] font-medium" style={{ color: "var(--text-muted)" }}>Entry</th>
            <th className="px-3 py-1.5 text-right text-[10px] uppercase tracking-[0.08em] font-medium" style={{ color: "var(--text-muted)" }}>Value</th>
            <th className="px-3 py-1.5 text-right text-[10px] uppercase tracking-[0.08em] font-medium" style={{ color: "var(--text-muted)" }}>P&L</th>
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
              <td className="px-3 py-2 text-right tabular-nums text-[11px]" style={{ fontFamily: "var(--font-mono)", color: "var(--text-muted)" }}>
                {item.shares ? item.shares.toLocaleString(undefined, { maximumFractionDigits: 4 }) : "—"}
              </td>
              <td className="px-3 py-2 text-right tabular-nums text-[11px]" style={{ fontFamily: "var(--font-mono)" }}>
                ${item.current_price ? item.current_price.toFixed(2) : "—"}
              </td>
              <td className="px-3 py-2 text-right tabular-nums text-[11px]" style={{ fontFamily: "var(--font-mono)", color: "var(--text-muted)" }}>
                {item.entry_price ? `$${item.entry_price.toFixed(2)}` : "—"}
              </td>
              <td className="px-3 py-2 text-right tabular-nums text-[11px]" style={{ fontFamily: "var(--font-mono)" }}>
                {item.shares && item.current_price ? `$${(item.shares * item.current_price).toFixed(2)}` : "—"}
              </td>
              <td className="px-3 py-2 text-right tabular-nums text-[11px] font-bold" style={{ fontFamily: "var(--font-mono)", color: item.pnl_pct >= 0 ? "var(--green)" : "var(--red)" }}>
                {item.entry_price ? (
                  <>
                    <div>{item.pnl_pct >= 0 ? "+" : ""}{item.pnl_pct.toFixed(1)}%</div>
                    {item.shares ? (
                      <div className="text-[10px] font-normal" style={{ color: item.pnl_dollars >= 0 ? "var(--green)" : "var(--red)" }}>
                        {item.pnl_dollars >= 0 ? "+" : ""}${item.pnl_dollars.toFixed(2)}
                      </div>
                    ) : null}
                  </>
                ) : "—"}
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
