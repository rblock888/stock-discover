"use client";

import { useState } from "react";

export function TickerLogo({ ticker, size = 32 }: { ticker: string; size?: number }) {
  const [error, setError] = useState(false);

  if (error) {
    // Fallback: first letter badge
    return (
      <div
        className="flex items-center justify-center rounded font-bold shrink-0"
        style={{
          width: size,
          height: size,
          backgroundColor: "var(--bg-elevated)",
          color: "var(--text-secondary)",
          fontSize: size * 0.42,
        }}
      >
        {ticker[0]}
      </div>
    );
  }

  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={`https://financialmodelingprep.com/image-stock/${ticker}.png`}
      alt={ticker}
      width={size}
      height={size}
      onError={() => setError(true)}
      className="rounded shrink-0"
      style={{
        backgroundColor: "var(--bg-elevated)",
        objectFit: "contain",
        padding: 2,
      }}
    />
  );
}
