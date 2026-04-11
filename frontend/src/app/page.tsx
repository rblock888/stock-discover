"use client";

import { useState } from "react";
import {
  discover,
  scoreTickers,
  StockResult,
  UniverseResponse,
} from "@/lib/api";
import { StockTable } from "@/components/StockTable";
import { StockCard } from "@/components/StockCard";
import { SourceBadges } from "@/components/SourceBadges";

type ViewMode = "table" | "cards";

export default function Home() {
  const [mode, setMode] = useState<"auto" | "manual">("auto");
  const [viewMode, setViewMode] = useState<ViewMode>("table");
  const [manualTickers, setManualTickers] = useState(
    "LWLG, ASTS, RKLB, LUNR, IONQ"
  );
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState("");
  const [universe, setUniverse] = useState<UniverseResponse | null>(null);
  const [results, setResults] = useState<StockResult[]>([]);
  const [alerts, setAlerts] = useState<string[]>([]);
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [sources, setSources] = useState({
    use_yahoo: true,
    use_finviz: true,
    use_reddit: true,
    use_sec: true,
    use_rss: true,
  });

  async function runAutoDiscovery() {
    setLoading(true);
    setError(null);
    setResults([]);
    setAlerts([]);
    try {
      setStatus("Discovering tickers from multiple sources...");
      const uni = await discover(sources);
      setUniverse(uni);

      if (uni.tickers.length === 0) {
        setStatus("No tickers discovered.");
        setLoading(false);
        return;
      }

      setStatus(`Found ${uni.total} tickers. Scoring top candidates...`);
      const scoreRes = await scoreTickers(uni.tickers.slice(0, 30), false);
      setResults(scoreRes.ranked);
      setAlerts(scoreRes.alerts);
      setStatus(
        `Scored ${scoreRes.ranked.length} stocks. ${scoreRes.alerts.length} multi-signal alerts.`
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
      setStatus("");
    }
    setLoading(false);
  }

  async function runManualScan() {
    setLoading(true);
    setError(null);
    setResults([]);
    setAlerts([]);
    setUniverse(null);
    try {
      const tickers = manualTickers
        .split(/[,\s]+/)
        .map((t) => t.trim().toUpperCase())
        .filter(Boolean);

      if (tickers.length === 0) {
        setError("Enter at least one ticker.");
        setLoading(false);
        return;
      }

      setStatus(`Scoring ${tickers.length} tickers...`);
      const scoreRes = await scoreTickers(tickers, true);
      setResults(scoreRes.ranked);
      setAlerts(scoreRes.alerts);
      setStatus(
        `Scored ${scoreRes.ranked.length} stocks. ${scoreRes.alerts.length} multi-signal alerts.`
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
      setStatus("");
    }
    setLoading(false);
  }

  const selectedStock =
    selectedTicker && results.find((r) => r.ticker === selectedTicker);

  return (
    <div className="flex h-screen overflow-hidden">
      {/* Sidebar */}
      <aside
        className="w-72 shrink-0 flex flex-col overflow-y-auto"
        style={{
          backgroundColor: "var(--bg-surface)",
          borderRight: "1px solid var(--border)",
        }}
      >
        {/* Logo */}
        <div
          className="px-5 py-4"
          style={{ borderBottom: "1px solid var(--border)" }}
        >
          <h1 className="text-lg font-bold tracking-tight">Stock Discovery</h1>
          <p
            className="text-[11px] mt-0.5"
            style={{ color: "var(--text-muted)" }}
          >
            Multi-signal rerating scanner
          </p>
        </div>

        {/* Mode toggle */}
        <div
          className="px-4 py-3"
          style={{ borderBottom: "1px solid var(--border)" }}
        >
          <div
            className="flex rounded-md overflow-hidden text-xs"
            style={{ border: "1px solid var(--border)" }}
          >
            <button
              className="flex-1 px-3 py-1.5 transition-colors font-medium"
              style={{
                backgroundColor:
                  mode === "auto" ? "var(--accent-dim)" : "transparent",
                color:
                  mode === "auto" ? "var(--accent)" : "var(--text-secondary)",
              }}
              onClick={() => setMode("auto")}
            >
              Auto-Discovery
            </button>
            <button
              className="flex-1 px-3 py-1.5 transition-colors font-medium"
              style={{
                backgroundColor:
                  mode === "manual" ? "var(--accent-dim)" : "transparent",
                color:
                  mode === "manual"
                    ? "var(--accent)"
                    : "var(--text-secondary)",
                borderLeft: "1px solid var(--border)",
              }}
              onClick={() => setMode("manual")}
            >
              Manual
            </button>
          </div>
        </div>

        {/* Mode-specific controls */}
        <div
          className="px-4 py-3 flex-1"
          style={{ borderBottom: "1px solid var(--border)" }}
        >
          {mode === "auto" ? (
            <div className="space-y-2">
              <p
                className="text-[11px] uppercase tracking-[0.06em] font-medium mb-2"
                style={{ color: "var(--text-muted)" }}
              >
                Sources
              </p>
              {Object.entries(sources).map(([key, enabled]) => (
                <label
                  key={key}
                  className="flex items-center gap-2 text-xs cursor-pointer"
                  style={{ color: "var(--text-secondary)" }}
                >
                  <input
                    type="checkbox"
                    checked={enabled}
                    onChange={() =>
                      setSources((s) => ({
                        ...s,
                        [key]: !s[key as keyof typeof s],
                      }))
                    }
                    className="rounded"
                    style={{ accentColor: "var(--accent)" }}
                  />
                  {key
                    .replace("use_", "")
                    .replace("_", " ")
                    .replace(/\b\w/g, (c) => c.toUpperCase())}
                </label>
              ))}
            </div>
          ) : (
            <div className="space-y-2">
              <p
                className="text-[11px] uppercase tracking-[0.06em] font-medium mb-2"
                style={{ color: "var(--text-muted)" }}
              >
                Tickers
              </p>
              <textarea
                value={manualTickers}
                onChange={(e) => setManualTickers(e.target.value)}
                rows={4}
                className="w-full text-xs rounded-md px-3 py-2 resize-none focus:outline-none"
                style={{
                  backgroundColor: "var(--bg-primary)",
                  border: "1px solid var(--border)",
                  color: "var(--text-primary)",
                }}
                placeholder="LWLG, ASTS, RKLB..."
              />
            </div>
          )}
        </div>

        {/* Run button */}
        <div className="px-4 py-3">
          <button
            onClick={mode === "auto" ? runAutoDiscovery : runManualScan}
            disabled={loading}
            className="w-full py-2.5 rounded-md text-sm font-semibold transition-all duration-150 active:scale-[0.98]"
            style={{
              backgroundColor: loading
                ? "var(--bg-surface-hover)"
                : "var(--accent)",
              color: loading ? "var(--text-muted)" : "#fff",
              cursor: loading ? "not-allowed" : "pointer",
            }}
          >
            {loading ? (
              <span className="flex items-center justify-center gap-2">
                <span className="w-3 h-3 border-2 border-current border-t-transparent rounded-full animate-spin" />
                Processing...
              </span>
            ) : mode === "auto" ? (
              "Run Auto-Discovery"
            ) : (
              "Score Tickers"
            )}
          </button>
        </div>

        {/* Universe info */}
        {universe && (
          <div
            className="px-4 py-3"
            style={{ borderTop: "1px solid var(--border)" }}
          >
            <p
              className="text-[11px] uppercase tracking-[0.06em] font-medium mb-2"
              style={{ color: "var(--text-muted)" }}
            >
              Discovered {universe.total} tickers
            </p>
            <SourceBadges sources={universe.sources} />
          </div>
        )}
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-y-auto p-6">
        {/* Header bar */}
        {results.length > 0 && (
          <div className="flex items-center justify-between mb-4">
            <div>
              <h2 className="text-lg font-semibold tracking-tight">
                Results
                <span
                  className="text-sm font-normal ml-2"
                  style={{ color: "var(--text-secondary)" }}
                >
                  {results.length} stocks scored
                </span>
              </h2>
              {alerts.length > 0 && (
                <p
                  className="text-xs mt-1"
                  style={{ color: "var(--amber)" }}
                >
                  {alerts.length} multi-signal alert
                  {alerts.length > 1 ? "s" : ""}: {alerts.join(", ")}
                </p>
              )}
            </div>
            <div
              className="flex rounded-md overflow-hidden text-[11px]"
              style={{ border: "1px solid var(--border)" }}
            >
              <button
                className="px-3 py-1.5"
                style={{
                  backgroundColor:
                    viewMode === "table"
                      ? "var(--bg-surface-hover)"
                      : "transparent",
                  color:
                    viewMode === "table"
                      ? "var(--text-primary)"
                      : "var(--text-muted)",
                }}
                onClick={() => setViewMode("table")}
              >
                Table
              </button>
              <button
                className="px-3 py-1.5"
                style={{
                  backgroundColor:
                    viewMode === "cards"
                      ? "var(--bg-surface-hover)"
                      : "transparent",
                  color:
                    viewMode === "cards"
                      ? "var(--text-primary)"
                      : "var(--text-muted)",
                  borderLeft: "1px solid var(--border)",
                }}
                onClick={() => setViewMode("cards")}
              >
                Cards
              </button>
            </div>
          </div>
        )}

        {/* Error */}
        {error && (
          <div
            className="rounded-lg px-4 py-3 text-sm mb-4"
            style={{
              backgroundColor: "var(--red-dim)",
              color: "var(--red)",
              border: "1px solid var(--red)",
            }}
          >
            {error}
          </div>
        )}

        {/* Loading spinner */}
        {loading && !results.length && (
          <div className="flex flex-col items-center justify-center h-64 gap-4">
            <div
              className="w-8 h-8 border-2 border-t-transparent rounded-full animate-spin"
              style={{
                borderColor: "var(--accent)",
                borderTopColor: "transparent",
              }}
            />
            <p
              className="text-sm"
              style={{ color: "var(--text-secondary)" }}
            >
              {status}
            </p>
          </div>
        )}

        {/* Empty state */}
        {!loading && results.length === 0 && !error && (
          <div className="flex flex-col items-center justify-center h-96 gap-3">
            <div
              className="w-16 h-16 rounded-full flex items-center justify-center text-2xl"
              style={{ backgroundColor: "var(--bg-surface)" }}
            >
              📊
            </div>
            <h3 className="text-base font-medium">Ready to discover</h3>
            <p
              className="text-sm text-center max-w-md"
              style={{ color: "var(--text-secondary)" }}
            >
              {mode === "auto"
                ? "Click Run Auto-Discovery to scan Yahoo, Finviz, Reddit, SEC filings, and RSS feeds for candidates."
                : "Enter tickers and click Score to analyze them across 5 dimensions."}
            </p>
          </div>
        )}

        {/* Results */}
        {results.length > 0 && (
          <>
            {viewMode === "table" ? (
              <StockTable
                stocks={results}
                onSelect={setSelectedTicker}
              />
            ) : (
              <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-3">
                {results.map((stock) => (
                  <StockCard key={stock.ticker} stock={stock} />
                ))}
              </div>
            )}
          </>
        )}

        {/* Detail panel below table */}
        {selectedStock && viewMode === "table" && (
          <div className="mt-4">
            <StockCard stock={selectedStock as StockResult} />
          </div>
        )}

        {/* Status bar */}
        {status && !loading && results.length > 0 && (
          <p
            className="text-xs mt-4"
            style={{ color: "var(--text-muted)" }}
          >
            {status}
          </p>
        )}
      </main>
    </div>
  );
}
