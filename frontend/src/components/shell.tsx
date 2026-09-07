"use client";

// Application shell: identity, market status, last-checked time, navigation.

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { useAuth } from "@/lib/auth";
import type { MarketStatus } from "@/lib/types";
import { relativeTime } from "@/lib/format";
import { GrowwLogo } from "./logo";
import { DemoBanner } from "./ui";

const NAV = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/watchlists", label: "Watchlists" },
  { href: "/changes", label: "Change history" },
];

function MarketPill({ market }: { market?: MarketStatus | null }) {
  if (!market) return null;
  const open = market.status === "OPEN";
  const preOpen = market.status === "PRE_OPEN";
  const dot = open ? "bg-up" : preOpen ? "bg-medium" : "bg-faint";
  return (
    <span className="inline-flex items-center gap-1.5 text-[12px] text-muted">
      <span className={`h-1.5 w-1.5 rounded-full ${dot}`} aria-hidden="true" />
      <span className="hidden sm:inline">{market.label}</span>
      <span className="sm:hidden">{open ? "Open" : "Closed"}</span>
    </span>
  );
}

export function Shell({
  children,
  market,
  lastChecked,
  demoMode = false,
}: {
  children: ReactNode;
  market?: MarketStatus | null;
  lastChecked?: string | null;
  demoMode?: boolean;
}) {
  const { user, logout } = useAuth();
  const pathname = usePathname();

  return (
    <div className="min-h-dvh bg-canvas">
      {demoMode ? <DemoBanner /> : null}
      <header className="sticky top-0 z-20 border-b border-line bg-canvas/95 backdrop-blur">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3">
          <Link href="/dashboard" className="flex items-center gap-2.5">
            <GrowwLogo size={26} />
            <span className="hidden h-4 w-px bg-line sm:block" aria-hidden="true" />
            <span className="hidden text-[14px] font-medium tracking-tight text-muted sm:block">
              Since You Last Looked
            </span>
          </Link>

          <nav aria-label="Main" className="order-3 -mx-1 flex w-full gap-1 sm:order-2 sm:w-auto">
            {NAV.map((item) => {
              const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  aria-current={active ? "page" : undefined}
                  className={`rounded-md px-2.5 py-1 text-[13px] transition-colors ${
                    active
                      ? "bg-surface-2 font-medium text-ink"
                      : "text-muted hover:bg-surface-2 hover:text-ink"
                  }`}
                >
                  {item.label}
                </Link>
              );
            })}
          </nav>

          <div className="order-2 ml-auto flex items-center gap-4 sm:order-3">
            <MarketPill market={market} />
            {lastChecked ? (
              <span className="hidden text-[12px] text-faint md:inline">
                Last checked {relativeTime(lastChecked)}
              </span>
            ) : null}
            {user ? (
              <div className="flex items-center gap-2">
                <span className="hidden text-[12px] text-muted sm:inline">
                  {user.display_name}
                </span>
                <button
                  onClick={logout}
                  className="rounded-md px-2 py-1 text-[12px] text-muted hover:bg-surface-2 hover:text-ink"
                >
                  Sign out
                </button>
              </div>
            ) : null}
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-4 py-6">{children}</main>

      <footer className="mx-auto max-w-6xl px-4 pb-10 pt-4">
        <p className="text-[11px] leading-relaxed text-faint">
          Market data is provided for information only and may be delayed. Nothing here is
          investment advice.
        </p>
      </footer>
    </div>
  );
}
