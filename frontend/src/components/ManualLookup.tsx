"use client";

import { useState } from "react";
import { StockResult } from "@/lib/api";
import { StockCard } from "./StockCard";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export function ManualLookup() {
  const [ticker, setTicker] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<StockResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function lookup(e?: React.FormEvent) {
    e?.preventDefault();
    const t = ticker.trim().toUpperCase();
    if (!t) return;

    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await fetch(`${API_BASE}/api/score/${t}`);
      if (!res.ok) throw new Error(`Failed to load ${t}`);
      const data = await res.json();
      setResult(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    }
    setLoading(false);
  }

  return (
    <div>
      <div className="flex items-baseline gap-3 mb-3">
        <span className="w-[3px] h-5 rounded-full" style={{ backgroundColor: "var(--accent-bright)" }} />
        <h2 className="text-[16px] font-semibold tracking-tight" style={{ letterSpacing: "-0.02em" }}>
          Lookup Any Ticker
        </h2>
        <span className="text-[11px]" style={{ color: "var(--text-muted)" }}>
          Run the full scoring + ML analysis on any stock
        </span>
      </div>

      <form onSubmit={lookup} className="flex gap-2 mb-3">
        <input
          value={ticker}
          onChange={(e) => setTicker(e.target.value.toUpperCase())}
          placeholder="e.g. LWLG, TSLA, PLTR"
          maxLength={6}
          className="flex-1 max-w-[200px] px-3 py-2 rounded text-[13px] focus:outline-none"
          style={{
            backgroundColor: "var(--bg-surface)",
            border: "1px solid var(--border)",
            color: "var(--text-primary)",
            fontFamily: "var(--font-mono)",
            letterSpacing: "0.04em",
          }}
          disabled={loading}
        />
        <button
          type="submit"
          disabled={loading || !ticker.trim()}
          className="px-4 py-2 rounded text-[12px] font-semibold transition-all active:scale-[0.98]"
          style={{
            backgroundColor: loading ? "var(--bg-elevated)" : "var(--accent)",
            color: loading ? "var(--text-muted)" : "#fff",
          }}
        >
          {loading ? "Analyzing…" : "Analyze"}
        </button>
      </form>

      {error && (
        <div
          className="rounded px-3 py-2 text-[12px] mb-3"
          style={{ backgroundColor: "var(--red-dim)", color: "var(--red)", border: "1px solid var(--red)" }}
        >
          {error}
        </div>
      )}

      {result && (
        <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-3">
          <StockCard stock={result} />
        </div>
      )}
    </div>
  );
}
