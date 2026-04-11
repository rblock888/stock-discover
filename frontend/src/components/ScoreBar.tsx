"use client";

export function ScoreBar({
  score,
  label,
  size = "md",
}: {
  score: number;
  label?: string;
  size?: "sm" | "md" | "lg";
}) {
  const color =
    score >= 75
      ? "var(--green)"
      : score >= 60
        ? "#4ade80"
        : score >= 40
          ? "var(--amber)"
          : "var(--red)";

  const bgColor =
    score >= 75
      ? "var(--green-dim)"
      : score >= 60
        ? "rgba(74, 222, 128, 0.12)"
        : score >= 40
          ? "var(--amber-dim)"
          : "var(--red-dim)";

  const heights = { sm: "h-1.5", md: "h-2", lg: "h-3" };

  return (
    <div className="flex items-center gap-2">
      {label && (
        <span className="text-[11px] uppercase tracking-[0.06em] w-24 shrink-0"
              style={{ color: "var(--text-secondary)" }}>
          {label}
        </span>
      )}
      <div
        className={`flex-1 rounded-full ${heights[size]} overflow-hidden`}
        style={{ backgroundColor: bgColor }}
      >
        <div
          className={`${heights[size]} rounded-full score-bar-fill`}
          style={{ width: `${Math.min(100, score)}%`, backgroundColor: color }}
        />
      </div>
      <span
        className="text-xs font-mono w-8 text-right tabular-nums"
        style={{ color }}
      >
        {score.toFixed(0)}
      </span>
    </div>
  );
}
