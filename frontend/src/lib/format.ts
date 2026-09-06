// Presentation helpers. Formatting lives here so number and date rendering is
// consistent everywhere, including the empty and unavailable cases.

export function formatPrice(value: number | null | undefined, currency = "INR"): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const symbol = currency === "INR" ? "₹" : "";
  return `${symbol}${value.toLocaleString("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

export function formatPct(value: number | null | undefined, withSign = true): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const sign = withSign && value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

export function formatMultiple(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${value.toFixed(1)}x`;
}

export function formatVolume(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  if (value >= 1e7) return `${(value / 1e7).toFixed(2)} Cr`;
  if (value >= 1e5) return `${(value / 1e5).toFixed(2)} L`;
  if (value >= 1e3) return `${(value / 1e3).toFixed(1)}K`;
  return value.toFixed(0);
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("en-IN", {
    day: "numeric",
    month: "short",
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  });
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return "never";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "never";
  const seconds = Math.max(0, Math.floor((Date.now() - then) / 1000));
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days} day${days === 1 ? "" : "s"} ago`;
  const months = Math.floor(days / 30);
  return `${months} month${months === 1 ? "" : "s"} ago`;
}

/** Direction class for a signed number. Never colour alone: pair with a sign. */
export function directionClass(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "text-muted";
  if (value > 0) return "text-up";
  if (value < 0) return "text-down";
  return "text-muted";
}

export function changeTypeLabel(type: string): string {
  return (
    {
      COMPANY_SPECIFIC: "Company-specific",
      SECTOR_DRIVEN: "Sector-driven",
      MARKET_DRIVEN: "Market-driven",
      TECHNICAL: "Unusual activity",
      NO_MATERIAL_CHANGE: "No material change",
    }[type] ?? type
  );
}

export function reasonLabel(reason: string): string {
  return (
    {
      COMPANY_EVENT: "Company event",
      ABNORMAL_MOVE: "Abnormal move",
      VOLUME_SPIKE: "Volume spike",
      BENCHMARK_DIVERGENCE: "Diverged from market",
      SECTOR_MOVE: "Moved with sector",
      MARKET_MOVE: "Moved with market",
      NO_SIGNAL: "No signal",
    }[reason] ?? reason
  );
}

export function activityLabel(type: string): string {
  return (
    {
      WATCHLIST_CREATED: "Created watchlist",
      WATCHLIST_RENAMED: "Renamed watchlist",
      WATCHLIST_DELETED: "Deleted watchlist",
      STOCK_ADDED: "Added to watchlist",
      STOCK_REMOVED: "Removed from watchlist",
      STOCK_VIEWED: "Viewed stock",
      STOCK_SEARCHED: "Searched",
      CHART_VIEWED: "Viewed chart",
      NEWS_VIEWED: "Viewed news",
      CHANGE_VIEWED: "Opened change",
      CHANGE_ACKNOWLEDGED: "Marked reviewed",
      CHANGE_DISMISSED: "Dismissed change",
      COPILOT_QUERY: "Asked copilot",
      DASHBOARD_VIEWED: "Opened dashboard",
    }[type] ?? type
  );
}

export function eventTypeLabel(type: string): string {
  return (
    {
      EARNINGS: "Earnings",
      MERGER_ACQUISITION: "M&A",
      REGULATORY: "Regulatory",
      LEGAL: "Legal",
      MANAGEMENT: "Management",
      CORPORATE_ACTION: "Corporate action",
      PRODUCT_BUSINESS: "Business",
      ANALYST: "Analyst",
      SECTOR: "Sector",
      GENERAL: "General",
    }[type] ?? type
  );
}
