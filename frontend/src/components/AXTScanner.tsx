"use client";

import { useEffect, useState, useCallback } from "react";
import { getAxtScan, runAxtScan, AxtResult, AxtScanResponse } from "@/lib/api";

function formatMcap(n: number): string {
  if (!n) return "—";
  if (n >= 1e9) return `$${(n / 1e9).toFixed(1)}B`;
  if (n >= 1e6) return `$${(n / 1e6).toFixed(0)}M`;
  return `$${(n / 1e3).toFixed(0)}K`;
}

function rerateColor(score: number): string {
  if (score >= 65) return "var(--green)";
  if (score >= 45) return "var(--amber)";
  return "var(--text-muted)";
}

function layerColor(layer: string): string {
  if (layer.includes("Compound")) return "#a78bfa";
  if (layer.includes("Photonics")) return "#38bdf8";
  if (layer.includes("Packaging")) return "#fb923c";
  return "var(--text-muted)";
}

function FilterDot({ pass, label, score }: { pass: boolean; label: string; score: number }) {
  return (
    <span title={`${label}: ${score}`} className="relative group cursor-default">
      <span
        className="inline-block w-2 h-2 rounded-full"
        style={{ backgroundColor: pass ? "var(--green)" : "var(--border)" }}
      />
      <span
        className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1 hidden group-hover:block
                   text-[10px] whitespace-nowrap px-1.5 py-0.5 rounded z-10 pointer-events-none"
        style={{ backgroundColor: "var(--bg-elevated)", border: "1px solid var(--border)", color: "var(--text-secondary)" }}
      >
        {label}: {score}
      </span>
    </span>
  );
}

function CandidateRow({ result }: { result: AxtResult }) {
  const [expanded, setExpanded] = useState(false);
  const { filters } = result;

  return (
    <>
      <tr
        className="cursor-pointer hover:bg-[var(--bg-elevated)] transition-colors"
        onClick={() => setExpanded(!expanded)}
      >
        {/* Ticker + name */}
        <td className="px-3 py-2 w-[160px]">
          <div className="flex items-center gap-2">
            <span className="text-[13px] font-bold" style={{ letterSpacing: "-0.01em" }}>
              {result.ticker}
            </span>
            {result.is_candidate && (
              <span
                className="text-[8px] font-bold uppercase tracking-[0.1em] px-1 py-[1px] rounded"
                style={{ backgroundColor: "#a78bfa20", color: "#a78bfa" }}
              >
                AXT
              </span>
            )}
          </div>
          <div className="text-[10px] truncate max-w-[140px]" style={{ color: "var(--text-muted)" }}>
            {result.name}
          </div>
        </td>

        {/* Stack layer */}
        <td className="px-3 py-2">
          <span
            className="text-[10px] font-medium px-1.5 py-[2px] rounded"
            style={{
              color: layerColor(result.stack_layer),
              backgroundColor: layerColor(result.stack_layer) + "18",
            }}
          >
            {result.stack_layer}
          </span>
        </td>

        {/* Market cap */}
        <td className="px-3 py-2 tabular-nums text-[11px]" style={{ color: "var(--text-secondary)", fontFamily: "var(--font-mono)" }}>
          {formatMcap(result.market_cap)}
        </td>

        {/* Filter dots */}
        <td className="px-3 py-2">
          <div className="flex items-center gap-1.5">
            <FilterDot pass={filters.stack_position.pass} label="Stack" score={filters.stack_position.score} />
            <FilterDot pass={filters.market_cap.pass} label="MCap" score={filters.market_cap.score} />
            <FilterDot pass={filters.revenue_profile.pass} label="Revenue" score={filters.revenue_profile.score} />
            <FilterDot pass={filters.supply_chain.pass} label="Supply" score={filters.supply_chain.score} />
            <FilterDot pass={filters.capacity_signal.pass} label="Capacity" score={filters.capacity_signal.score} />
            <span className="text-[9px] pl-0.5" style={{ color: "var(--text-muted)" }}>
              {result.filters_passed}/5
            </span>
          </div>
        </td>

        {/* Capacity hits badge */}
        <td className="px-3 py-2 max-w-[200px]">
          {result.capacity_hits.length > 0 ? (
            <div className="flex flex-wrap gap-1">
              {result.capacity_hits.slice(0, 2).map((h) => (
                <span
                  key={h}
                  className="text-[9px] px-1 py-[1px] rounded truncate"
                  style={{ backgroundColor: "var(--amber-dim)", color: "var(--amber)", maxWidth: 90 }}
                >
                  {h}
                </span>
              ))}
            </div>
          ) : (
            <span className="text-[10px]" style={{ color: "var(--border)" }}>—</span>
          )}
        </td>

        {/* Rerate score */}
        <td className="px-3 py-2 text-right">
          {result.narrative_penalty > 0 && (
            <span className="text-[9px] pr-1.5" style={{ color: "var(--red)" }} title="Narrative premium penalty">
              -{result.narrative_penalty}
            </span>
          )}
          <span
            className="text-[18px] font-bold tabular-nums"
            style={{ color: rerateColor(result.rerate_score), fontFamily: "var(--font-mono)", letterSpacing: "-0.02em" }}
          >
            {result.rerate_score}
          </span>
          <span className="text-[9px] pl-1" style={{ color: "var(--text-muted)" }}>/ 100</span>
        </td>
      </tr>

      {expanded && (
        <tr style={{ backgroundColor: "var(--bg-elevated)" }}>
          <td colSpan={6} className="px-3 pb-3 pt-1">
            <div className="grid grid-cols-2 lg:grid-cols-5 gap-2 mt-1">
              {Object.entries(filters).map(([key, f]) => (
                <div
                  key={key}
                  className="rounded p-2"
                  style={{
                    backgroundColor: "var(--bg-surface)",
                    border: `1px solid ${f.pass ? "var(--green)" : "var(--border)"}40`,
                  }}
                >
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-[9px] uppercase tracking-[0.08em]" style={{ color: "var(--text-muted)" }}>
                      {key.replace("_", " ")}
                    </span>
                    <span
                      className="text-[11px] font-bold tabular-nums"
                      style={{ color: f.pass ? "var(--green)" : "var(--text-muted)", fontFamily: "var(--font-mono)" }}
                    >
                      {f.score}
                    </span>
                  </div>
                  <p className="text-[10px]" style={{ color: "var(--text-secondary)" }}>
                    {f.label}
                  </p>
                  {f.hits && f.hits.length > 0 && (
                    <div className="flex flex-wrap gap-0.5 mt-1">
                      {f.hits.slice(0, 3).map((h) => (
                        <span key={h} className="text-[8px] px-1 py-[1px] rounded" style={{ backgroundColor: "var(--bg-primary)", color: "var(--accent-bright)" }}>
                          {h}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
            {result.narrative_hits.length > 0 && (
              <p className="text-[10px] mt-2" style={{ color: "var(--red)" }}>
                ⚠ Narrative premium detected: {result.narrative_hits.join(", ")} (−{result.narrative_penalty} penalty)
              </p>
            )}
            {result.supply_hits.length > 0 && (
              <p className="text-[10px] mt-1" style={{ color: "var(--text-muted)" }}>
                Supply chain: {result.supply_hits.join(" · ")}
              </p>
            )}
          </td>
        </tr>
      )}
    </>
  );
}

export function AXTScanner() {
  const [data, setData] = useState<AxtScanResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [scanning, setScanning] = useState(false);
  const [showAll, setShowAll] = useState(false);

  const fetch = useCallback(async () => {
    try {
      const d = await getAxtScan();
      setData(d);
    } catch {
      // silently fail — optional panel
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetch(); }, [fetch]);

  // Poll while scan is in progress
  useEffect(() => {
    if (!data?.scan_in_progress) return;
    const t = setInterval(async () => {
      const d = await getAxtScan();
      setData(d);
      if (!d.scan_in_progress) clearInterval(t);
    }, 4000);
    return () => clearInterval(t);
  }, [data?.scan_in_progress]);

  async function handleScan() {
    if (scanning) return;
    setScanning(true);
    await runAxtScan();
    // Poll until done
    const poll = setInterval(async () => {
      const d = await getAxtScan();
      setData(d);
      if (!d.scan_in_progress) {
        setScanning(false);
        clearInterval(poll);
      }
    }, 4000);
  }

  const isRunning = scanning || data?.scan_in_progress;
  const results = data?.results ?? [];
  const candidates = results.filter((r) => r.is_candidate);
  const displayed = showAll ? results : results.slice(0, 10);

  return (
    <div
      className="rounded-lg overflow-hidden"
      style={{ backgroundColor: "var(--bg-surface)", border: "1px solid var(--border)" }}
    >
      {/* Header */}
      <div
        className="flex items-center justify-between px-4 py-3"
        style={{ borderBottom: "1px solid var(--border)" }}
      >
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <span
              className="w-2 h-2 rounded-full"
              style={{ backgroundColor: "#a78bfa" }}
            />
            <span className="text-[13px] font-semibold" style={{ letterSpacing: "-0.01em" }}>
              AXT Microcap Scanner
            </span>
          </div>
          <span className="text-[11px]" style={{ color: "var(--text-muted)" }}>
            compound semi · photonics · adv. packaging
          </span>
          {candidates.length > 0 && (
            <span
              className="text-[10px] font-bold px-2 py-[2px] rounded"
              style={{ backgroundColor: "#a78bfa20", color: "#a78bfa" }}
            >
              {candidates.length} candidate{candidates.length !== 1 ? "s" : ""}
            </span>
          )}
        </div>

        <div className="flex items-center gap-3">
          {data?.last_scan && (
            <span className="text-[10px]" style={{ color: "var(--text-muted)" }}>
              {new Date(data.last_scan).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
            </span>
          )}
          {isRunning && (
            <span className="text-[10px] flex items-center gap-1" style={{ color: "var(--amber)" }}>
              <span className="w-1.5 h-1.5 rounded-full animate-pulse" style={{ backgroundColor: "var(--amber)" }} />
              scanning
            </span>
          )}
          <button
            onClick={handleScan}
            disabled={!!isRunning}
            className="text-[11px] px-3 py-1 rounded transition-colors"
            style={{
              backgroundColor: "var(--bg-elevated)",
              color: "var(--text-secondary)",
              border: "1px solid var(--border)",
            }}
          >
            {isRunning ? "Scanning…" : "Rescan"}
          </button>
        </div>
      </div>

      {/* Legend */}
      <div
        className="flex items-center gap-4 px-4 py-2 text-[10px]"
        style={{ borderBottom: "1px solid var(--border)", color: "var(--text-muted)", backgroundColor: "var(--bg-primary)" }}
      >
        <span>Filters: </span>
        <span><span style={{ color: "#a78bfa" }}>■</span> Stack Position</span>
        <span><span style={{ color: "var(--text-secondary)" }}>■</span> Market Cap ($50–$300M)</span>
        <span><span style={{ color: "var(--text-secondary)" }}>■</span> Revenue Profile</span>
        <span><span style={{ color: "var(--text-secondary)" }}>■</span> Supply Chain Depth</span>
        <span><span style={{ color: "var(--amber)" }}>■</span> Capacity Signal</span>
        <span className="ml-auto">Score = rerate probability 0–100</span>
      </div>

      {/* Table */}
      {loading ? (
        <div className="flex items-center justify-center h-24 text-[12px]" style={{ color: "var(--text-muted)" }}>
          Loading…
        </div>
      ) : results.length === 0 ? (
        <div className="flex items-center justify-center h-24 text-[12px]" style={{ color: "var(--text-muted)" }}>
          {isRunning ? "Scanning seed universe…" : "No results yet — click Rescan"}
        </div>
      ) : (
        <>
          <table className="w-full border-collapse">
            <thead>
              <tr style={{ borderBottom: "1px solid var(--border)" }}>
                {["Ticker", "Stack Layer", "Market Cap", "Filters", "Capacity Signals", "Rerate Score"].map((h) => (
                  <th
                    key={h}
                    className="px-3 py-1.5 text-left text-[9px] uppercase tracking-[0.08em] font-medium"
                    style={{ color: "var(--text-muted)" }}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody style={{ borderTop: "1px solid var(--border)" }}>
              {displayed.map((r) => (
                <CandidateRow key={r.ticker} result={r} />
              ))}
            </tbody>
          </table>

          {results.length > 10 && (
            <button
              onClick={() => setShowAll(!showAll)}
              className="w-full h-8 text-[10px] uppercase tracking-[0.08em] transition-colors hover:bg-[var(--bg-elevated)]"
              style={{ color: "var(--text-muted)", borderTop: "1px solid var(--border)" }}
            >
              {showAll ? `Show fewer` : `Show all ${results.length} tickers`}
            </button>
          )}
        </>
      )}

      {/* Thesis footer */}
      <div
        className="px-4 py-2.5 text-[10px] leading-relaxed"
        style={{ borderTop: "1px solid var(--border)", color: "var(--text-muted)", backgroundColor: "var(--bg-primary)" }}
      >
        <span style={{ color: "var(--text-secondary)", fontWeight: 600 }}>AXT thesis:</span>{" "}
        Find upstream materials suppliers priced like industrial legacy that sit one layer below a newly discovered AI bottleneck.
        Sweet spot: $50M–$300M mcap, compound semi / photonics position, real revenue with no AI narrative yet.
        Rerate comes from reclassification, not growth.
      </div>
    </div>
  );
}
