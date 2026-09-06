"use client";

// Inline SVG sparkline/price chart. No charting library: this keeps the bundle
// small and the render deterministic, and the shape is all the page needs.

import { useMemo } from "react";
import type { HistoryBar } from "@/lib/types";
import { formatDate, formatPrice } from "@/lib/format";

export function PriceChart({
  bars,
  height = 200,
  baselineLabel,
}: {
  bars: HistoryBar[];
  height?: number;
  baselineLabel?: string;
}) {
  const model = useMemo(() => {
    if (bars.length < 2) return null;
    const closes = bars.map((b) => b.close);
    const min = Math.min(...closes);
    const max = Math.max(...closes);
    const span = max - min || 1;
    const width = 1000;
    const pad = 6;
    const points = closes.map((c, i) => {
      const x = (i / (closes.length - 1)) * width;
      const y = pad + (1 - (c - min) / span) * (height - pad * 2);
      return [x, y] as const;
    });
    const line = points.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
    const area = `${line} L${width} ${height} L0 ${height} Z`;
    const rising = closes[closes.length - 1] >= closes[0];
    return { line, area, min, max, rising, width, first: bars[0], last: bars[bars.length - 1] };
  }, [bars, height]);

  if (!model) {
    return (
      <div
        className="flex items-center justify-center rounded-md border border-dashed border-line text-[13px] text-muted"
        style={{ height }}
      >
        Not enough history to draw a chart
      </div>
    );
  }

  const stroke = model.rising ? "var(--color-up)" : "var(--color-down)";

  return (
    <figure className="m-0">
      <svg
        viewBox={`0 0 ${model.width} ${height}`}
        preserveAspectRatio="none"
        className="w-full"
        style={{ height }}
        role="img"
        aria-label={`Price from ${formatPrice(model.first.close)} on ${formatDate(
          model.first.timestamp,
        )} to ${formatPrice(model.last.close)} on ${formatDate(model.last.timestamp)}`}
      >
        <defs>
          <linearGradient id="mw-area" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={stroke} stopOpacity="0.14" />
            <stop offset="100%" stopColor={stroke} stopOpacity="0" />
          </linearGradient>
        </defs>
        <path d={model.area} fill="url(#mw-area)" />
        <path
          d={model.line}
          fill="none"
          stroke={stroke}
          strokeWidth="2"
          vectorEffect="non-scaling-stroke"
          strokeLinejoin="round"
        />
      </svg>
      <figcaption className="mt-1.5 flex justify-between text-[11px] text-faint">
        <span>{formatDate(model.first.timestamp)}</span>
        <span>
          {baselineLabel ? `${baselineLabel} · ` : ""}
          Range {formatPrice(model.min)} – {formatPrice(model.max)}
        </span>
        <span>{formatDate(model.last.timestamp)}</span>
      </figcaption>
    </figure>
  );
}
