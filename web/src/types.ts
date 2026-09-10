export type FilterOp = "gt" | "gte" | "lt" | "lte" | "eq";

export type ScreenerField =
  | "price"
  | "avg_volume"
  | "atr"
  | "rel_vol_at"
  | "market"
  | "dollar_volume"
  | "market_cap";

export type Filter = {
  field: ScreenerField;
  op: FilterOp;
  value: string | number;
  lookback?: number | null;
  window_minutes?: number | null;
};

export type ScreenerRow = {
  security_id: number;
  ticker: string;
  name: string;
  exchange: string;
  market: string;
  as_of?: string | null;
  price: number | null;
  avg_volume: number | null;
  atr: number | null;
  rel_vol_at: number | null;
  rel_vol_at_sessions: number | null;
  dollar_volume: number | null;
  market_cap: number | null;
  first5m_volume: number | null;
};

export type Clock = {
  as_of: string | null;
  last_success: string | null;
  expected: string | null;
  pending_sessions: string[];
  ingest_running: boolean;
};

export type SystemEvent = {
  id: string;
  ts: string;
  level: "info" | "warning" | "error" | string;
  source: string;
  code: string;
  title: string;
  detail: string;
  data: Record<string, unknown>;
};

export type ScreenerResponse = {
  as_of: string | null;
  n: number;
  rows: ScreenerRow[];
};

export type Bar = {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
};

export type SavedScan = {
  id: string;
  name: string;
  filters: Filter[];
  sort: keyof ScreenerRow | "atr_pct";
  sortDir: "asc" | "desc";
  columns: string[];
};

export type ColumnId =
  | "ticker"
  | "name"
  | "exchange"
  | "market"
  | "as_of"
  | "price"
  | "rel_vol_at"
  | "rel_vol_at_sessions"
  | "avg_volume"
  | "dollar_volume"
  | "atr"
  | "atr_pct"
  | "market_cap"
  | "first5m_volume";
