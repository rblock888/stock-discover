"use client";

const SOURCE_COLORS: Record<string, string> = {
  yahoo_gainers: "#7c3aed",
  yahoo_active: "#6366f1",
  yahoo_smallcap: "#8b5cf6",
  finviz: "#0ea5e9",
  reddit: "#f97316",
  sec_insiders: "#22c55e",
  rss_feeds: "#eab308",
};

const SOURCE_LABELS: Record<string, string> = {
  yahoo_gainers: "Yahoo Gainers",
  yahoo_active: "Yahoo Active",
  yahoo_smallcap: "Yahoo SmallCap",
  finviz: "Finviz",
  reddit: "Reddit",
  sec_insiders: "SEC Insiders",
  rss_feeds: "RSS Feeds",
};

export function SourceBadges({
  sources,
}: {
  sources: Record<string, string[]>;
}) {
  return (
    <div className="flex flex-wrap gap-2">
      {Object.entries(sources).map(([key, tickers]) => {
        const color = SOURCE_COLORS[key] || "var(--text-muted)";
        return (
          <span
            key={key}
            className="text-[11px] tracking-wide px-2.5 py-1 rounded-md flex items-center gap-1.5"
            style={{
              border: `1px solid ${color}33`,
              backgroundColor: `${color}11`,
              color,
            }}
          >
            <span
              className="w-1.5 h-1.5 rounded-full"
              style={{ backgroundColor: color }}
            />
            {SOURCE_LABELS[key] || key}
            <span className="font-mono font-bold">{tickers.length}</span>
          </span>
        );
      })}
    </div>
  );
}
