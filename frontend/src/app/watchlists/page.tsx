"use client";

// Watchlist management: create, rename, delete, search, add, remove, reorder.

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import type { SymbolSearchResult, Watchlist } from "@/lib/types";
import { Shell } from "@/components/shell";
import {
  Button,
  Card,
  EmptyState,
  ErrorState,
  SectionHeading,
  Skeleton,
} from "@/components/ui";

export default function WatchlistsPage() {
  const { user, loading: authLoading } = useRequireAuth();
  const [lists, setLists] = useState<Watchlist[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [newName, setNewName] = useState("");
  const [renaming, setRenaming] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [busy, setBusy] = useState(false);

  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SymbolSearchResult[]>([]);
  const debounce = useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = useCallback(async () => {
    try {
      setError(null);
      const data = await api.listWatchlists();
      setLists(data);
      setActiveId((cur) => cur ?? data[0]?.id ?? null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load your watchlists.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (user) load();
  }, [user, load]);

  // Debounced search: one request per pause, not per keystroke.
  useEffect(() => {
    if (debounce.current) clearTimeout(debounce.current);
    if (!query.trim()) {
      setResults([]);
      return;
    }
    debounce.current = setTimeout(async () => {
      try {
        setResults(await api.search(query));
      } catch {
        setResults([]);
      }
    }, 250);
    return () => {
      if (debounce.current) clearTimeout(debounce.current);
    };
  }, [query]);

  const active = lists.find((l) => l.id === activeId) ?? null;

  async function run(fn: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "That did not work.");
    } finally {
      setBusy(false);
    }
  }

  if (authLoading || (loading && !lists.length)) {
    return (
      <Shell>
        <Skeleton className="h-64 w-full" />
      </Shell>
    );
  }

  return (
    <Shell>
      <h1 className="mb-1 text-[20px] font-semibold tracking-tight text-ink">Watchlists</h1>
      <p className="mb-6 text-[13px] text-muted">
        Add the stocks you care about. The dashboard measures change from the moment you added
        each one, or from the last time you opened it.
      </p>

      {error ? (
        <div className="mb-4">
          <ErrorState message={error} onRetry={load} />
        </div>
      ) : null}

      <div className="grid gap-6 md:grid-cols-[240px_minmax(0,1fr)]">
        {/* ---- list of watchlists ---- */}
        <div>
          <SectionHeading title="Your lists" />
          <div className="space-y-1.5">
            {lists.map((list) => (
              <button
                key={list.id}
                onClick={() => setActiveId(list.id)}
                aria-current={list.id === activeId ? "true" : undefined}
                className={`flex w-full items-center justify-between rounded-md border px-3 py-2 text-left text-[13px] transition-colors ${
                  list.id === activeId
                    ? "border-line-strong bg-surface-2 font-medium text-ink"
                    : "border-line bg-surface text-muted hover:text-ink"
                }`}
              >
                <span className="truncate">{list.name}</span>
                <span className="tnum ml-2 shrink-0 text-[11px] text-faint">
                  {list.items.length}
                </span>
              </button>
            ))}
          </div>

          <form
            className="mt-3 flex gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (!newName.trim()) return;
              run(async () => {
                await api.createWatchlist(newName.trim());
                setNewName("");
              });
            }}
          >
            <label htmlFor="new-list" className="sr-only">
              New watchlist name
            </label>
            <input
              id="new-list"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="New list…"
              className="min-w-0 flex-1 rounded-md border border-line bg-surface px-2.5 py-1.5 text-[13px] text-ink placeholder:text-faint"
            />
            <Button type="submit" size="sm" disabled={busy || !newName.trim()}>
              Add
            </Button>
          </form>
        </div>

        {/* ---- active watchlist ---- */}
        <div className="min-w-0">
          {!active ? (
            <EmptyState
              title="No watchlists yet"
              body="Create your first list to start tracking what changes while you are away."
            />
          ) : (
            <>
              <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                {renaming === active.id ? (
                  <form
                    className="flex gap-2"
                    onSubmit={(e) => {
                      e.preventDefault();
                      run(async () => {
                        await api.renameWatchlist(active.id, renameValue.trim());
                        setRenaming(null);
                      });
                    }}
                  >
                    <input
                      value={renameValue}
                      onChange={(e) => setRenameValue(e.target.value)}
                      autoFocus
                      aria-label="Watchlist name"
                      className="rounded-md border border-line bg-surface px-2.5 py-1.5 text-[14px] text-ink"
                    />
                    <Button type="submit" size="sm" disabled={busy}>
                      Save
                    </Button>
                    <Button variant="ghost" size="sm" onClick={() => setRenaming(null)}>
                      Cancel
                    </Button>
                  </form>
                ) : (
                  <h2 className="text-[16px] font-semibold text-ink">{active.name}</h2>
                )}

                <div className="flex gap-1.5">
                  {renaming !== active.id ? (
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => {
                        setRenaming(active.id);
                        setRenameValue(active.name);
                      }}
                    >
                      Rename
                    </Button>
                  ) : null}
                  <Button
                    variant="danger"
                    size="sm"
                    disabled={busy}
                    onClick={() => {
                      if (!confirm(`Delete "${active.name}"? This cannot be undone.`)) return;
                      run(async () => {
                        await api.deleteWatchlist(active.id);
                        setActiveId(null);
                      });
                    }}
                  >
                    Delete
                  </Button>
                </div>
              </div>

              {/* ---- add symbol ---- */}
              <Card className="mb-4 p-4">
                <label htmlFor="sym-search" className="mb-1.5 block text-[12px] font-medium text-ink-2">
                  Add a stock
                </label>
                <input
                  id="sym-search"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Search by symbol or company name…"
                  autoComplete="off"
                  className="w-full rounded-md border border-line bg-surface px-3 py-2 text-[13px] text-ink placeholder:text-faint"
                />
                {results.length > 0 ? (
                  <ul className="mt-2 max-h-56 divide-y divide-line overflow-y-auto rounded-md border border-line">
                    {results.map((r) => {
                      const already = active.items.some((i) => i.symbol === r.symbol);
                      return (
                        <li
                          key={r.symbol}
                          className="flex items-center justify-between gap-3 px-3 py-2"
                        >
                          <span className="min-w-0">
                            <span className="text-[13px] font-medium text-ink">{r.symbol}</span>
                            <span className="ml-2 truncate text-[12px] text-muted">{r.name}</span>
                          </span>
                          <Button
                            size="sm"
                            variant={already ? "ghost" : "secondary"}
                            disabled={busy || already}
                            onClick={() =>
                              run(async () => {
                                await api.addSymbol(active.id, r.symbol);
                                setQuery("");
                                setResults([]);
                              })
                            }
                          >
                            {already ? "Added" : "Add"}
                          </Button>
                        </li>
                      );
                    })}
                  </ul>
                ) : query.trim() ? (
                  <p className="mt-2 text-[12px] text-muted">No matches for “{query}”.</p>
                ) : null}
              </Card>

              {/* ---- symbols ---- */}
              {active.items.length === 0 ? (
                <EmptyState
                  title="No stocks in this list"
                  body="Search above to add your first stock."
                />
              ) : (
                <Card className="divide-y divide-line">
                  {active.items.map((item, index) => (
                    <div key={item.symbol} className="flex items-center gap-3 px-4 py-2.5">
                      <div className="flex flex-col gap-0.5">
                        <button
                          aria-label={`Move ${item.symbol} up`}
                          disabled={index === 0 || busy}
                          onClick={() =>
                            run(() => {
                              const order = active.items.map((i) => i.symbol);
                              [order[index - 1], order[index]] = [order[index], order[index - 1]];
                              return api.reorder(active.id, order);
                            })
                          }
                          className="text-[10px] leading-none text-faint hover:text-ink disabled:opacity-30"
                        >
                          ▲
                        </button>
                        <button
                          aria-label={`Move ${item.symbol} down`}
                          disabled={index === active.items.length - 1 || busy}
                          onClick={() =>
                            run(() => {
                              const order = active.items.map((i) => i.symbol);
                              [order[index], order[index + 1]] = [order[index + 1], order[index]];
                              return api.reorder(active.id, order);
                            })
                          }
                          className="text-[10px] leading-none text-faint hover:text-ink disabled:opacity-30"
                        >
                          ▼
                        </button>
                      </div>
                      <Link href={`/stocks/${item.symbol}`} className="min-w-0 flex-1">
                        <span className="text-[13px] font-medium text-ink hover:text-accent">
                          {item.symbol}
                        </span>
                        <span className="ml-2 truncate text-[12px] text-muted">
                          {item.display_name}
                        </span>
                      </Link>
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={busy}
                        onClick={() => run(() => api.removeSymbol(active.id, item.symbol))}
                      >
                        Remove
                      </Button>
                    </div>
                  ))}
                </Card>
              )}
            </>
          )}
        </div>
      </div>
    </Shell>
  );
}
