"use client";

export function ScoreBar({
  score,
  label,
  size = "md",
}: {
  score: number;
  label?: string;
  size?: "sm" | "md";
}) {
  const color =
    score >= 75
      ? "var(--green)"
      : score >= 60
        ? "var(--green-bright)"
        : score >= 40
          ? "var(--amber)"
          : "var(--red)";

  const bgColor =
    score >= 75
      ? "var(--green-dim)"
      : score >= 60
        ? "rgba(77, 208, 200, 0.10)"
        : score >= 40
          ? "var(--amber-dim)"
          : "var(--red-dim)";

  const h = size === "sm" ? "h-[3px]" : "h-1";

  return (
    <div className="flex items-center gap-2">
      {label && (
        <span
          className="text-[10px] uppercase tracking-[0.08em] w-[72px] shrink-0"
          style={{ color: "var(--text-muted)", fontFamily: "var(--font-body)" }}
        >
          {label}
        </span>
      )}
      <div
        className={`flex-1 rounded-full ${h} overflow-hidden`}
        style={{ backgroundColor: bgColor }}
      >
        <div
          className={`${h} rounded-full score-bar-fill`}
          style={{ width: `${Math.min(100, score)}%`, backgroundColor: color }}
        />
      </div>
      <span
        className="text-[10px] w-6 text-right tabular-nums"
        style={{ color, fontFamily: "var(--font-mono)" }}
      >
        {score.toFixed(0)}
      </span>
    </div>
  );
}
