import type { ColumnId, Filter, FilterOp, ScreenerField } from "./types";

export type FieldMeta = {
  id: ScreenerField;
  label: string;
  short: string;
  group: "Security info" | "Market data" | "Technicals" | "Liquidity";
  hint: string;
  lookback: boolean;
  window: boolean;
  valueKind: "number" | "text";
  unit?: string;
  presets?: number[];
};

export const FIELDS: FieldMeta[] = [
  {
    id: "market",
    label: "Market",
    short: "US",
    group: "Security info",
    hint: "Listing market. Stage 1 is US only.",
    lookback: false,
    window: false,
    valueKind: "text",
  },
  {
    id: "price",
    label: "Price",
    short: "Price",
    group: "Market data",
    hint: "Last EOD close",
    lookback: false,
    window: false,
    valueKind: "number",
    unit: "USD",
    presets: [5, 10, 20, 50],
  },
  {
    id: "market_cap",
    label: "Market capitalization",
    short: "Mkt cap",
    group: "Market data",
    hint: "Close × shares outstanding when available",
    lookback: false,
    window: false,
    valueKind: "number",
    presets: [300_000_000, 2_000_000_000, 10_000_000_000],
  },
  {
    id: "dollar_volume",
    label: "Dollar volume",
    short: "Dollar vol",
    group: "Market data",
    hint: "Close × session volume",
    lookback: false,
    window: false,
    valueKind: "number",
    presets: [10_000_000, 20_000_000, 50_000_000],
  },
  {
    id: "avg_volume",
    label: "Average volume",
    short: "Avg vol",
    group: "Liquidity",
    hint: "SMA of EOD volume",
    lookback: true,
    window: false,
    valueKind: "number",
    presets: [500_000, 1_000_000, 2_000_000, 5_000_000],
  },
  {
    id: "rel_vol_at",
    label: "Relative volume at time",
    short: "Rel vol at time",
    group: "Technicals",
    hint: "First N minutes vs average of prior sessions",
    lookback: true,
    window: true,
    valueKind: "number",
    presets: [1, 1.5, 2, 3],
  },
  {
    id: "atr",
    label: "Average true range",
    short: "ATR",
    group: "Technicals",
    hint: "Wilder ATR on daily bars",
    lookback: true,
    window: false,
    valueKind: "number",
    presets: [0.5, 1, 2],
  },
];

/** Always on the 4-row bank, even when inactive. */
export const PINNED: ScreenerField[] = [
  "market",
  "price",
  "rel_vol_at",
  "avg_volume",
  "atr",
  "market_cap",
];

export const OPS: { id: FilterOp; label: string }[] = [
  { id: "gt", label: "Above" },
  { id: "gte", label: "At least" },
  { id: "lt", label: "Below" },
  { id: "lte", label: "At most" },
  { id: "eq", label: "Equal" },
];

export const OP_SHORT: Record<FilterOp, string> = {
  gt: ">",
  gte: "≥",
  lt: "<",
  lte: "≤",
  eq: "=",
};

export const LOOKBACKS = [7, 10, 14, 20, 30];
export const WINDOWS = [5, 10, 15, 30];

export const COLUMNS: { id: ColumnId; label: string; align: "left" | "right" }[] = [
  { id: "ticker", label: "Symbol", align: "left" },
  { id: "name", label: "Name", align: "left" },
  { id: "exchange", label: "Exchange", align: "left" },
  { id: "market", label: "Market", align: "left" },
  { id: "as_of", label: "Updated", align: "left" },
  { id: "price", label: "Price", align: "right" },
  { id: "rel_vol_at", label: "Rel vol", align: "right" },
  { id: "rel_vol_at_sessions", label: "Rel vol n", align: "right" },
  { id: "avg_volume", label: "Avg vol", align: "right" },
  { id: "first5m_volume", label: "Vol 5m", align: "right" },
  { id: "dollar_volume", label: "Dollar vol", align: "right" },
  { id: "atr", label: "ATR", align: "right" },
  { id: "atr_pct", label: "ATR %", align: "right" },
  { id: "market_cap", label: "Mkt cap", align: "right" },
];

export const DEFAULT_COLUMNS: ColumnId[] = [
  "ticker",
  "price",
  "market_cap",
  "as_of",
  "avg_volume",
  "atr",
];

export const US_UNIVERSE: Filter[] = [{ field: "market", op: "eq", value: "US" }];

export const OPEN_RELVOL: Filter[] = [
  { field: "market", op: "eq", value: "US" },
  { field: "price", op: "gt", value: 5 },
  { field: "rel_vol_at", op: "gt", value: 1, lookback: 14, window_minutes: 5 },
  { field: "avg_volume", op: "gt", value: 1_000_000, lookback: 14 },
  { field: "atr", op: "gt", value: 0.5, lookback: 14 },
];

export type BuiltinScan = { id: string; name: string; filters: Filter[]; sort: ColumnId };

export const BUILTIN_SCANS: BuiltinScan[] = [
  { id: "us", name: "US stocks", filters: US_UNIVERSE, sort: "market_cap" },
  { id: "open_relvol", name: "Open RelVol", filters: OPEN_RELVOL, sort: "rel_vol_at" },
  {
    id: "liquid_us",
    name: "Liquid US",
    sort: "dollar_volume",
    filters: [
      { field: "market", op: "eq", value: "US" },
      { field: "price", op: "gt", value: 5 },
      { field: "avg_volume", op: "gt", value: 1_000_000, lookback: 14 },
      { field: "dollar_volume", op: "gt", value: 20_000_000 },
    ],
  },
  {
    id: "high_relvol",
    name: "High RelVol",
    sort: "rel_vol_at",
    filters: [
      { field: "market", op: "eq", value: "US" },
      { field: "price", op: "gt", value: 5 },
      { field: "rel_vol_at", op: "gt", value: 2, lookback: 14, window_minutes: 5 },
      { field: "avg_volume", op: "gt", value: 500_000, lookback: 14 },
    ],
  },
  {
    id: "wide_range",
    name: "Wide range",
    sort: "atr",
    filters: [
      { field: "market", op: "eq", value: "US" },
      { field: "price", op: "gt", value: 10 },
      { field: "atr", op: "gt", value: 1, lookback: 14 },
      { field: "avg_volume", op: "gt", value: 1_000_000, lookback: 14 },
    ],
  },
];

export function fieldMeta(id: ScreenerField): FieldMeta {
  return FIELDS.find((f) => f.id === id) ?? FIELDS[0];
}

export function defaultFilter(id: ScreenerField): Filter {
  const m = fieldMeta(id);
  if (m.valueKind === "text") return { field: id, op: "eq", value: "US" };
  const value = m.presets?.[0] ?? 0;
  return {
    field: id,
    op: "gt",
    value,
    lookback: m.lookback ? 14 : null,
    window_minutes: m.window ? 5 : null,
  };
}

export function compactValue(n: number): string {
  const abs = Math.abs(n);
  if (abs >= 1e12) return `${n / 1e12}T`;
  if (abs >= 1e9) return `${trimNum(n / 1e9)}B`;
  if (abs >= 1e6) return `${trimNum(n / 1e6)}M`;
  if (abs >= 1e3) return `${trimNum(n / 1e3)}K`;
  return String(n);
}

function trimNum(n: number): string {
  return n % 1 === 0 ? String(n) : n.toFixed(1).replace(/\.0$/, "");
}

export function chipLabel(f: Filter): string {
  const m = fieldMeta(f.field);
  if (f.field === "market") return String(f.value || "US");
  const look =
    m.lookback && f.lookback && f.field !== "rel_vol_at" ? `, ${f.lookback}` : "";
  const val = typeof f.value === "number" ? compactValue(f.value) : String(f.value);
  const unit = m.unit && typeof f.value === "number" && f.value < 1000 ? ` ${m.unit}` : "";
  return `${m.short}${look} ${OP_SHORT[f.op]} ${val}${unit}`;
}
