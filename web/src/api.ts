import type { Bar, Clock, Filter, ScreenerResponse, SystemEvent } from "./types";

const base = import.meta.env.VITE_API_BASE ?? "";

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${base}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? JSON.stringify(body);
    } catch {
      /* ignore */
    }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return res.json() as Promise<T>;
}

export function getClock() {
  return json<Clock>("/v1/clock");
}

export function runScreener(body: {
  preset?: string | null;
  filters: Filter[];
  limit: number;
  sort: string;
  sort_dir: "asc" | "desc";
}) {
  const payload = {
    ...body,
    filters: body.filters.map((f) => ({
      field: f.field,
      op: f.op,
      value: f.field === "market" ? String(f.value) : Number(f.value),
      lookback: f.lookback ?? null,
      window_minutes: f.window_minutes ?? null,
    })),
  };
  return json<ScreenerResponse>("/v1/screener", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getBars(ticker: string, limit = 60) {
  return json<{ ticker: string; bars: Bar[] }>(`/v1/bars/${encodeURIComponent(ticker)}?limit=${limit}`);
}

export function getNotifications(limit = 50) {
  return json<{ n: number; events: SystemEvent[] }>(`/v1/notifications?limit=${limit}`);
}
