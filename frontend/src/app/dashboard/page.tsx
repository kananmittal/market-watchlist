"use client";

// The hero screen. It must answer, in this order:
//   1. When did I last look?  2. What changed?  3. Which changes matter?
//   4. Why do they matter?    5. Have I already reviewed them?
// Charts and metrics deliberately come after that.

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { ApiError, api } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import type { Dashboard } from "@/lib/types";
import {
  directionClass,
  formatPct,
  formatPrice,
  relativeTime,
} from "@/lib/format";
import { ChangeCard } from "@/components/change";
import { CopilotPanel } from "@/components/copilot";
import { Shell } from "@/components/shell";
import {
  Button,
  Card,
  EmptyState,
  ErrorState,
  FreshnessTag,
  SectionHeading,
  SeverityBadge,
  Skeleton,
  StatusBadge,
} from "@/components/ui";

export default function DashboardPage() {
  const { user, loading: authLoading } = useRequireAuth();
  const [data, setData] = useState<Dashboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);

  // The first load advances the "last looked" anchor exactly once. Later
  // refreshes must not, or the app would forget where the user left off.
  const load = useCallback(async (advance: boolean) => {
    try {
      setError(null);
      setData(await api.dashboard({ advanceAnchor: advance }));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load your dashboard.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!user) return;
    load(true);
  }, [user, load]);

  async function acknowledge(id: string) {
    setBusyId(id);
    try {
      await api.acknowledgeChange(id);
      await load(false);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save that.");
    } finally {
      setBusyId(null);
    }
  }

  if (authLoading || (loading && !data)) {
    return (
      <Shell>
        <div className="space-y-4">
          <Skeleton className="h-28 w-full" />
          <Skeleton className="h-40 w-full" />
          <Skeleton className="h-40 w-full" />
        </div>
      </Shell>
    );
  }

  if (error && !data) {
    return (
      <Shell>
        <ErrorState message={error} onRetry={() => load(false)} />
      </Shell>
    );
  }
  if (!data) return null;

  const { catch_up: catchUp } = data;
  const hasWatchlist = data.watchlist.length > 0;
  const visible = showAll
    ? [...data.meaningful_changes, ...data.normal_movements]
    : data.meaningful_changes;

  return (
    <Shell market={data.market} lastChecked={data.last_checked_at} demoMode={data.demo_mode}>
      {/* ---- 1 & 2: when did I last look, and what changed ---- */}
      <section aria-labelledby="catchup-heading" className="mb-7">
        <Card className="p-5">
          <p className="text-[12px] text-muted">
            {data.is_first_visit
              ? "Welcome"
              : `Last checked ${relativeTime(data.last_checked_at)}`}
          </p>
          <h1
            id="catchup-heading"
            className="mt-1.5 text-[21px] font-semibold leading-snug tracking-tight text-ink sm:text-[24px]"
          >
            {catchUp.headline}
          </h1>

          {hasWatchlist ? (
            <div className="mt-4 flex flex-wrap items-center gap-x-6 gap-y-2 text-[13px]">
              <span className="text-ink-2">
                <strong className="tnum font-semibold text-high">{catchUp.high_count}</strong> high
                attention
              </span>
              <span className="text-ink-2">
                <strong className="tnum font-semibold text-medium">{catchUp.medium_count}</strong>{" "}
                medium
              </span>
              <span className="text-ink-2">
                <strong className="tnum font-semibold">{catchUp.normal_count}</strong> normal
              </span>
              <span className="text-muted">
                <strong className="tnum font-semibold">{catchUp.unreviewed_count}</strong> awaiting
                review
              </span>
              {data.benchmark ? (
                <span className="ml-auto flex items-center gap-2 text-muted">
                  NIFTY 50
                  <span className={`tnum font-medium ${directionClass(data.benchmark.change_pct)}`}>
                    {formatPct(data.benchmark.change_pct)}
                  </span>
                </span>
              ) : null}
            </div>
          ) : null}
        </Card>
      </section>

      {!hasWatchlist ? (
        <EmptyState
          title="Your watchlist is empty"
          body="Add a few stocks and the next time you come back, this page will tell you exactly what changed while you were away."
          action={
            <Link href="/watchlists">
              <Button>Set up a watchlist</Button>
            </Link>
          }
        />
      ) : (
        <div className="grid gap-7 lg:grid-cols-[minmax(0,1fr)_320px]">
          <div className="min-w-0 space-y-7">
            {/* ---- 3, 4 & 5: which matter, why, and have I reviewed them ---- */}
            <section aria-labelledby="changes-heading">
              <SectionHeading
                title={showAll ? "All movements" : "Meaningful changes"}
                hint={
                  data.meaningful_changes.length
                    ? `${data.meaningful_changes.length} ranked by attention`
                    : undefined
                }
                action={
                  data.normal_movements.length ? (
                    <Button variant="ghost" size="sm" onClick={() => setShowAll((v) => !v)}>
                      {showAll
                        ? "Show only meaningful"
                        : `Show ${data.normal_movements.length} normal`}
                    </Button>
                  ) : null
                }
              />
              <h2 id="changes-heading" className="sr-only">
                Changes since you last looked
              </h2>

              {visible.length === 0 ? (
                <EmptyState
                  title="Nothing material changed"
                  body="Your watchlist moved within its normal range since you last looked. That is a result too."
                />
              ) : (
                <div className="space-y-3">
                  {visible.map((change) => (
                    <ChangeCard
                      key={change.id}
                      change={change}
                      onAcknowledge={change.change_type === "NO_MATERIAL_CHANGE" ? undefined : acknowledge}
                      busy={busyId === change.id}
                    />
                  ))}
                </div>
              )}
            </section>

            {/* ---- watchlist table ---- */}
            <section aria-labelledby="watchlist-heading">
              <SectionHeading
                title="Watchlist"
                action={
                  <Link
                    href="/watchlists"
                    className="text-xs text-muted hover:text-ink hover:underline"
                  >
                    Manage
                  </Link>
                }
              />
              <h2 id="watchlist-heading" className="sr-only">
                Your watchlist
              </h2>
              <Card className="overflow-hidden">
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[620px] text-[13px]">
                    <caption className="sr-only">
                      Watchlist with price, change since you last looked, attention and review state
                    </caption>
                    <thead>
                      <tr className="border-b border-line text-left text-[11px] uppercase tracking-[0.06em] text-muted">
                        <th scope="col" className="px-4 py-2.5 font-medium">Stock</th>
                        <th scope="col" className="px-4 py-2.5 text-right font-medium">Price</th>
                        <th scope="col" className="px-4 py-2.5 text-right font-medium">Change</th>
                        <th scope="col" className="px-4 py-2.5 font-medium">Attention</th>
                        <th scope="col" className="px-4 py-2.5 font-medium">Last viewed</th>
                        <th scope="col" className="px-4 py-2.5 font-medium">Review</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.watchlist.map((row) => (
                        <tr
                          key={row.symbol}
                          className="border-b border-line last:border-0 hover:bg-surface-2"
                        >
                          <td className="px-4 py-3">
                            <Link href={`/stocks/${row.symbol}`} className="block">
                              <span className="font-medium text-ink hover:text-accent">
                                {row.symbol}
                              </span>
                              <span className="block truncate text-[12px] text-muted">
                                {row.name}
                              </span>
                            </Link>
                          </td>
                          <td className="px-4 py-3 text-right">
                            <span className="tnum text-ink">
                              {formatPrice(row.quote?.price ?? null)}
                            </span>
                            <span className="block">
                              <FreshnessTag info={row.quote?.freshness} />
                            </span>
                          </td>
                          <td
                            className={`tnum px-4 py-3 text-right font-medium ${directionClass(
                              row.change?.metrics.price_change_pct ?? row.quote?.change_pct,
                            )}`}
                          >
                            {formatPct(
                              row.change?.metrics.price_change_pct ?? row.quote?.change_pct,
                            )}
                          </td>
                          <td className="px-4 py-3">
                            {row.change && row.change.change_type !== "NO_MATERIAL_CHANGE" ? (
                              <SeverityBadge severity={row.change.severity} compact />
                            ) : (
                              <span className="text-[12px] text-faint">—</span>
                            )}
                          </td>
                          <td className="px-4 py-3 text-[12px] text-muted">
                            {row.last_viewed_at ? relativeTime(row.last_viewed_at) : "Never"}
                          </td>
                          <td className="px-4 py-3">
                            {row.change && row.change.change_type !== "NO_MATERIAL_CHANGE" ? (
                              <StatusBadge status={row.change.status} />
                            ) : (
                              <span className="text-[12px] text-faint">—</span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Card>
            </section>
          </div>

          {/* ---- copilot: an explanation layer, placed last ---- */}
          <aside className="space-y-4 lg:sticky lg:top-20 lg:self-start">
            <CopilotPanel compact />
            {error ? <ErrorState message={error} onRetry={() => load(false)} /> : null}
          </aside>
        </div>
      )}
    </Shell>
  );
}
