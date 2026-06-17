"use client";

// Hand-rolled SVG gauge primitives — no chart library, consistent with the
// TradingView-dark design tokens in globals.css.

// ─── ArcGauge — semicircular dial (market mood) ──────────────────────────────

export function ArcGauge({
  value,
  color,
  width = 132,
}: {
  value: number; // 0-100
  color: string;
  width?: number;
}) {
  const r = 48;
  const arcLen = Math.PI * r;
  const filled = (Math.max(0, Math.min(100, value)) / 100) * arcLen;
  const height = (width / 132) * 78;

  return (
    <svg viewBox="0 0 132 78" width={width} height={height}>
      <path
        d="M 18 70 A 48 48 0 0 1 114 70"
        fill="none"
        stroke="var(--bg-elevated)"
        strokeWidth={9}
        strokeLinecap="round"
      />
      <path
        d="M 18 70 A 48 48 0 0 1 114 70"
        fill="none"
        stroke={color}
        strokeWidth={9}
        strokeLinecap="round"
        strokeDasharray={`${filled} ${arcLen + 10}`}
        style={{ transition: "stroke-dasharray 0.8s ease, stroke 0.4s ease" }}
      />
      <text
        x={66}
        y={66}
        textAnchor="middle"
        fill="var(--text-primary)"
        style={{ font: "700 24px var(--font-mono)", letterSpacing: "-0.02em" }}
      >
        {Math.round(value)}
      </text>
    </svg>
  );
}

// ─── ScaleGauge — 3-zone horizontal track with marker ───────────────────────

export function ScaleGauge({
  stops,
  activeIndex,
  position,
  color,
}: {
  stops: string[]; // e.g. ["QUIET", "TRADABLE", "WILD"]
  activeIndex: number;
  position: number; // 0-100 marker position
  color: string;
}) {
  const pos = Math.max(2, Math.min(98, position));
  return (
    <div>
      <div className="relative h-[6px] rounded-full" style={{ backgroundColor: "var(--bg-elevated)" }}>
        {stops.slice(1).map((_, i) => (
          <div
            key={i}
            className="absolute top-0 bottom-0 w-px"
            style={{ left: `${((i + 1) / stops.length) * 100}%`, backgroundColor: "var(--bg-primary)" }}
          />
        ))}
        <div
          className="absolute top-1/2 w-[11px] h-[11px] rounded-full"
          style={{
            left: `${pos}%`,
            transform: "translate(-50%, -50%)",
            backgroundColor: color,
            boxShadow: `0 0 10px ${color}80`,
            border: "2px solid var(--bg-surface)",
            transition: "left 0.6s ease, background-color 0.4s ease",
          }}
        />
      </div>
      <div className="flex mt-1.5">
        {stops.map((s, i) => (
          <span
            key={s}
            className="flex-1 text-[8px] uppercase tracking-[0.08em] font-bold"
            style={{
              color: i === activeIndex ? color : "var(--text-muted)",
              textAlign: i === 0 ? "left" : i === stops.length - 1 ? "right" : "center",
            }}
          >
            {s}
          </span>
        ))}
      </div>
    </div>
  );
}

// ─── DivergingBar — center-zero bar (IWM vs SPY) ─────────────────────────────

export function DivergingBar({
  value,
  max = 5,
  color,
}: {
  value: number; // e.g. relative % return, negative = left
  max?: number;
  color: string;
}) {
  const pct = Math.min(Math.abs(value) / max, 1) * 50;
  return (
    <div className="relative h-[8px] rounded-full" style={{ backgroundColor: "var(--bg-elevated)" }}>
      <div className="absolute top-0 bottom-0 w-px left-1/2" style={{ backgroundColor: "var(--text-muted)", opacity: 0.5 }} />
      <div
        className="absolute top-0 bottom-0 rounded-full"
        style={{
          left: value >= 0 ? "50%" : `${50 - pct}%`,
          width: `${pct}%`,
          backgroundColor: color,
          transition: "all 0.6s ease",
        }}
      />
    </div>
  );
}

// ─── Sparkline — tiny multi-series polyline ──────────────────────────────────

export interface SparkSeries {
  points: (number | null)[];
  color: string;
  dashed?: boolean;
}

export function Sparkline({
  series,
  height = 40,
  className,
}: {
  series: SparkSeries[];
  height?: number;
  className?: string;
}) {
  const all = series.flatMap((s) => s.points.filter((p): p is number => p != null));
  if (all.length < 2) return null;
  const min = Math.min(...all);
  const max = Math.max(...all);
  const range = max - min || 1;

  const W = 100;
  const H = 32;

  function toPath(points: (number | null)[]): string {
    const n = points.length;
    if (n < 2) return "";
    return points
      .map((p, i) => {
        if (p == null) return null;
        const x = (i / (n - 1)) * W;
        const y = H - 2 - ((p - min) / range) * (H - 4);
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .filter(Boolean)
      .join(" ");
  }

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="none"
      className={className}
      style={{ width: "100%", height, display: "block" }}
    >
      {series.map((s, i) => {
        const pts = toPath(s.points);
        if (!pts) return null;
        return (
          <polyline
            key={i}
            points={pts}
            fill="none"
            stroke={s.color}
            strokeWidth={1.5}
            strokeDasharray={s.dashed ? "3 3" : undefined}
            vectorEffect="non-scaling-stroke"
            strokeLinejoin="round"
          />
        );
      })}
    </svg>
  );
}

// ─── HBar — simple horizontal fill bar ───────────────────────────────────────

export function HBar({
  pct,
  color,
  height = 6,
}: {
  pct: number; // 0-100
  color: string;
  height?: number;
}) {
  return (
    <div className="rounded-full overflow-hidden" style={{ backgroundColor: "var(--bg-elevated)", height }}>
      <div
        className="h-full rounded-full"
        style={{
          width: `${Math.max(0, Math.min(100, pct))}%`,
          backgroundColor: color,
          transition: "width 0.6s ease",
        }}
      />
    </div>
  );
}
