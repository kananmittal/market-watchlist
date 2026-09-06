// Mirrors the backend Pydantic schemas. Kept explicit rather than generated so
// the shape the UI relies on is reviewable in one place.

export type Severity = "HIGH" | "MEDIUM" | "NORMAL";

export type ChangeType =
  | "COMPANY_SPECIFIC"
  | "SECTOR_DRIVEN"
  | "MARKET_DRIVEN"
  | "TECHNICAL"
  | "NO_MATERIAL_CHANGE";

export type ChangeStatus =
  | "NEW"
  | "IMPORTANT"
  | "VIEWED"
  | "ACKNOWLEDGED"
  | "DISMISSED"
  | "STALE";

export type Freshness = "LIVE" | "DELAYED" | "STALE" | "UNAVAILABLE";

export type DataQuality =
  | "OK"
  | "DELAYED"
  | "STALE"
  | "CONFLICTED"
  | "UNAVAILABLE"
  | "SYNTHETIC";

export interface User {
  id: string;
  email: string;
  display_name: string;
  is_demo: boolean;
  created_at: string;
  last_dashboard_view_at: string | null;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
  user: User;
}

export interface FreshnessInfo {
  freshness?: Freshness;
  label?: string;
  age_seconds?: number | null;
  source?: string | null;
  is_synthetic?: boolean;
  quality?: DataQuality;
  observed_at?: string;
  notes?: string[];
  market_status?: string;
}

export interface Quote {
  symbol: string;
  name: string;
  price: number | null;
  previous_close: number | null;
  change_pct: number | null;
  open: number | null;
  high: number | null;
  low: number | null;
  volume: number | null;
  currency: string;
  observed_at: string | null;
  freshness: FreshnessInfo;
}

export interface Evidence {
  evidence_type: string;
  label: string;
  value: number | null;
  unit: string | null;
  source_ref: string | null;
  weight_contribution: number;
  metadata: Record<string, unknown>;
}

export interface ScoreBreakdown {
  abnormality: number;
  relative_move: number;
  volume: number;
  news: number;
  base_significance: number;
  user_adjustment: number;
  total: number;
}

export interface ChangeMetrics {
  price_change_pct: number | null;
  relative_to_benchmark_pct: number | null;
  relative_to_sector_pct: number | null;
  volume_multiple: number | null;
  normalized_move: number | null;
  expected_daily_move_pct: number | null;
  news_event_count: number;
  max_news_significance: number;
}

export interface Change {
  id: string;
  symbol: string;
  name: string;
  detected_at: string;
  since: string;
  change_type: ChangeType;
  severity: Severity;
  attention_score: number;
  primary_reason: string;
  status: ChangeStatus;
  headline: string;
  data_quality: DataQuality;
  is_synthetic: boolean;
  metrics: ChangeMetrics;
  breakdown: ScoreBreakdown;
  evidence: Evidence[];
}

export interface NewsItem {
  event_id: string;
  symbol: string;
  event_type: string;
  headline: string;
  summary: string | null;
  source: string;
  source_url: string | null;
  published_at: string;
  entity_confidence: number;
  event_significance: number;
  article_count: number;
}

export interface ActivityItem {
  event_type: string;
  symbol: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface WatchlistItem {
  symbol: string;
  display_name: string | null;
  added_at: string;
  sort_order: number;
}

export interface Watchlist {
  id: string;
  name: string;
  items: WatchlistItem[];
  created_at: string;
  updated_at: string;
}

export interface MarketStatus {
  status: "OPEN" | "PRE_OPEN" | "CLOSED" | "WEEKEND" | "HOLIDAY";
  label: string;
  as_of: string;
  next_open: string | null;
  last_close: string | null;
}

export interface CatchUp {
  headline: string;
  high_count: number;
  medium_count: number;
  meaningful_count: number;
  normal_count: number;
  unreviewed_count: number;
  by_type: Record<string, number>;
  top: Array<{
    symbol: string;
    name: string;
    headline: string;
    severity: Severity;
    attention_score: number;
    change_type: ChangeType;
    evidence: string[];
    status: ChangeStatus;
  }>;
}

export interface WatchlistRow {
  symbol: string;
  name: string;
  quote: Quote | null;
  change: Change | null;
  news: NewsItem[];
  last_viewed_at: string | null;
  last_acknowledged_at: string | null;
}

export interface Dashboard {
  last_checked_at: string | null;
  away_for: string;
  is_first_visit: boolean;
  demo_mode: boolean;
  market: MarketStatus;
  benchmark: Quote | null;
  catch_up: CatchUp;
  meaningful_changes: Change[];
  normal_movements: Change[];
  watchlist: WatchlistRow[];
}

export interface HistoryBar {
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface History {
  symbol: string;
  interval: string;
  source: string;
  is_synthetic: boolean;
  bars: HistoryBar[];
}

export interface StockDetail {
  symbol: string;
  name: string;
  sector: string | null;
  quote: Quote | null;
  change: Change | null;
  benchmark: Quote | null;
  sector_index: Quote | null;
  history: History | null;
  news: NewsItem[];
  activity: ActivityItem[];
  last_viewed_at: string | null;
  last_acknowledged_at: string | null;
}

export interface SymbolSearchResult {
  symbol: string;
  name: string;
  sector: string;
  is_index: boolean;
}

export interface CopilotReply {
  answer: string;
  grounded: boolean;
  evidence: string[];
  symbols: string[];
  model: string | null;
  degraded_reason: string | null;
  cached: boolean;
}

export interface ApiErrorShape {
  error: { code: string; message: string; details?: Record<string, unknown> };
}
