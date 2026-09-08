import { DEFAULT_COLUMNS } from "./catalog";
import type { ColumnId, SavedScan } from "./types";

const SCANS_KEY = "pb.screener.scans";
const COLS_KEY = "pb.screener.columns";

export function loadScans(): SavedScan[] {
  try {
    const raw = localStorage.getItem(SCANS_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as SavedScan[];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function saveScans(scans: SavedScan[]) {
  localStorage.setItem(SCANS_KEY, JSON.stringify(scans));
}

export function loadColumns(): ColumnId[] {
  try {
    const raw = localStorage.getItem(COLS_KEY);
    if (!raw) return [...DEFAULT_COLUMNS];
    const parsed = JSON.parse(raw) as ColumnId[];
    return parsed.includes("ticker") ? parsed : ["ticker", ...parsed];
  } catch {
    return [...DEFAULT_COLUMNS];
  }
}

export function saveColumns(cols: ColumnId[]) {
  localStorage.setItem(COLS_KEY, JSON.stringify(cols));
}
