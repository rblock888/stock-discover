"use client";

import { useEffect, useState, useCallback } from "react";
import {
  getPhotonicsCycle,
  rescanPhotonicsCycle,
  PhotonicsCycleResponse,
  CyclePhase,
  PhaseResult,
} from "@/lib/api";

// ─── helpers ─────────────────────────────────────────────────────────────────

function fmtMcap(n: number): string {
  if (!n) return "—";
  if (n >= 1e9) return `$${(n / 1e9).toFixed(1)}B`;
  return `$${(n / 1e6).toFixed(0)}M`;
}

const STATUS_META: Record<string, { label: string; bg: string; fg: string }> = {
  in_progress: { label: "Moving",   bg: "#78350f30", fg: "#fbbf24" },
  emerging:    { label: "Emerging", bg: "#0c4a6e30", fg: "#38bdf8" },
  current:     { label: "HOT NOW",  bg: "#14532d30", fg: "#22c55e" },
  upcoming:    { label: "Upcoming", bg: "#1e1b4b30", fg: "#818cf8" },
  future:      { label: "Future",   bg: "#1c1917",   fg: "#78716c" },
};

const ASYMMETRY_LABEL: Record<string, string> = {
  medium:    "medium asymmetry",
  high:      "high asymmetry",
  very_high: "highest asymmetry",
};

// ─── Cycle timeline header ────────────────────────────────────────────────────

function CycleTimeline({ phases, currentPhaseNum }: { phases: CyclePhase[]; currentPhaseNum: number }) {
  return (
    <div className="flex items-center gap-0 px-4 py-3 overflow-x-auto">
      {phases.map((phase, i) => {
        const isCurrent = phase.num === currentPhaseNum;
        const isPast = phase.num < currentPhaseNum;
        const meta = STATUS_META[phase.status] ?? STATUS_META.future;
        return (
          <div key={phase.id} className="flex items-center shrink-0">
            {/* Node */}
            <div className="flex flex-col items-center gap-1">
              <div
                className="flex items-center justify-center text-[10px] font-bold rounded-full transition-all"
                style={{
                  width: isCurrent ? 28 : 22,
                  height: isCurrent ? 28 : 22,
                  backgroundColor: isCurrent ? phase.color : isPast ? phase.color + "50" : "var(--bg-elevated)",
                  border: `2px solid ${isCurrent ? phase.color : isPast ? phase.color + "60" : "var(--border)"}`,
                  color: isCurrent ? "#fff" : isPast ? phase.color : "var(--text-muted)",
                  boxShadow: isCurrent ? `0 0 12px ${phase.color}60` : "none",
                }}
              >
                {phase.num}
              </div>
              <div className="text-center" style={{ minWidth: 88 }}>
                <div
                  className="text-[10px] font-semibold leading-tight"
                  style={{ color: isCurrent ? phase.color : isPast ? "var(--text-secondary)" : "var(--text-muted)" }}
                >
                  {phase.name}
                </div>
                <div className="text-[8px] mt-0.5" style={{ color: "var(--text-muted)" }}>
                  {phase.timeline}
                </div>
                <span
                  className="inline-block text-[8px] font-bold uppercase tracking-[0.06em] px-1 py-[1px] rounded mt-0.5"
                  style={{ backgroundColor: meta.bg, color: meta.fg }}
                >
                  {meta.label}
                </span>
              </div>
            </div>
            {/* Connector */}
            {i < phases.length - 1 && (
              <div
                className="h-[2px] mx-1 mb-5 shrink-0"
                style={{
                  width: 32,
                  backgroundColor: phase.num < currentPhaseNum ? phase.color + "60" : "var(--border)",
                }}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}

// ─── Single ticker row ────────────────────────────────────────────────────────

function TickerRow({ result, color }: { result: PhaseResult; color: string }) {
  const [expanded, setExpanded] = useState(false);
  const { filters } = result;

  const filterKeys = ["stack", "mcap", "revenue", "supply", "capacity"] as const;

  return (
    <>
      <tr
        className="cursor-pointer transition-colors hover:bg-[var(--bg-elevated)]"
        onClick={() => setExpanded(!expanded)}
      >
        {/* Ticker */}
        <td className="px-3 py-2">
          <div className="flex items-center gap-2">
            <span className="text-[13px] font-bold" style={{ letterSpacing: "-0.01em" }}>
              {result.ticker}
            </span>
            {result.is_candidate && (
              <span
                className="text-[8px] font-bold uppercase tracking-[0.08em] px-1 py-[1px] rounded"
                style={{ backgroundColor: color + "20", color }}
              >
                ★
              </span>
            )}
          </div>
          <div className="text-[10px] truncate max-w-[130px]" style={{ color: "var(--text-muted)" }}>
            {result.name}
          </div>
        </td>

        {/* Market cap */}
        <td className="px-3 py-2 tabular-nums text-[11px]" style={{ color: "var(--text-secondary)", fontFamily: "var(--font-mono)" }}>
          {fmtMcap(result.market_cap)}
        </td>

        {/* Filter dots */}
        <td className="px-3 py-2">
          <div className="flex items-center gap-1">
            {filterKeys.map((key) => (
              <span
                key={key}
                title={`${key}: ${filters[key].score} — ${filters[key].label}`}
                className="w-2 h-2 rounded-full cursor-default"
                style={{ backgroundColor: filters[key].pass ? color : "var(--border)" }}
              />
            ))}
            <span className="text-[9px] pl-0.5" style={{ color: "var(--text-muted)" }}>
              {result.filters_passed}/5
            </span>
          </div>
        </td>

        {/* Capacity hits */}
        <td className="px-3 py-2 max-w-[180px]">
          {result.capacity_hits.length > 0 ? (
            <div className="flex flex-wrap gap-1">
              {result.capacity_hits.slice(0, 2).map((h) => (
                <span
                  key={h}
                  className="text-[9px] px-1 py-[1px] rounded truncate"
                  style={{ backgroundColor: "var(--amber-dim)", color: "var(--amber)", maxWidth: 86 }}
                >
                  {h}
                </span>
              ))}
            </div>
          ) : (
            <span className="text-[10px]" style={{ color: "var(--border)" }}>—</span>
          )}
        </td>

        {/* Phase score */}
        <td className="px-3 py-2 text-right">
          {result.narrative_penalty > 0 && (
            <span className="text-[9px] pr-1" style={{ color: "var(--red)" }}>
              -{result.narrative_penalty}
            </span>
          )}
          <span
            className="text-[18px] font-bold tabular-nums"
            style={{ color: result.phase_score >= 60 ? color : result.phase_score >= 40 ? "var(--amber)" : "var(--text-muted)", fontFamily: "var(--font-mono)", letterSpacing: "-0.02em" }}
          >
            {result.phase_score}
          </span>
        </td>
      </tr>

      {expanded && (
        <tr style={{ backgroundColor: "var(--bg-elevated)" }}>
          <td colSpan={5} className="px-3 pb-3 pt-1">
            <div className="grid grid-cols-5 gap-1.5 mt-1">
              {filterKeys.map((key) => {
                const f = filters[key];
                return (
                  <div
                    key={key}
                    className="rounded p-1.5"
                    style={{
                      backgroundColor: "var(--bg-surface)",
                      border: `1px solid ${f.pass ? color : "var(--border)"}40`,
                    }}
                  >
                    <div className="flex justify-between mb-0.5">
                      <span className="text-[8px] uppercase tracking-[0.06em]" style={{ color: "var(--text-muted)" }}>
                        {key}
                      </span>
                      <span className="text-[10px] font-bold tabular-nums" style={{ color: f.pass ? color : "var(--text-muted)", fontFamily: "var(--font-mono)" }}>
                        {f.score}
                      </span>
                    </div>
                    <p className="text-[9px]" style={{ color: "var(--text-secondary)" }}>{f.label}</p>
                  </div>
                );
              })}
            </div>
            {result.supply_hits.length > 0 && (
              <p className="text-[10px] mt-2" style={{ color: "var(--text-muted)" }}>
                Supply chain: {result.supply_hits.join(" · ")}
              </p>
            )}
            {result.narrative_penalty > 0 && (
              <p className="text-[10px] mt-1" style={{ color: "var(--red)" }}>
                ⚠ Narrative premium −{result.narrative_penalty} pts
              </p>
            )}
          </td>
        </tr>
      )}
    </>
  );
}

// ─── Phase section ────────────────────────────────────────────────────────────

function PhaseSection({ phase, defaultOpen }: { phase: CyclePhase; defaultOpen: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  const meta = STATUS_META[phase.status] ?? STATUS_META.future;
  const isCurrent = phase.status === "current";

  return (
    <div
      className="rounded-lg overflow-hidden"
      style={{
        border: `1px solid ${isCurrent ? phase.color + "60" : "var(--border)"}`,
        boxShadow: isCurrent ? `0 0 16px ${phase.color}18` : "none",
      }}
    >
      {/* Phase header */}
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-start gap-3 px-4 py-3 text-left transition-colors hover:bg-[var(--bg-elevated)]"
        style={{ backgroundColor: isCurrent ? phase.color + "08" : "var(--bg-surface)" }}
      >
        {/* Phase number pill */}
        <div
          className="flex items-center justify-center text-[11px] font-bold rounded-full shrink-0 mt-0.5"
          style={{
            width: 24, height: 24,
            backgroundColor: phase.color + "20",
            border: `1.5px solid ${phase.color}`,
            color: phase.color,
          }}
        >
          {phase.num}
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span
              className="text-[14px] font-bold"
              style={{ color: isCurrent ? phase.color : "var(--text-primary)", letterSpacing: "-0.01em" }}
            >
              {phase.name}
            </span>
            <span
              className="text-[9px] font-bold uppercase tracking-[0.08em] px-1.5 py-[2px] rounded"
              style={{ backgroundColor: meta.bg, color: meta.fg }}
            >
              {meta.label}
            </span>
            {isCurrent && (
              <span
                className="text-[9px] font-bold uppercase tracking-[0.08em] px-1.5 py-[2px] rounded"
                style={{ backgroundColor: phase.color + "20", color: phase.color }}
              >
                {ASYMMETRY_LABEL[phase.asymmetry]}
              </span>
            )}
            {phase.candidates.length > 0 && (
              <span className="text-[10px]" style={{ color: "var(--text-muted)" }}>
                {phase.candidates.length} candidate{phase.candidates.length !== 1 ? "s" : ""}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2 mt-0.5">
            <span className="text-[10px] font-medium" style={{ color: phase.color + "cc" }}>
              {phase.layer}
            </span>
            <span className="text-[10px]" style={{ color: "var(--text-muted)" }}>
              · {phase.timeline}
            </span>
          </div>
          {open && (
            <p className="text-[11px] mt-1.5 leading-relaxed" style={{ color: "var(--text-secondary)" }}>
              {phase.description}
            </p>
          )}
        </div>

        <span className="text-[10px] shrink-0" style={{ color: "var(--text-muted)" }}>
          {open ? "▲" : "▼"}
        </span>
      </button>

      {/* Ticker table */}
      {open && (
        phase.results.length === 0 ? (
          <div className="px-4 py-3 text-[11px]" style={{ color: "var(--text-muted)", borderTop: "1px solid var(--border)" }}>
            No results yet
          </div>
        ) : (
          <table className="w-full border-collapse" style={{ borderTop: "1px solid var(--border)" }}>
            <thead>
              <tr style={{ backgroundColor: "var(--bg-primary)" }}>
                {["Ticker", "MCap", "Filters", "Capacity Signals", "Phase Score"].map((h) => (
                  <th
                    key={h}
                    className="px-3 py-1.5 text-left text-[9px] uppercase tracking-[0.06em] font-medium"
                    style={{ color: "var(--text-muted)" }}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {phase.results.map((r) => (
                <TickerRow key={r.ticker} result={r} color={phase.color} />
              ))}
            </tbody>
          </table>
        )
      )}
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

export function PhotonicsCycle() {
  const [data, setData] = useState<PhotonicsCycleResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [scanning, setScanning] = useState(false);

  const fetch = useCallback(async () => {
    try {
      setData(await getPhotonicsCycle());
    } catch {
      /* optional panel */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetch(); }, [fetch]);

  useEffect(() => {
    if (!data?.scan_in_progress) return;
    const t = setInterval(async () => {
      const d = await getPhotonicsCycle();
      setData(d);
      if (!d.scan_in_progress) clearInterval(t);
    }, 5000);
    return () => clearInterval(t);
  }, [data?.scan_in_progress]);

  async function handleRescan() {
    if (scanning || data?.scan_in_progress) return;
    setScanning(true);
    await rescanPhotonicsCycle();
    const poll = setInterval(async () => {
      const d = await getPhotonicsCycle();
      setData(d);
      if (!d.scan_in_progress) {
        setScanning(false);
        clearInterval(poll);
      }
    }, 5000);
  }

  const isRunning = scanning || !!data?.scan_in_progress;

  return (
    <div
      className="rounded-lg overflow-hidden"
      style={{ backgroundColor: "var(--bg-surface)", border: "1px solid var(--border)" }}
    >
      {/* ── Panel header ── */}
      <div
        className="flex items-center justify-between px-4 py-3"
        style={{ borderBottom: "1px solid var(--border)" }}
      >
        <div className="flex items-center gap-3">
          <span className="text-[13px] font-semibold" style={{ letterSpacing: "-0.01em" }}>
            Photonics Cycle
          </span>
          <span className="text-[11px]" style={{ color: "var(--text-muted)" }}>
            5-phase AI optics supply chain model
          </span>
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
            onClick={handleRescan}
            disabled={isRunning}
            className="text-[11px] px-3 py-1 rounded transition-colors"
            style={{ backgroundColor: "var(--bg-elevated)", color: "var(--text-secondary)", border: "1px solid var(--border)" }}
          >
            {isRunning ? "Scanning…" : "Rescan"}
          </button>
        </div>
      </div>

      {/* ── Cycle timeline ── */}
      {data?.phases && data.phases.length > 0 && (
        <div style={{ borderBottom: "1px solid var(--border)", backgroundColor: "var(--bg-primary)" }}>
          <CycleTimeline phases={data.phases} currentPhaseNum={data.current_phase_num} />
        </div>
      )}

      {/* ── Core insight banner ── */}
      <div
        className="px-4 py-2 text-[10px]"
        style={{ borderBottom: "1px solid var(--border)", backgroundColor: "var(--bg-primary)", color: "var(--text-muted)" }}
      >
        <span style={{ color: "var(--text-secondary)", fontWeight: 600 }}>Core insight:</span>{" "}
        The market always misprices one layer behind reality — GPUs → optics → packaging → test → materials.
        Each phase creates a new wave of AXT-style moves in the layer <em>below</em> the last discovered bottleneck.
      </div>

      {/* ── Phase sections ── */}
      {loading ? (
        <div className="flex items-center justify-center h-24 text-[12px]" style={{ color: "var(--text-muted)" }}>
          Loading…
        </div>
      ) : !data?.phases?.length ? (
        <div className="flex items-center justify-center h-24 text-[12px]" style={{ color: "var(--text-muted)" }}>
          {isRunning ? "Running initial scan…" : "No data — click Rescan to start"}
        </div>
      ) : (
        <div className="p-4 space-y-3">
          {data.phases.map((phase) => (
            <PhaseSection
              key={phase.id}
              phase={phase}
              defaultOpen={phase.status === "current" || phase.status === "emerging"}
            />
          ))}
        </div>
      )}
    </div>
  );
}
