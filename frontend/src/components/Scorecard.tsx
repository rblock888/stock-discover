"use client";

import { useCallback, useEffect, useState } from "react";
import {
  CalibrationCurve,
  Scorecard,
  ScorecardResponse,
  SignalCard,
  getScorecard,
} from "@/lib/api";

const SIGNAL_LABELS: Record<string, string> = {
  composite_score: "Composite",
  ml_score: "AI / ML",
};

function icColor(ic: number): string {
  if (ic >= 0.05) return "var(--green)";
  if (ic <= -0.05) return "var(--red)";
  return "var(--text-muted)";
}
function icVerdict(ic: number, spread: number): string {
  if (ic >= 0.1 && spread > 2) return "real edge";
  if (ic >= 0.04 && spread > 1.5) return "weak edge";
  if (ic <= -0.02 || spread < 0) return "no edge";
  return "inconclusive";
}

// ─── Calibration curve (score → measured win-rate) ───────────────────────────

function CalibrationChart({ cal }: { cal: CalibrationCurve }) {
  if (!cal?.available || !cal.curve || cal.curve.length < 2) return null;
  const pts = cal.curve;
  const W = 280, H = 120, padL = 30, padB = 20, padT = 8, padR = 8;
  const xs = pts.map((p) => p.score);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const maxP = Math.max(0.5, ...pts.map((p) => p.p_win));
  const sx = (x: number) => padL + ((x - minX) / (maxX - minX || 1)) * (W - padL - padR);
  const sy = (p: number) => H - padB - (p / maxP) * (H - padB - padT);
  const base = cal.base_rate ?? 0;

  const line = pts.map((p) => `${sx(p.score).toFixed(1)},${sy(p.p_win).toFixed(1)}`).join(" ");
  const area = `M ${sx(pts[0].score)},${H - padB} L ${pts.map((p) => `${sx(p.score).toFixed(1)},${sy(p.p_win).toFixed(1)}`).join(" L ")} L ${sx(pts[pts.length - 1].score)},${H - padB} Z`;

  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto" }}>
      <defs>
        <linearGradient id="calfill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--accent-bright)" stopOpacity="0.3" />
          <stop offset="100%" stopColor="var(--accent-bright)" stopOpacity="0" />
        </linearGradient>
      </defs>
      {/* base-rate line */}
      <line x1={padL} y1={sy(base)} x2={W - padR} y2={sy(base)} stroke="var(--text-muted)" strokeWidth={1} strokeDasharray="3 3" opacity={0.6} />
      <text x={W - padR} y={sy(base) - 3} textAnchor="end" fontSize={8} fill="var(--text-muted)">
        base {(base * 100).toFixed(0)}%
      </text>
      <path d={area} fill="url(#calfill)" />
      <polyline points={line} fill="none" stroke="var(--accent-bright)" strokeWidth={2} strokeLinejoin="round" />
      {pts.map((p, i) => (
        <circle key={i} cx={sx(p.score)} cy={sy(p.p_win)} r={2.5} fill="var(--accent-bright)" />
      ))}
      {/* axes labels */}
      <text x={padL} y={H - 6} fontSize={8} fill="var(--text-muted)">{minX.toFixed(0)}</text>
      <text x={W - padR} y={H - 6} textAnchor="end" fontSize={8} fill="var(--text-muted)">{maxX.toFixed(0)}</text>
      <text x={2} y={sy(maxP) + 3} fontSize={8} fill="var(--text-muted)">{(maxP * 100).toFixed(0)}%</text>
    </svg>
  );
}

// ─── Decile spread bars ──────────────────────────────────────────────────────

function DecileBars({ card }: { card: SignalCard }) {
  const d = card.deciles;
  if (!d?.length) return null;
  const max = Math.max(...d.map((x) => Math.abs(x.avg_return_pct)), 1);
  return (
    <div className="flex items-end gap-[3px] h-[60px]">
      {d.map((b) => {
        const up = b.avg_return_pct >= 0;
        const h = (Math.abs(b.avg_return_pct) / max) * 100;
        const color = up ? "var(--green)" : "var(--red)";
        return (
          <div key={b.bin} className="flex-1 flex flex-col items-center justify-end h-full" title={`score ${b.score_lo}-${b.score_hi} · ${b.avg_return_pct >= 0 ? "+" : ""}${b.avg_return_pct}% · ${b.win_rate}% win · n=${b.n}`}>
            <div
              className="w-full rounded-sm"
              style={{
                height: `${Math.max(3, h / 2)}%`,
                background: `linear-gradient(180deg, color-mix(in srgb, ${color} 60%, transparent), ${color})`,
                boxShadow: `0 0 8px color-mix(in srgb, ${color} 50%, transparent)`,
                alignSelf: up ? "flex-end" : "flex-start",
              }}
            />
          </div>
        );
      })}
    </div>
  );
}

function SignalRow({ field, card }: { field: string; card: SignalCard }) {
  const verdict = icVerdict(card.ic, card.top_minus_bottom_pct);
  const vColor = verdict.includes("real") ? "var(--green)" : verdict.includes("weak") ? "var(--amber)" : "var(--red)";
  return (
    <div className="rounded-xl p-3" style={{ background: "rgba(255,255,255,0.025)", border: "1px solid var(--border-subtle)" }}>
      <div className="flex items-center justify-between mb-2">
        <span className="text-[13px] font-bold">{SIGNAL_LABELS[field] ?? field}</span>
        <span className="text-[10px] font-bold uppercase tracking-[0.06em] px-2 py-[2px] rounded-full" style={{ backgroundColor: `color-mix(in srgb, ${vColor} 18%, transparent)`, color: vColor }}>
          {verdict}
        </span>
      </div>
      <div className="grid grid-cols-3 gap-2 mb-2.5">
        <Metric label="IC (rank corr)" value={card.ic >= 0 ? `+${card.ic.toFixed(2)}` : card.ic.toFixed(2)} color={icColor(card.ic)} />
        <Metric label="top − bottom" value={`${card.top_minus_bottom_pct >= 0 ? "+" : ""}${card.top_minus_bottom_pct.toFixed(1)}%`} color={card.top_minus_bottom_pct >= 0 ? "var(--green)" : "var(--red)"} />
        <Metric label="top vs bot win" value={`${card.top_win_rate.toFixed(0)}/${card.bottom_win_rate.toFixed(0)}%`} color="var(--text-secondary)" />
      </div>
      <DecileBars card={card} />
      <div className="text-[9px] mt-1.5 text-center" style={{ color: "var(--text-muted)" }}>
        avg forward return by score decile (low → high) · n={card.n}
      </div>
    </div>
  );
}

function Metric({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div>
      <div className="text-[15px] font-bold tabular-nums leading-none" style={{ fontFamily: "var(--font-mono)", color }}>{value}</div>
      <div className="text-[8px] uppercase tracking-[0.06em] mt-1" style={{ color: "var(--text-muted)" }}>{label}</div>
    </div>
  );
}

// ─── Root ─────────────────────────────────────────────────────────────────────

export function ScorecardPanel() {
  const [data, setData] = useState<ScorecardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [horizon, setHorizon] = useState<number>(5);

  const load = useCallback(() => {
    getScorecard().then((d) => { setData(d); setLoading(false); }).catch(() => setLoading(false));
  }, []);
  useEffect(() => { load(); }, [load]);

  const ds = data?.data_status;
  const cards = data?.scorecards ?? {};
  const available = Object.entries(cards).filter(([, c]) => c.available).map(([h]) => Number(h)).sort((a, b) => a - b);
  const active: Scorecard | undefined = cards[String(horizon)];
  const cal = data?.calibration?.[`composite_score@${horizon}`];

  return (
    <div className="glass glow-top rounded-2xl p-4 max-w-[1200px]" style={{ ["--glow-color" as string]: "var(--accent-bright)" }}>
      <div className="flex items-center justify-between mb-1">
        <div>
          <div className="text-[15px] font-bold" style={{ letterSpacing: "-0.02em" }}>Model Scorecard</div>
          <div className="text-[11px] mt-0.5" style={{ color: "var(--text-muted)" }}>
            Do the scores actually predict? Measured against real forward returns.
          </div>
        </div>
        {available.length > 0 && (
          <div className="flex gap-1">
            {[5, 10, 20, 60].map((h) => {
              const has = available.includes(h);
              const on = h === horizon;
              return (
                <button key={h} disabled={!has} onClick={() => setHorizon(h)}
                  className="text-[11px] px-2.5 py-1 rounded-md transition-colors"
                  style={{
                    backgroundColor: on ? "var(--accent-dim)" : "transparent",
                    color: !has ? "var(--text-muted)" : on ? "var(--accent-bright)" : "var(--text-secondary)",
                    border: `1px solid ${on ? "var(--accent)" : "transparent"}`,
                    opacity: has ? 1 : 0.4,
                    cursor: has ? "pointer" : "not-allowed",
                  }}>
                  {h}d
                </button>
              );
            })}
          </div>
        )}
      </div>

      {/* Honesty / coverage strip */}
      {ds && (
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-[10px] mt-2 mb-4 pb-3" style={{ color: "var(--text-muted)", borderBottom: "1px solid var(--border-subtle)" }}>
          <span><b style={{ color: "var(--text-secondary)" }}>{ds.trading_days_deep}</b> days of history</span>
          <span><b style={{ color: "var(--text-secondary)" }}>{ds.tickers_with_price_history}</b>/{ds.tickers_scored} real tickers</span>
          {ds.junk_tickers > 0 && <span style={{ color: "var(--amber)" }}>{ds.junk_tickers} junk symbols dropped</span>}
          <span>measured @ {available.length ? available.map((h) => `${h}d`).join(", ") : "—"}; longer horizons accruing</span>
        </div>
      )}

      {loading && <div className="h-32 flex items-center justify-center text-[12px]" style={{ color: "var(--text-muted)" }}>Loading…</div>}

      {!loading && !active?.available && (
        <div className="h-32 flex flex-col items-center justify-center gap-1 text-[12px]" style={{ color: "var(--text-muted)" }}>
          <span>Not enough forward data at {horizon}-day horizon yet.</span>
          <span className="text-[10px]">Picks must age {horizon} trading days before they can be scored — accruing automatically.</span>
        </div>
      )}

      {!loading && active?.available && (
        <>
          {/* Overall summary */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
            <Stat label={`avg return @${horizon}d`} value={`${active.overall_avg_return_pct! >= 0 ? "+" : ""}${active.overall_avg_return_pct}%`} color={active.overall_avg_return_pct! >= 0 ? "var(--green)" : "var(--red)"} />
            <Stat label="win rate (≥+10%)" value={`${active.overall_win_rate}%`} color="var(--text-primary)" />
            <Stat label="beat SPY" value={active.overall_beat_spy_rate != null ? `${active.overall_beat_spy_rate}%` : "—"} color={(active.overall_beat_spy_rate ?? 50) >= 50 ? "var(--green)" : "var(--red)"} />
            <Stat label="picks measured" value={`${active.n}`} color="var(--text-secondary)" />
          </div>

          {/* Per-signal cards */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 mb-4">
            {Object.entries(active.signals ?? {}).map(([field, card]) => (
              <SignalRow key={field} field={field} card={card} />
            ))}
          </div>

          {/* Calibration */}
          {cal?.available && (
            <div className="rounded-xl p-3" style={{ background: "rgba(255,255,255,0.025)", border: "1px solid var(--border-subtle)" }}>
              <div className="flex items-center justify-between mb-1">
                <span className="text-[12px] font-semibold">Composite calibration</span>
                <span className="text-[10px]" style={{ color: "var(--text-muted)" }}>score → measured P(≥+10% in {horizon}d) · n={cal.n}</span>
              </div>
              <CalibrationChart cal={cal} />
              <div className="text-[10px] mt-1" style={{ color: "var(--text-muted)" }}>
                The dashed line is the base rate. Where the curve rises above it, a higher score genuinely means a higher hit-rate.
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function Stat({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div className="rounded-xl p-3" style={{ background: "rgba(255,255,255,0.025)", border: "1px solid var(--border-subtle)" }}>
      <div className="text-[20px] font-bold tabular-nums leading-none" style={{ fontFamily: "var(--font-mono)", color }}>{value}</div>
      <div className="text-[9px] uppercase tracking-[0.06em] mt-1.5" style={{ color: "var(--text-muted)" }}>{label}</div>
    </div>
  );
}
