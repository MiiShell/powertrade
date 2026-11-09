export type Ready = { status: string; checks: Record<string, string> };
export type WatchItem = {
  id: number;
  symbol: string;
  name: string;
  type: string;
  currency: string;
  last_close: number | null;
  last_date: string | null;
  change_pct: number | null;
  ingestion: { status: string | null; at: string | null; error: string | null };
};
export type FmpUsage = {
  configured: boolean;
  calls_today: number;
  allowed_now: number;
  daily_limit: number;
  bytes_30d: number;
  bandwidth_limit_30d: number;
  blocked_today: boolean;
};
export type Point = [number, number];
export type Divergence = {
  t: number; prev_t: number; kind: "bull" | "bear"; rsi: number; prev_rsi: number; price: number; prev_price: number;
};
export type Level = { id: number; price: number; color: string; label: string };
export type ChartData = {
  instrument: { id: number; symbol: string; name: string; type: string; currency: string };
  tf: "1d" | "1w";
  bars: [number, number, number, number, number, number | null][];
  indicators: Record<string, Point[]>;
  rsi: { period: number; values: Point[]; divergences: Divergence[] } | null;
  levels: Level[];
};
export type ChartConfig = { sma: number[]; ema: number[]; rsi: number };
export type TaRow = { name: string; value: number | null; action: "buy" | "neutral" | "sell" };
export type Counts = { sell: number; neutral: number; buy: number };
export type TaGroup = { score: number | null; label: string; counts: Counts; rows: TaRow[] };
export type Technicals = {
  summary: { score: number | null; label: string; counts: Counts };
  oscillators: TaGroup;
  moving_averages: TaGroup;
  as_of: string;
  bars: number;
};
export type PivotSet = Record<"R3" | "R2" | "R1" | "P" | "S1" | "S2" | "S3", number | null>;
export type Pivots = { basis: string; ohlc: number[]; levels: Record<"classic" | "fibonacci" | "camarilla" | "woodie" | "dm", PivotSet> };
export type Profile = {
  source: string; company_name: string | null; description: string | null; sector: string | null; industry: string | null;
  country: string | null; exchange: string | null; currency: string | null; website: string | null; ceo: string | null;
  employees: number | null; ipo_date: string | null; isin: string | null; market_cap: number | null; beta: number | null;
  last_dividend: number | null; avg_volume: number | null; is_etf: boolean | null; fetched_at: string;
};
export type Stats = {
  date: string; price: number; change: number | null; change_pct: number | null; volume: number | null;
  avg_volume_30d: number | null; day_range: [number, number]; range_week: [number, number]; range_52w: [number, number];
  all_time_high: { price: number; date: string }; performance: Record<string, number | null>;
};
export type Tf = "1d" | "1w" | "1mo";
export type Details = {
  instrument: { id: number; symbol: string; name: string; type: string; currency: string; isin: string | null; exchange: string | null; country: string | null };
  profile: Profile | null;
  stats: Stats | Record<string, never>;
  technicals: Record<Tf, Technicals | null>;
  pivots: Record<Tf, Pivots | null>;
};
export type Seasonality = {
  range: { min_year: number; max_year: number; from: number; to: number } | null;
  years: { year: number; points: Point[]; last: number | null }[];
  average: Point[];
  average_years: number[];
  monthly: Record<string, Record<string, number>>;
  monthly_stats: Record<string, { avg: number; positive_pct: number; n: number }>;
};
export type PineScript = { id: number; name: string; source: string; builtin: boolean; created_at: string; updated_at: string };
export type SelfCheck = { worker: string; db_write: string; db_read: string; latency_ms: number };

async function request<T>(path: string, init?: RequestInit): Promise<{ status: number; data: T | null }> {
  const res = await fetch(path, {
    ...init,
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  const text = await res.text();
  return { status: res.status, data: text ? (JSON.parse(text) as T) : null };
}

export const api = {
  me: () => request<{ user: string }>("/api/auth/me"),
  login: (username: string, password: string, totp?: string) =>
    request<null>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password, totp: totp || null }),
    }),
  logout: () => request<null>("/api/auth/logout", { method: "POST" }),
  ready: () => request<Ready>("/api/health/ready"),
  watchlist: () => request<{ name: string; items: WatchItem[] }>("/api/watchlist"),
  addItem: (symbol: string, type: string, currency: string) =>
    request<{ id: number }>("/api/watchlist/items", {
      method: "POST",
      body: JSON.stringify({ symbol, type, currency }),
    }),
  removeItem: (id: number) => request<null>(`/api/watchlist/items/${id}`, { method: "DELETE" }),
  refresh: (id: number) => request<{ status: string }>(`/api/instruments/${id}/refresh`, { method: "POST" }),
  chart: (id: number, tf: string, cfg: ChartConfig) => {
    const q = new URLSearchParams({ tf, sma: cfg.sma.join(","), ema: cfg.ema.join(","), rsi: String(cfg.rsi) });
    return request<ChartData>(`/api/instruments/${id}/chart?${q.toString()}`);
  },
  addLevel: (id: number, price: number, color: string, label = "") =>
    request<Level>(`/api/instruments/${id}/levels`, { method: "POST", body: JSON.stringify({ price, color, label }) }),
  deleteLevel: (id: number, levelId: number) =>
    request<null>(`/api/instruments/${id}/levels/${levelId}`, { method: "DELETE" }),
  details: (id: number) => request<Details>(`/api/instruments/${id}/details`),
  seasonality: (id: number, from?: number, to?: number) => {
    const q = new URLSearchParams();
    if (from) q.set("from_year", String(from));
    if (to) q.set("to_year", String(to));
    return request<Seasonality>(`/api/instruments/${id}/seasonality?${q.toString()}`);
  },
  refreshProfile: (id: number) => request<{ status: string }>(`/api/instruments/${id}/profile/refresh`, { method: "POST" }),
  stats: (id: number) => request<Stats>(`/api/instruments/${id}/stats`),
  pineScripts: () => request<{ scripts: PineScript[] }>("/api/pine/scripts"),
  createPine: (body: { name: string; source: string }) =>
    request<PineScript>("/api/pine/scripts", { method: "POST", body: JSON.stringify(body) }),
  updatePine: (id: number, body: { name: string; source: string }) =>
    request<PineScript>(`/api/pine/scripts/${id}`, { method: "PUT", body: JSON.stringify(body) }),
  deletePine: (id: number) => request<null>(`/api/pine/scripts/${id}`, { method: "DELETE" }),
  usage: () => request<{ fmp: FmpUsage }>("/api/providers/usage"),
  selfcheck: () => request<SelfCheck>("/api/system/selfcheck", { method: "POST" }),
};
