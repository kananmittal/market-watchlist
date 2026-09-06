"use client";

// Change history: every detected change with its review state, filterable.
// An old event is not the same as a new one, and this is where that history lives.

import { useCallback, useEffect, useState } from "react";
import { ApiError, api } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import type { Change } from "@/lib/types";
import { ChangeCard } from "@/components/change";
import { Shell } from "@/components/shell";
import { EmptyState, ErrorState, SectionHeading, Skeleton } from "@/components/ui";

const STATUS_FILTERS = [
  { key: "all", label: "All", value: undefined },
  { key: "unreviewed", label: "Unreviewed", value: "NEW,IMPORTANT,VIEWED" },
  { key: "reviewed", label: "Reviewed", value: "ACKNOWLEDGED" },
  { key: "dismissed", label: "Dismissed", value: "DISMISSED" },
  { key: "stale", label: "Stale", value: "STALE" },
] as const;

const SEVERITY_FILTERS = [
  { key: "any", label: "Any severity", value: undefined },
  { key: "high", label: "High", value: "HIGH" },
  { key: "medium", label: "Medium", value: "MEDIUM" },
] as const;

export default function ChangesPage() {
  const { user } = useRequireAuth();
  const [changes, setChanges] = useState<Change[]>([]);
  const [status, setStatus] = useState<(typeof STATUS_FILTERS)[number]["key"]>("all");
  const [severity, setSeverity] = useState<(typeof SEVERITY_FILTERS)[number]["key"]>("any");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setError(null);
      setChanges(
        await api.changes({
          status: STATUS_FILTERS.find((f) => f.key === status)?.value,
          severity: SEVERITY_FILTERS.find((f) => f.key === severity)?.value,
        }),
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load your change history.");
    } finally {
      setLoading(false);
    }
  }, [status, severity]);

  useEffect(() => {
    if (user) load();
  }, [user, load]);

  async function acknowledge(id: string) {
    setBusyId(id);
    try {
      await api.acknowledgeChange(id);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save that.");
    } finally {
      setBusyId(null);
    }
  }

  const material = changes.filter((c) => c.change_type !== "NO_MATERIAL_CHANGE");

  return (
    <Shell>
      <h1 className="mb-1 text-[20px] font-semibold tracking-tight text-ink">Change history</h1>
      <p className="mb-5 text-[13px] text-muted">
        Everything the system has flagged, and whether you have reviewed it.
      </p>

      <div className="mb-5 flex flex-wrap gap-4">
        <div>
          <SectionHeading title="Review state" />
          <div className="flex flex-wrap gap-1.5">
            {STATUS_FILTERS.map((f) => (
              <button
                key={f.key}
                onClick={() => setStatus(f.key)}
                aria-pressed={status === f.key}
                className={`rounded-full border px-3 py-1 text-[12px] transition-colors ${
                  status === f.key
                    ? "border-line-strong bg-surface-2 font-medium text-ink"
                    : "border-line text-muted hover:text-ink"
                }`}
              >
                {f.label}
              </button>
            ))}
          </div>
        </div>
        <div>
          <SectionHeading title="Severity" />
          <div className="flex flex-wrap gap-1.5">
            {SEVERITY_FILTERS.map((f) => (
              <button
                key={f.key}
                onClick={() => setSeverity(f.key)}
                aria-pressed={severity === f.key}
                className={`rounded-full border px-3 py-1 text-[12px] transition-colors ${
                  severity === f.key
                    ? "border-line-strong bg-surface-2 font-medium text-ink"
                    : "border-line text-muted hover:text-ink"
                }`}
              >
                {f.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {error ? <ErrorState message={error} onRetry={load} /> : null}

      {loading ? (
        <div className="space-y-3">
          <Skeleton className="h-36 w-full" />
          <Skeleton className="h-36 w-full" />
        </div>
      ) : material.length === 0 ? (
        <EmptyState
          title="Nothing here yet"
          body="Changes appear once the system detects something meaningful in your watchlist."
        />
      ) : (
        <div className="space-y-3">
          {material.map((c) => (
            <ChangeCard
              key={c.id}
              change={c}
              onAcknowledge={acknowledge}
              busy={busyId === c.id}
            />
          ))}
        </div>
      )}
    </Shell>
  );
}
