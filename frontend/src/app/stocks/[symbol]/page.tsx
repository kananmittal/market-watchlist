"use client";

// Stock detail. Answers: what happened, is it unusual, is it company/sector/
// market driven, what evidence supports that, and have I reviewed it.

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { ApiError, api } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import type { StockDetail } from "@/lib/types";
import {
  activityLabel,
  changeTypeLabel,
  directionClass,
  eventTypeLabel,
  formatDateTime,
  formatMultiple,
  formatPct,
  formatPrice,
  formatVolume,
  reasonLabel,
  relativeTime,
} from "@/lib/format";
import { PriceChart } from "@/components/chart";
import { EvidenceList, ScoreBreakdownBar } from "@/components/change";
import { CopilotPanel } from "@/components/copilot";
import { Shell } from "@/components/shell";
import {
  Button,
  Card,
  ErrorState,
  FreshnessTag,
  SectionHeading,
  SeverityBadge,
  Skeleton,
  StatusBadge,
} from "@/components/ui";

const PERIODS = ["1mo", "3mo", "6mo", "1y"] as const;

export default function StockPage() {
  const { user, loading: authLoading } = useRequireAuth();
  const params = useParams<{ symbol: string }>();
  const symbol = (params?.symbol ?? "").toUpperCase();

  const [data, setData] = useState<StockDetail | null>(null);
  const [period, setPeriod] = useState<(typeof PERIODS)[number]>("3mo");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setError(null);
      setData(await api.stock(symbol, period));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : `Could not load ${symbol}.`);
    } finally {
      setLoading(false);
    }
  }, [symbol, period]);

  useEffect(() => {
    if (!user || !symbol) return;
    load();
  }, [user, symbol, load]);

  async function acknowledge() {
    setBusy(true);
    try {
      setData(await api.acknowledgeStock(symbol));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save that.");
    } finally {
      setBusy(false);
    }
  }

  if (authLoading || (loading && !data)) {
    return (
      <Shell>
        <Skeleton className="mb-4 h-32 w-full" />
        <Skeleton className="h-64 w-full" />
      </Shell>
    );
  }
  if (error && !data) {
    return (
      <Shell>
        <ErrorState message={error} onRetry={load} />
        <div className="mt-4">
          <Link href="/dashboard" className="text-[13px] text-accent hover:underline">
            ← Back to dashboard
          </Link>
        </div>
      </Shell>
    );
  }
  if (!data) return null;

  const change = data.change;
  const quote = data.quote;
  const move = change?.metrics.price_change_pct ?? quote?.change_pct ?? null;
  const reviewed = change?.status === "ACKNOWLEDGED" || change?.status === "DISMISSED";
  const material = change && change.change_type !== "NO_MATERIAL_CHANGE";

  return (
    <Shell demoMode={quote?.freshness?.is_synthetic ?? false}>
      <Link
        href="/dashboard"
        className="mb-4 inline-block text-[13px] text-muted hover:text-ink hover:underline"
      >
        ← Dashboard
      </Link>

      {/* ---- headline ---- */}
      <Card className="mb-6 p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="flex flex-wrap items-baseline gap-2.5">
              <h1 className="text-[24px] font-semibold tracking-tight text-ink">{data.symbol}</h1>
              <span className="text-[14px] text-muted">{data.name}</span>
              {data.sector ? (
                <span className="rounded bg-surface-2 px-2 py-0.5 text-[11px] text-muted">
                  {data.sector}
                </span>
              ) : null}
            </div>
            <div className="mt-2 flex flex-wrap items-baseline gap-3">
              <span className="tnum text-[28px] font-semibold text-ink">
                {formatPrice(quote?.price ?? null)}
              </span>
              <span className={`tnum text-[15px] font-medium ${directionClass(move)}`}>
                {formatPct(move)}
              </span>
              <span className="text-[13px] text-muted">
                {change?.metrics.price_change_pct != null
                  ? "since you last looked"
                  : "in the latest session"}
              </span>
            </div>
            <div className="mt-2">
              <FreshnessTag info={quote?.freshness} />
            </div>
          </div>

          <div className="flex flex-col items-end gap-2">
            {material ? <SeverityBadge severity={change.severity} /> : null}
            {change ? <StatusBadge status={change.status} /> : null}
            <Button
              variant={reviewed ? "ghost" : "primary"}
              size="sm"
              disabled={busy || reviewed}
              onClick={acknowledge}
            >
              {reviewed ? "✓ Reviewed" : busy ? "Saving…" : "Mark as reviewed"}
            </Button>
            <p className="max-w-[180px] text-right text-[11px] text-faint">
              Last viewed {data.last_viewed_at ? relativeTime(data.last_viewed_at) : "never"} ·
              Reviewed{" "}
              {data.last_acknowledged_at ? relativeTime(data.last_acknowledged_at) : "never"}
            </p>
          </div>
        </div>
      </Card>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="min-w-0 space-y-6">
          {/* ---- why it matters ---- */}
          {change ? (
            <section aria-labelledby="why-heading">
              <SectionHeading
                title="Why it matters"
                hint={material ? changeTypeLabel(change.change_type) : "No material change"}
              />
              <h2 id="why-heading" className="sr-only">
                Why this matters
              </h2>
              <Card className="p-5">
                <p className="mb-3 text-[14px] text-ink">{change.headline}</p>
                <EvidenceList evidence={change.evidence} />

                {material ? (
                  <>
                    <div className="mt-4 grid grid-cols-2 gap-x-6 gap-y-3 border-t border-line pt-4 sm:grid-cols-4">
                      <Metric
                        label="Normal daily move"
                        value={
                          change.metrics.expected_daily_move_pct != null
                            ? `±${change.metrics.expected_daily_move_pct.toFixed(2)}%`
                            : "—"
                        }
                      />
                      <Metric
                        label="This move"
                        value={formatMultiple(change.metrics.normalized_move)}
                        hint="vs a normal day"
                      />
                      <Metric
                        label="vs NIFTY 50"
                        value={formatPct(change.metrics.relative_to_benchmark_pct)}
                      />
                      <Metric
                        label="Volume"
                        value={formatMultiple(change.metrics.volume_multiple)}
                        hint="vs average"
                      />
                    </div>
                    <div className="mt-4 rounded-md bg-surface-2 p-3.5">
                      <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.07em] text-muted">
                        Primary driver: {reasonLabel(change.primary_reason)}
                      </p>
                      <ScoreBreakdownBar change={change} />
                    </div>
                  </>
                ) : null}
              </Card>
            </section>
          ) : null}

          {/* ---- chart ---- */}
          <section aria-labelledby="chart-heading">
            <SectionHeading
              title="Price history"
              action={
                <div className="flex gap-1">
                  {PERIODS.map((p) => (
                    <button
                      key={p}
                      onClick={() => setPeriod(p)}
                      aria-pressed={period === p}
                      className={`rounded px-2 py-1 text-[11px] ${
                        period === p
                          ? "bg-surface-2 font-medium text-ink"
                          : "text-muted hover:text-ink"
                      }`}
                    >
                      {p}
                    </button>
                  ))}
                </div>
              }
            />
            <h2 id="chart-heading" className="sr-only">
              Price history
            </h2>
            <Card className="p-4">
              <PriceChart
                bars={data.history?.bars ?? []}
                baselineLabel={data.history?.is_synthetic ? "Demo data" : undefined}
              />
              <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-2 border-t border-line pt-3 sm:grid-cols-4">
                <Metric label="Open" value={formatPrice(quote?.open ?? null)} />
                <Metric label="High" value={formatPrice(quote?.high ?? null)} />
                <Metric label="Low" value={formatPrice(quote?.low ?? null)} />
                <Metric label="Volume" value={formatVolume(quote?.volume ?? null)} />
              </dl>
            </Card>
          </section>

          {/* ---- benchmark comparison ---- */}
          {data.benchmark || data.sector_index ? (
            <section aria-labelledby="bench-heading">
              <SectionHeading title="Compared with" />
              <h2 id="bench-heading" className="sr-only">
                Benchmark comparison
              </h2>
              <Card className="divide-y divide-line">
                <CompareRow label={data.symbol} value={move} emphasis />
                {data.benchmark ? (
                  <CompareRow label="NIFTY 50" value={data.benchmark.change_pct} />
                ) : null}
                {data.sector_index ? (
                  <CompareRow
                    label={data.sector_index.name}
                    value={data.sector_index.change_pct}
                  />
                ) : null}
              </Card>
            </section>
          ) : null}

          {/* ---- news ---- */}
          <section aria-labelledby="news-heading">
            <SectionHeading
              title="News and events"
              hint={data.news.length ? `${data.news.length} distinct events` : undefined}
            />
            <h2 id="news-heading" className="sr-only">
              News and events
            </h2>
            {data.news.length === 0 ? (
              <Card className="p-5">
                <p className="text-[13px] text-muted">
                  No recent events detected for {data.symbol}. Attention is based on market
                  signals alone.
                </p>
              </Card>
            ) : (
              <Card className="divide-y divide-line">
                {data.news.map((n) => (
                  <article key={n.event_id} className="p-4">
                    <div className="flex flex-wrap items-center gap-2 text-[11px]">
                      <span className="rounded bg-surface-2 px-2 py-0.5 text-muted">
                        {eventTypeLabel(n.event_type)}
                      </span>
                      <span className="text-faint">{n.source}</span>
                      <span className="text-faint">{formatDateTime(n.published_at)}</span>
                      {n.article_count > 1 ? (
                        <span className="text-faint">
                          · {n.article_count} articles merged
                        </span>
                      ) : null}
                    </div>
                    <p className="mt-1.5 text-[13px] leading-relaxed text-ink-2">
                      {n.source_url ? (
                        <a
                          href={n.source_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="hover:text-accent hover:underline"
                        >
                          {n.headline}
                        </a>
                      ) : (
                        n.headline
                      )}
                    </p>
                  </article>
                ))}
              </Card>
            )}
          </section>

          {/* ---- activity ---- */}
          <section aria-labelledby="activity-heading">
            <SectionHeading title="Your activity" />
            <h2 id="activity-heading" className="sr-only">
              Your activity on this stock
            </h2>
            <Card className="p-4">
              {data.activity.length === 0 ? (
                <p className="text-[13px] text-muted">No activity recorded yet.</p>
              ) : (
                <ol className="space-y-2">
                  {data.activity.slice(0, 12).map((a, i) => (
                    <li key={i} className="flex items-baseline justify-between gap-4 text-[13px]">
                      <span className="text-ink-2">{activityLabel(a.event_type)}</span>
                      <span className="shrink-0 text-[12px] text-faint">
                        {relativeTime(a.created_at)}
                      </span>
                    </li>
                  ))}
                </ol>
              )}
            </Card>
          </section>
        </div>

        <aside className="space-y-4 lg:sticky lg:top-20 lg:self-start">
          <CopilotPanel symbol={data.symbol} compact />
          {error ? <ErrorState message={error} onRetry={load} /> : null}
        </aside>
      </div>
    </Shell>
  );
}

function Metric({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div>
      <dt className="text-[11px] uppercase tracking-[0.05em] text-muted">{label}</dt>
      <dd className="tnum mt-0.5 text-[14px] font-medium text-ink">
        {value}
        {hint ? <span className="ml-1 text-[11px] font-normal text-faint">{hint}</span> : null}
      </dd>
    </div>
  );
}

function CompareRow({
  label,
  value,
  emphasis = false,
}: {
  label: string;
  value: number | null | undefined;
  emphasis?: boolean;
}) {
  const magnitude = Math.min(Math.abs(value ?? 0) * 12, 100);
  return (
    <div className="flex items-center gap-4 px-4 py-3">
      <span className={`w-32 shrink-0 text-[13px] ${emphasis ? "font-medium text-ink" : "text-muted"}`}>
        {label}
      </span>
      <div className="flex flex-1 items-center gap-2">
        <div className="relative h-1.5 flex-1 rounded-full bg-surface-2">
          <div
            className={`absolute top-0 h-full rounded-full ${
              (value ?? 0) >= 0 ? "left-1/2 bg-up" : "right-1/2 bg-down"
            }`}
            style={{ width: `${magnitude / 2}%` }}
          />
          <div className="absolute left-1/2 top-[-3px] h-3 w-px bg-line-strong" aria-hidden="true" />
        </div>
        <span className={`tnum w-16 text-right text-[13px] font-medium ${directionClass(value)}`}>
          {formatPct(value)}
        </span>
      </div>
    </div>
  );
}
