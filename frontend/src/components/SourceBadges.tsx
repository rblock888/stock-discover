"use client";

const SOURCE_COLORS: Record<string, string> = {
  yahoo_gainers: "#2962ff",
  yahoo_active: "#2962ff",
  yahoo_smallcap: "#2962ff",
  finviz: "#26a69a",
  finviz_microcap: "#e11d48",
  reddit: "#ff6d00",
  sec_insiders: "#4dd0c8",
  rss_feeds: "#787b86",
  stocktwits: "#ff9800",
};

const SOURCE_LABELS: Record<string, string> = {
  yahoo_gainers: "Gainers",
  yahoo_active: "Active",
  yahoo_smallcap: "SmCap",
  finviz: "Finviz",
  finviz_microcap: "MicroCap",
  reddit: "Reddit",
  sec_insiders: "SEC",
  rss_feeds: "RSS",
  stocktwits: "StockTwits",
};

export function SourceBadges({ sources }: { sources: Record<string, string[]> }) {
  return (
    <div className="flex flex-wrap gap-1">
      {Object.entries(sources).map(([key, tickers]) => {
        const color = SOURCE_COLORS[key] || "var(--text-muted)";
        return (
          <span
            key={key}
            className="text-[9px] tracking-[0.06em] uppercase px-1.5 py-[2px] rounded flex items-center gap-1"
            style={{
              backgroundColor: `${color}14`,
              color,
              fontFamily: "var(--font-body)",
            }}
          >
            {SOURCE_LABELS[key] || key}
            <span style={{ fontFamily: "var(--font-mono)", fontWeight: 700 }}>{tickers.length}</span>
          </span>
        );
      })}
    </div>
  );
}
