"use client";

import { useEffect, useState } from "react";
import { getBacktest, BacktestResult } from "@/lib/api";

export function BacktestPanel() {
  const [data, setData] = useState<BacktestResult | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getBacktest()
      .then((d) => { setData(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  if (loading) return null;
  if (!data || data.total_picks === 0) {
    return (
      <div
        className="rounded-lg p-4 text-[12px]"
        style={{ backgroundColor: "var(--bg-surface)", border: "1px solid var(--border)", color: "var(--text-muted)" }}
      >
        <div className="text-[11px] uppercase tracking-[0.08em] mb-1" style={{ color: "var(--text-secondary)" }}>
          Backtest
        </div>
        Backtest data accumulates with each scan. Check back in 24 hours.
      </div>
    );
  }

  const avgColor = data.avg_return >= 0 ? "var(--green)" : "var(--red)";

  return (
    <div className="rounded-lg overflow-hidden" style={{ border: "1px solid var(--border)" }}>
      <div className="px-4 py-2.5 flex items-center justify-between" style={{ backgroundColor: "var(--bg-surface)", borderBottom: "1px solid var(--border)" }}>
        <span className="text-[12px] font-semibold">Pick Performance</span>
        <span className="text-[10px] tabular-nums" style={{ color: "var(--text-muted)" }}>
          {data.total_picks} historical picks tracked
        </span>
      </div>

      <div className="p-3 grid grid-cols-3 gap-2">
        <div className="rounded p-2.5" style={{ backgroundColor: "var(--bg-primary)", border: "1px solid var(--border)" }}>
          <div className="text-[9px] uppercase tracking-[0.08em]" style={{ color: "var(--text-muted)" }}>Avg Return</div>
          <div className="text-[18px] font-bold tabular-nums leading-tight" style={{ color: avgColor, fontFamily: "var(--font-mono)" }}>
            {data.avg_return >= 0 ? "+" : ""}{data.avg_return}%
          </div>
        </div>
        <div className="rounded p-2.5" style={{ backgroundColor: "var(--bg-primary)", border: "1px solid var(--border)" }}>
          <div className="text-[9px] uppercase tracking-[0.08em]" style={{ color: "var(--text-muted)" }}>Win Rate</div>
          <div className="text-[18px] font-bold tabular-nums leading-tight" style={{ color: data.win_rate >= 50 ? "var(--green)" : "var(--amber)", fontFamily: "var(--font-mono)" }}>
            {data.win_rate}%
          </div>
        </div>
        <div className="rounded p-2.5" style={{ backgroundColor: "var(--bg-primary)", border: "1px solid var(--border)" }}>
          <div className="text-[9px] uppercase tracking-[0.08em]" style={{ color: "var(--text-muted)" }}>Picks</div>
          <div className="text-[18px] font-bold tabular-nums leading-tight" style={{ color: "var(--text-primary)", fontFamily: "var(--font-mono)" }}>
            {data.total_picks}
          </div>
        </div>
      </div>

      {/* By segment */}
      {Object.keys(data.by_segment).length > 0 && (
        <div className="px-3 pb-3 space-y-1">
          {Object.entries(data.by_segment).map(([label, stats]) => (
            <div key={label} className="flex items-center justify-between text-[11px] py-1 px-2 rounded" style={{ backgroundColor: "var(--bg-primary)" }}>
              <span style={{ color: "var(--text-secondary)" }}>{label}</span>
              <div className="flex items-center gap-3">
                <span className="tabular-nums" style={{ color: "var(--text-muted)", fontFamily: "var(--font-mono)" }}>{stats.count}</span>
                <span className="tabular-nums font-bold" style={{ color: stats.avg_return >= 0 ? "var(--green)" : "var(--red)", fontFamily: "var(--font-mono)" }}>
                  {stats.avg_return >= 0 ? "+" : ""}{stats.avg_return}%
                </span>
                <span className="tabular-nums text-[10px]" style={{ color: stats.win_rate >= 50 ? "var(--green)" : "var(--amber)", fontFamily: "var(--font-mono)" }}>
                  {stats.win_rate}% win
                </span>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Best picks */}
      {data.best_picks.length > 0 && (
        <div className="px-3 pb-3">
          <div className="text-[10px] uppercase tracking-[0.08em] mb-1" style={{ color: "var(--text-muted)" }}>Top Performers</div>
          <div className="flex flex-wrap gap-1.5">
            {data.best_picks.slice(0, 5).map((p, i) => (
              <div key={`${p.ticker}-${i}`} className="text-[10px] px-1.5 py-0.5 rounded flex items-center gap-1" style={{ backgroundColor: "var(--green-dim)", border: "1px solid var(--green)" + "40" }}>
                <span className="font-bold">{p.ticker}</span>
                <span className="tabular-nums" style={{ color: "var(--green)", fontFamily: "var(--font-mono)" }}>+{p.return_pct}%</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
