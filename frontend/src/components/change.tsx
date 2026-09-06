"use client";

// Change cards and evidence display.
//
// A score is never shown without the evidence that produced it. The breakdown
// is expandable rather than hidden, because "attention 87" with no explanation
// is exactly the anti-pattern this product exists to avoid.

import Link from "next/link";
import { useState } from "react";
import type { Change, Evidence } from "@/lib/types";
import {
  changeTypeLabel,
  directionClass,
  formatPct,
  reasonLabel,
  relativeTime,
} from "@/lib/format";
import { Button, Card, SeverityBadge, StatusBadge } from "./ui";

const EVIDENCE_ICON: Record<string, string> = {
  PRICE_MOVE: "◱",
  ABNORMALITY: "◇",
  BENCHMARK: "⇅",
  SECTOR: "⊞",
  VOLUME: "▤",
  NEWS: "✎",
  USER_CONTEXT: "◔",
  DATA_QUALITY: "⚑",
};

export function EvidenceList({ evidence }: { evidence: Evidence[] }) {
  if (!evidence.length) {
    return <p className="text-[13px] text-muted">No supporting evidence recorded.</p>;
  }
  return (
    <ul className="space-y-1.5">
      {evidence.map((item, i) => (
        <li key={`${item.evidence_type}-${i}`} className="flex gap-2.5 text-[13px] leading-relaxed">
          <span
            className={`mt-px shrink-0 ${
              item.evidence_type === "DATA_QUALITY" ? "text-medium" : "text-faint"
            }`}
            aria-hidden="true"
          >
            {EVIDENCE_ICON[item.evidence_type] ?? "·"}
          </span>
          <span className={item.evidence_type === "DATA_QUALITY" ? "text-medium" : "text-ink-2"}>
            {item.label}
            {item.source_ref && item.evidence_type === "NEWS" ? (
              <span className="ml-1.5 text-faint">— {item.source_ref}</span>
            ) : null}
          </span>
        </li>
      ))}
    </ul>
  );
}

/** Transparent score decomposition: every point is attributable. */
export function ScoreBreakdownBar({ change }: { change: Change }) {
  const b = change.breakdown;
  const parts = [
    { key: "Abnormal move", value: b.abnormality, max: 25 },
    { key: "vs benchmark", value: b.relative_move, max: 20 },
    { key: "Volume", value: b.volume, max: 15 },
    { key: "News", value: b.news, max: 25 },
    { key: "Your interest", value: b.user_adjustment, max: 15 },
  ];
  return (
    <div className="space-y-2">
      <p className="text-[12px] text-muted">
        Attention {change.attention_score.toFixed(0)} of 100 — {b.base_significance.toFixed(0)} from
        market signals
        {b.user_adjustment > 0
          ? `, +${b.user_adjustment.toFixed(0)} because you follow this closely (ranking only, never severity)`
          : ""}
        .
      </p>
      <dl className="space-y-1.5">
        {parts.map((p) => (
          <div key={p.key} className="flex items-center gap-3">
            <dt className="w-28 shrink-0 text-[12px] text-muted">{p.key}</dt>
            <dd className="flex flex-1 items-center gap-2">
              <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-2">
                <div
                  className="h-full rounded-full bg-accent"
                  style={{ width: `${Math.min(100, (p.value / p.max) * 100)}%` }}
                />
              </div>
              <span className="tnum w-12 text-right text-[12px] text-ink-2">
                {p.value.toFixed(1)}
                <span className="text-faint">/{p.max}</span>
              </span>
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

export function ChangeCard({
  change,
  onAcknowledge,
  busy = false,
  showLink = true,
}: {
  change: Change;
  onAcknowledge?: (id: string) => void;
  busy?: boolean;
  showLink?: boolean;
}) {
  const [showBreakdown, setShowBreakdown] = useState(false);
  const move = change.metrics.price_change_pct;
  const reviewed = change.status === "ACKNOWLEDGED" || change.status === "DISMISSED";

  return (
    <Card
      as="article"
      className={`p-4 ${reviewed ? "opacity-75" : ""}`}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            {showLink ? (
              <Link
                href={`/stocks/${change.symbol}`}
                className="text-[15px] font-semibold text-ink hover:text-accent hover:underline"
              >
                {change.symbol}
              </Link>
            ) : (
              <span className="text-[15px] font-semibold text-ink">{change.symbol}</span>
            )}
            <span className="truncate text-[13px] text-muted">{change.name}</span>
          </div>
          <p className="mt-1 text-[13px] text-ink-2">{change.headline}</p>
        </div>

        <div className="flex shrink-0 flex-col items-end gap-1.5">
          <span className={`tnum text-[17px] font-semibold ${directionClass(move)}`}>
            {formatPct(move)}
          </span>
          <SeverityBadge severity={change.severity} />
        </div>
      </div>

      <div className="mt-2.5 flex flex-wrap items-center gap-2 text-[11px]">
        <span className="rounded bg-surface-2 px-2 py-0.5 text-muted">
          {changeTypeLabel(change.change_type)}
        </span>
        <span className="text-faint">{reasonLabel(change.primary_reason)}</span>
        <StatusBadge status={change.status} />
        <span className="text-faint">since {relativeTime(change.since)}</span>
      </div>

      <div className="mt-3 border-t border-line pt-3">
        <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.07em] text-muted">
          Why it matters
        </p>
        <EvidenceList evidence={change.evidence.slice(0, 5)} />
      </div>

      {showBreakdown ? (
        <div className="mt-3 rounded-md bg-surface-2 p-3">
          <ScoreBreakdownBar change={change} />
        </div>
      ) : null}

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button
          size="sm"
          variant="ghost"
          onClick={() => setShowBreakdown((v) => !v)}
        >
          {showBreakdown ? "Hide score breakdown" : "How was this scored?"}
        </Button>
        {showLink ? (
          <Link
            href={`/stocks/${change.symbol}`}
            className="inline-flex items-center rounded-md px-2.5 py-1 text-xs font-medium text-muted hover:bg-surface-2 hover:text-ink"
          >
            Open {change.symbol}
          </Link>
        ) : null}
        {onAcknowledge && !reviewed ? (
          <Button
            size="sm"
            variant="secondary"
            disabled={busy}
            onClick={() => onAcknowledge(change.id)}
            className="ml-auto"
          >
            {busy ? "Saving…" : "Mark as reviewed"}
          </Button>
        ) : null}
        {reviewed ? (
          <span className="ml-auto text-[11px] text-reviewed">✓ Reviewed</span>
        ) : null}
      </div>
    </Card>
  );
}
