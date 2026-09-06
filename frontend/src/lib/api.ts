// Typed API client.
//
// The auth token lives in localStorage for convenience only; the server is the
// authoritative store for every piece of user state. Losing localStorage costs
// a re-login, never data.

import type {
  ApiErrorShape,
  AuthResponse,
  Change,
  CopilotReply,
  Dashboard,
  History,
  Quote,
  StockDetail,
  SymbolSearchResult,
  User,
  Watchlist,
} from "./types";

const RAW_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
export const API_BASE = RAW_BASE.replace(/\/+$/, "");

const TOKEN_KEY = "mw.token";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null) {
  if (typeof window === "undefined") return;
  try {
    if (token) window.localStorage.setItem(TOKEN_KEY, token);
    else window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* private browsing - the session simply will not persist */
  }
}

export class ApiError extends Error {
  code: string;
  status: number;
  details?: Record<string, unknown>;

  constructor(message: string, code: string, status: number, details?: Record<string, unknown>) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
    this.details = details;
  }

  /** True when the caller should send the user back to sign-in. */
  get isAuth() {
    return this.status === 401;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    ...(init.body ? { "Content-Type": "application/json" } : {}),
    ...((init.headers as Record<string, string>) ?? {}),
  };
  if (token) headers.Authorization = `Bearer ${token}`;

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, { ...init, headers });
  } catch {
    // Network-level failure: a sleeping free-tier backend looks exactly like this.
    throw new ApiError(
      "Cannot reach the server. It may be waking up from sleep - try again in a moment.",
      "NETWORK_ERROR",
      0,
    );
  }

  if (response.status === 204) return undefined as T;

  const text = await response.text();
  let payload: unknown = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = null;
    }
  }

  if (!response.ok) {
    const shaped = payload as ApiErrorShape | null;
    throw new ApiError(
      shaped?.error?.message ?? `Request failed (${response.status})`,
      shaped?.error?.code ?? "UNKNOWN",
      response.status,
      shaped?.error?.details,
    );
  }
  return payload as T;
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined });

export const api = {
  // ---- auth ----
  register: (email: string, password: string, display_name: string) =>
    post<AuthResponse>("/api/auth/register", { email, password, display_name }),
  login: (email: string, password: string) =>
    post<AuthResponse>("/api/auth/login", { email, password }),
  me: () => request<User>("/api/auth/me"),

  // ---- watchlists ----
  listWatchlists: () => request<Watchlist[]>("/api/watchlists"),
  createWatchlist: (name: string) => post<Watchlist>("/api/watchlists", { name }),
  renameWatchlist: (id: string, name: string) =>
    request<Watchlist>(`/api/watchlists/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ name }),
    }),
  deleteWatchlist: (id: string) =>
    request<void>(`/api/watchlists/${id}`, { method: "DELETE" }),
  addSymbol: (id: string, symbol: string) =>
    post<Watchlist>(`/api/watchlists/${id}/items`, { symbol }),
  removeSymbol: (id: string, symbol: string) =>
    request<Watchlist>(`/api/watchlists/${id}/items/${encodeURIComponent(symbol)}`, {
      method: "DELETE",
    }),
  reorder: (id: string, symbols: string[]) =>
    post<Watchlist>(`/api/watchlists/${id}/reorder`, { symbols }),

  // ---- market ----
  search: (q: string) =>
    request<SymbolSearchResult[]>(`/api/market/search?q=${encodeURIComponent(q)}`),
  quote: (symbol: string) => request<Quote>(`/api/market/quote/${encodeURIComponent(symbol)}`),
  history: (symbol: string, period = "3mo") =>
    request<History>(`/api/market/history/${encodeURIComponent(symbol)}?period=${period}`),

  // ---- core product ----
  dashboard: (opts: { advanceAnchor?: boolean; includeNews?: boolean } = {}) => {
    const params = new URLSearchParams({
      advance_anchor: String(opts.advanceAnchor ?? true),
      include_news: String(opts.includeNews ?? true),
    });
    return request<Dashboard>(`/api/dashboard?${params}`);
  },
  changes: (filters: { status?: string; symbol?: string; severity?: string } = {}) => {
    const params = new URLSearchParams();
    if (filters.status) params.set("status", filters.status);
    if (filters.symbol) params.set("symbol", filters.symbol);
    if (filters.severity) params.set("severity", filters.severity);
    const qs = params.toString();
    return request<Change[]>(`/api/changes${qs ? `?${qs}` : ""}`);
  },
  change: (id: string) => request<Change>(`/api/changes/${id}`),
  acknowledgeChange: (id: string) => post<Change>(`/api/changes/${id}/acknowledge`),
  dismissChange: (id: string) => post<Change>(`/api/changes/${id}/dismiss`),

  stock: (symbol: string, period = "3mo") =>
    request<StockDetail>(`/api/stocks/${encodeURIComponent(symbol)}?period=${period}`),
  acknowledgeStock: (symbol: string) =>
    post<StockDetail>(`/api/stocks/${encodeURIComponent(symbol)}/acknowledge`),

  // ---- copilot ----
  copilot: (question: string, symbol?: string) =>
    post<CopilotReply>("/api/copilot/chat", { question, symbol: symbol ?? null }),

  // ---- demo ----
  demoStatus: () =>
    request<{ demo_mode: boolean; step: number; available_steps: number[] }>("/api/demo/status"),
  demoStep: (step: number) => post<{ step: number }>(`/api/demo/step?step=${step}`),
  demoReset: () => post<{ reset: boolean; step: number }>("/api/demo/reset"),

  // ---- health ----
  health: () => request<{ status: string; demo_mode: boolean }>("/api/health"),
};
