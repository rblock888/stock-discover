"use client";

import { useId } from "react";

// Hand-rolled SVG gauge primitives — glassmorphism style with gradient
// strokes/fills and soft glows. No chart library.

// ─── ArcGauge — semicircular dial with glowing gradient stroke ────────────────

export function ArcGauge({
  value,
  color,
  width = 134,
}: {
  value: number; // 0-100
  color: string;
  width?: number;
}) {
  const id = useId().replace(/:/g, "");
  const r = 48;
  const arcLen = Math.PI * r;
  const filled = (Math.max(0, Math.min(100, value)) / 100) * arcLen;
  const height = (width / 134) * 80;

  return (
    <svg viewBox="0 0 134 80" width={width} height={height}>
      <defs>
        <linearGradient id={`arc-${id}`} x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor={color} stopOpacity="0.45" />
          <stop offset="55%" stopColor={color} stopOpacity="1" />
          <stop offset="100%" stopColor={color} stopOpacity="0.92" />
        </linearGradient>
        <filter id={`arcglow-${id}`} x="-40%" y="-40%" width="180%" height="180%">
          <feGaussianBlur stdDeviation="3.2" result="b" />
          <feMerge>
            <feMergeNode in="b" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>
      <path
        d="M 19 70 A 48 48 0 0 1 115 70"
        fill="none"
        stroke="rgba(255,255,255,0.08)"
        strokeWidth={10}
        strokeLinecap="round"
      />
      <path
        d="M 19 70 A 48 48 0 0 1 115 70"
        fill="none"
        stroke={`url(#arc-${id})`}
        strokeWidth={10}
        strokeLinecap="round"
        strokeDasharray={`${filled} ${arcLen + 10}`}
        filter={`url(#arcglow-${id})`}
        style={{ transition: "stroke-dasharray 0.8s ease" }}
      />
      <text
        x={67}
        y={64}
        textAnchor="middle"
        fill="var(--text-primary)"
        style={{ font: "700 26px var(--font-mono)", letterSpacing: "-0.02em" }}
      >
        {Math.round(value)}
      </text>
    </svg>
  );
}

// ─── ScaleGauge — 3-zone horizontal track with glowing marker ────────────────

export function ScaleGauge({
  stops,
  activeIndex,
  position,
  color,
}: {
  stops: string[];
  activeIndex: number;
  position: number; // 0-100 marker position
  color: string;
}) {
  const pos = Math.max(2, Math.min(98, position));
  return (
    <div>
      <div
        className="relative h-[7px] rounded-full overflow-visible"
        style={{
          background:
            "linear-gradient(90deg, rgba(56,189,248,0.18), rgba(255,255,255,0.06) 45%, rgba(251,113,133,0.18))",
        }}
      >
        {stops.slice(1).map((_, i) => (
          <div
            key={i}
            className="absolute top-0 bottom-0 w-px"
            style={{ left: `${((i + 1) / stops.length) * 100}%`, backgroundColor: "rgba(8,12,30,0.6)" }}
          />
        ))}
        <div
          className="absolute top-1/2 w-[12px] h-[12px] rounded-full"
          style={{
            left: `${pos}%`,
            transform: "translate(-50%, -50%)",
            backgroundColor: color,
            boxShadow: `0 0 14px ${color}, 0 0 4px ${color}`,
            border: "2px solid rgba(255,255,255,0.85)",
            transition: "left 0.6s ease, background-color 0.4s ease",
          }}
        />
      </div>
      <div className="flex mt-2">
        {stops.map((s, i) => (
          <span
            key={s}
            className="flex-1 text-[8px] uppercase tracking-[0.08em] font-bold"
            style={{
              color: i === activeIndex ? color : "var(--text-muted)",
              textShadow: i === activeIndex ? `0 0 10px ${color}` : "none",
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

// ─── DivergingBar — center-zero bar with gradient + glow ─────────────────────

export function DivergingBar({
  value,
  max = 5,
  color,
}: {
  value: number;
  max?: number;
  color: string;
}) {
  const pct = Math.min(Math.abs(value) / max, 1) * 50;
  return (
    <div className="relative h-[9px] rounded-full" style={{ backgroundColor: "rgba(255,255,255,0.06)" }}>
      <div className="absolute top-0 bottom-0 w-px left-1/2" style={{ backgroundColor: "rgba(255,255,255,0.18)" }} />
      <div
        className="absolute top-0 bottom-0 rounded-full"
        style={{
          left: value >= 0 ? "50%" : `${50 - pct}%`,
          width: `${pct}%`,
          background: `linear-gradient(90deg, color-mix(in srgb, ${color} 45%, transparent), ${color})`,
          boxShadow: `0 0 12px color-mix(in srgb, ${color} 55%, transparent)`,
          transition: "all 0.6s ease",
        }}
      />
    </div>
  );
}

// ─── Sparkline — gradient stroke + soft area glow ────────────────────────────

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
  const id = useId().replace(/:/g, "");
  const all = series.flatMap((s) => s.points.filter((p): p is number => p != null));
  if (all.length < 2) return null;
  const min = Math.min(...all);
  const max = Math.max(...all);
  const range = max - min || 1;

  const W = 100;
  const H = 32;

  function coords(points: (number | null)[]): [number, number][] {
    const n = points.length;
    return points
      .map((p, i): [number, number] | null => {
        if (p == null) return null;
        const x = (i / (n - 1)) * W;
        const y = H - 2 - ((p - min) / range) * (H - 5);
        return [x, y];
      })
      .filter((c): c is [number, number] => c != null);
  }

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="none"
      className={className}
      style={{ width: "100%", height, display: "block" }}
    >
      {series.map((s, i) => {
        const pts = coords(s.points);
        if (pts.length < 2) return null;
        const line = pts.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
        const area = `M ${pts[0][0].toFixed(1)},${H} L ${line.replace(/ /g, " L ")} L ${pts[pts.length - 1][0].toFixed(1)},${H} Z`;
        return (
          <g key={i}>
            {!s.dashed && (
              <>
                <defs>
                  <linearGradient id={`spark-${id}-${i}`} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={s.color} stopOpacity="0.28" />
                    <stop offset="100%" stopColor={s.color} stopOpacity="0" />
                  </linearGradient>
                </defs>
                <path d={area} fill={`url(#spark-${id}-${i})`} stroke="none" />
              </>
            )}
            <polyline
              points={line}
              fill="none"
              stroke={s.color}
              strokeWidth={1.6}
              strokeDasharray={s.dashed ? "3 3" : undefined}
              vectorEffect="non-scaling-stroke"
              strokeLinejoin="round"
              strokeLinecap="round"
            />
          </g>
        );
      })}
    </svg>
  );
}

// ─── HBar — horizontal fill bar with gradient + glow ─────────────────────────

export function HBar({
  pct,
  color,
  height = 7,
}: {
  pct: number; // 0-100
  color: string;
  height?: number;
}) {
  return (
    <div className="rounded-full overflow-hidden" style={{ backgroundColor: "rgba(255,255,255,0.06)", height }}>
      <div
        className="h-full rounded-full"
        style={{
          width: `${Math.max(0, Math.min(100, pct))}%`,
          background: `linear-gradient(90deg, color-mix(in srgb, ${color} 50%, transparent), ${color})`,
          boxShadow: `0 0 10px color-mix(in srgb, ${color} 55%, transparent)`,
          transition: "width 0.6s ease",
        }}
      />
    </div>
  );
}
