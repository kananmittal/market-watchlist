"use client";

// Shared primitives. Severity and freshness always render a text label as well
// as colour, so meaning survives colour-blindness and greyscale printing.

import type { ReactNode } from "react";
import type { ChangeStatus, FreshnessInfo, Severity } from "@/lib/types";

export function Card({
  children,
  className = "",
  as: Tag = "div",
}: {
  children: ReactNode;
  className?: string;
  as?: "div" | "section" | "article";
}) {
  return (
    <Tag
      className={`rounded-lg border border-line bg-surface ${className}`}
    >
      {children}
    </Tag>
  );
}

export function SectionHeading({
  title,
  hint,
  action,
}: {
  title: string;
  hint?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
      <div className="flex items-baseline gap-2">
        <h2 className="text-[13px] font-semibold uppercase tracking-[0.08em] text-muted">
          {title}
        </h2>
        {hint ? <span className="text-xs text-faint">{hint}</span> : null}
      </div>
      {action}
    </div>
  );
}

const SEVERITY_STYLE: Record<Severity, { bg: string; fg: string; label: string; mark: string }> = {
  HIGH: { bg: "bg-high-soft", fg: "text-high", label: "High attention", mark: "▲" },
  MEDIUM: { bg: "bg-medium-soft", fg: "text-medium", label: "Medium", mark: "◆" },
  NORMAL: { bg: "bg-normal-soft", fg: "text-normal", label: "Normal", mark: "•" },
};

export function SeverityBadge({ severity, compact = false }: { severity: Severity; compact?: boolean }) {
  const s = SEVERITY_STYLE[severity] ?? SEVERITY_STYLE.NORMAL;
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded px-2 py-0.5 text-[11px] font-medium ${s.bg} ${s.fg}`}
    >
      <span aria-hidden="true">{s.mark}</span>
      {compact ? severity[0] + severity.slice(1).toLowerCase() : s.label}
    </span>
  );
}

const STATUS_STYLE: Record<ChangeStatus, { label: string; className: string; mark: string }> = {
  NEW: { label: "Unreviewed", className: "bg-high-soft text-high", mark: "●" },
  IMPORTANT: { label: "Unreviewed", className: "bg-high-soft text-high", mark: "●" },
  VIEWED: { label: "Seen, not reviewed", className: "bg-medium-soft text-medium", mark: "◐" },
  ACKNOWLEDGED: { label: "Reviewed", className: "bg-reviewed-soft text-reviewed", mark: "✓" },
  DISMISSED: { label: "Dismissed", className: "bg-normal-soft text-normal", mark: "×" },
  STALE: { label: "Stale", className: "bg-normal-soft text-normal", mark: "◌" },
};

export function StatusBadge({ status }: { status: ChangeStatus }) {
  const s = STATUS_STYLE[status] ?? STATUS_STYLE.NEW;
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded px-2 py-0.5 text-[11px] font-medium ${s.className}`}
    >
      <span aria-hidden="true">{s.mark}</span>
      {s.label}
    </span>
  );
}

/**
 * Freshness is stated plainly. Stale data is never dressed up as live, and
 * demo data is always announced as demo data.
 */
export function FreshnessTag({ info }: { info?: FreshnessInfo | null }) {
  if (!info || !info.label) return null;
  const kind = info.freshness ?? "UNAVAILABLE";
  const tone =
    info.is_synthetic || info.quality === "SYNTHETIC"
      ? "text-medium"
      : kind === "LIVE"
        ? "text-up"
        : kind === "DELAYED"
          ? "text-medium"
          : "text-muted";
  const dot =
    kind === "LIVE" ? "bg-up" : kind === "DELAYED" ? "bg-medium" : "bg-faint";
  return (
    <span className={`inline-flex items-center gap-1.5 text-[11px] ${tone}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${dot}`} aria-hidden="true" />
      {info.label}
      {info.quality === "CONFLICTED" ? (
        <span className="ml-1 rounded bg-medium-soft px-1.5 py-0.5 text-medium">
          Under verification
        </span>
      ) : null}
    </span>
  );
}

export function Button({
  children,
  onClick,
  variant = "primary",
  size = "md",
  disabled,
  type = "button",
  className = "",
  title,
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "md";
  disabled?: boolean;
  type?: "button" | "submit";
  className?: string;
  title?: string;
}) {
  const base =
    "inline-flex items-center justify-center gap-1.5 rounded-md font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50";
  const sizes = { sm: "px-2.5 py-1 text-xs", md: "px-3.5 py-2 text-[13px]" };
  const variants = {
    primary: "bg-accent text-white hover:opacity-90",
    secondary: "border border-line-strong bg-surface text-ink hover:bg-surface-2",
    ghost: "text-muted hover:bg-surface-2 hover:text-ink",
    danger: "border border-line-strong text-down hover:bg-down-soft",
  };
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={`${base} ${sizes[size]} ${variants[variant]} ${className}`}
    >
      {children}
    </button>
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`skeleton ${className}`} aria-hidden="true" />;
}

export function EmptyState({
  title,
  body,
  action,
}: {
  title: string;
  body: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-line px-6 py-12 text-center">
      <p className="text-sm font-medium text-ink">{title}</p>
      <p className="mt-1 max-w-sm text-[13px] text-muted">{body}</p>
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}

export function ErrorState({
  message,
  onRetry,
}: {
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div
      role="alert"
      className="rounded-lg border border-line bg-down-soft px-4 py-3 text-[13px] text-down"
    >
      <p className="font-medium">Something went wrong</p>
      <p className="mt-0.5 text-ink-2">{message}</p>
      {onRetry ? (
        <div className="mt-2.5">
          <Button variant="secondary" size="sm" onClick={onRetry}>
            Try again
          </Button>
        </div>
      ) : null}
    </div>
  );
}

/** A demo-mode banner. Synthetic data must never masquerade as real. */
export function DemoBanner() {
  return (
    <div className="border-b border-line bg-medium-soft px-4 py-1.5 text-center text-[12px] text-medium">
      <strong className="font-semibold">Demo mode</strong> — figures are
      generated sample data, not live market prices.
    </div>
  );
}
