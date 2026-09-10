import { useEffect, useMemo, useRef, useState } from "react";
import { getClock, getNotifications, runScreener } from "./api";
import { BUILTIN_SCANS, COLUMNS, DEFAULT_COLUMNS, US_UNIVERSE } from "./catalog";
import { FilterBar } from "./FilterBar";
import { NotificationsPanel } from "./NotificationsPanel";
import { ScreenerTable } from "./ScreenerTable";
import { atrPct } from "./format";
import { loadColumns, loadScans, saveColumns, saveScans } from "./storage";
import type { Clock, ColumnId, Filter, SavedScan, ScreenerRow, SystemEvent } from "./types";
import "./styles.css";

const DEMO: ScreenerRow[] = [
  {
    security_id: 1,
    ticker: "NVDA",
    name: "NVIDIA Corp",
    exchange: "NASDAQ",
    market: "US",
    price: 128.4,
    avg_volume: 42_100_000,
    atr: 4.12,
    rel_vol_at: 2.41,
    rel_vol_at_sessions: 7,
    dollar_volume: 5_400_000_000,
    market_cap: 3_100_000_000_000,
    first5m_volume: 8_200_000,
    as_of: "2026-09-09",
  },
  {
    security_id: 2,
    ticker: "AAPL",
    name: "Apple Inc",
    exchange: "NASDAQ",
    market: "US",
    price: 227.15,
    avg_volume: 51_000_000,
    atr: 3.05,
    rel_vol_at: 1.18,
    rel_vol_at_sessions: 7,
    dollar_volume: 11_200_000_000,
    market_cap: 3_400_000_000_000,
    first5m_volume: 4_100_000,
    as_of: "2026-09-09",
  },
  {
    security_id: 3,
    ticker: "MSFT",
    name: "Microsoft Corp",
    exchange: "NASDAQ",
    market: "US",
    price: 428.9,
    avg_volume: 22_400_000,
    atr: 6.2,
    rel_vol_at: 1.62,
    rel_vol_at_sessions: 7,
    dollar_volume: 9_600_000_000,
    market_cap: 3_180_000_000_000,
    first5m_volume: 3_400_000,
    as_of: "2026-09-08",
  },
];

const MIN_W = 380;
const WIDTH_KEY = "pb.screener.width";
const SEEN_KEY = "pb.notifications.seen_ts";

export function App() {
  const demo = new URLSearchParams(window.location.search).has("demo");
  const [clock, setClock] = useState<Clock | null>(null);
  const [scanId, setScanId] = useState("us");
  const [filters, setFilters] = useState<Filter[]>(() => US_UNIVERSE.map((f) => ({ ...f })));
  const [saved, setSaved] = useState<SavedScan[]>(loadScans);
  const [columns, setColumns] = useState<ColumnId[]>(loadColumns);
  const [showCols, setShowCols] = useState(false);
  const [sort, setSort] = useState<ColumnId>("market_cap");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [q, setQ] = useState("");
  const [rows, setRows] = useState<ScreenerRow[]>(demo ? DEMO : []);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [layout, setLayout] = useState<"dock" | "full" | "collapsed">("dock");
  const [width, setWidth] = useState(() => loadWidth());
  const widthRef = useRef(width);
  const drag = useRef<{ startX: number; startW: number } | null>(null);
  const [dragging, setDragging] = useState(false);
  const [notesOpen, setNotesOpen] = useState(false);
  const [events, setEvents] = useState<SystemEvent[]>([]);
  const [seenTs, setSeenTs] = useState(() => localStorage.getItem(SEEN_KEY) ?? "");

  useEffect(() => {
    function loadOps() {
      getClock()
        .then(setClock)
        .catch(() => setClock(null));
      if (!demo) {
        getNotifications(50)
          .then((d) => setEvents(d.events ?? []))
          .catch(() => setEvents([]));
      }
    }
    loadOps();
    const t = window.setInterval(loadOps, 20_000);
    return () => window.clearInterval(t);
  }, [demo]);

  useEffect(() => {
    saveColumns(columns);
  }, [columns]);

  function applyScan(id: string) {
    const builtin = BUILTIN_SCANS.find((s) => s.id === id);
    const custom = saved.find((s) => s.id === id);
    setScanId(id);
    setDirty(false);
    if (builtin) {
      setFilters(builtin.filters.map((f) => ({ ...f })));
      setSort(builtin.sort);
      setSortDir("desc");
    }
    if (custom) {
      setFilters(custom.filters.map((f) => ({ ...f })));
      setSort(custom.sort as ColumnId);
      setSortDir(custom.sortDir);
      setColumns(custom.columns as ColumnId[]);
    }
  }

  async function run(nextFilters = filters) {
    if (demo) {
      setRows(DEMO);
      setErr(null);
      return;
    }
    setLoading(true);
    setErr(null);
    try {
      const apiSort =
        sort === "atr_pct" || sort === "ticker" || sort === "name" || sort === "exchange" || sort === "market"
          ? "market_cap"
          : sort;
      const data = await runScreener({
        preset: null,
        filters: nextFilters,
        limit: 500,
        sort: apiSort,
        sort_dir: sortDir,
      });
      setRows(data.rows);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
      setRows([]);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    const t = window.setTimeout(() => void run(filters), 280);
    return () => window.clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters, sort, sortDir]);

  function onFilters(next: Filter[]) {
    setFilters(next);
    setDirty(true);
    if (BUILTIN_SCANS.some((s) => s.id === scanId)) setScanId("custom");
  }

  const visible = useMemo(() => {
    const needle = q.trim().toLowerCase();
    let list = rows;
    if (needle) {
      list = list.filter(
        (r) =>
          r.ticker.toLowerCase().includes(needle) ||
          (r.name ?? "").toLowerCase().includes(needle),
      );
    }
    const dir = sortDir === "asc" ? 1 : -1;
    return [...list].sort((a, b) => {
      const av = value(a, sort);
      const bv = value(b, sort);
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      if (typeof av === "number" && typeof bv === "number") return (av - bv) * dir;
      return String(av).localeCompare(String(bv)) * dir;
    });
  }, [rows, q, sort, sortDir]);

  function toggleSort(key: ColumnId) {
    if (sort === key) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setSort(key);
      setSortDir(key === "ticker" || key === "name" ? "asc" : "desc");
    }
  }

  function persistScan() {
    const current = [...BUILTIN_SCANS, ...saved].find((s) => s.id === scanId);
    const name = window.prompt("Screener name", current?.name ?? "My screener");
    if (!name) return;
    const item: SavedScan = {
      id: scanId.startsWith("scan-") ? scanId : `scan-${Date.now()}`,
      name,
      filters: filters.map((f) => ({ ...f })),
      sort,
      sortDir,
      columns,
    };
    const next = [...saved.filter((s) => s.id !== item.id && s.name !== name), item];
    setSaved(next);
    saveScans(next);
    setScanId(item.id);
    setDirty(false);
  }

  function onHandleDown(e: React.MouseEvent) {
    e.preventDefault();
    drag.current = { startX: e.clientX, startW: widthRef.current };
    setDragging(true);
    function move(ev: MouseEvent) {
      if (!drag.current) return;
      const max = Math.max(MIN_W, window.innerWidth - 80);
      const next = Math.min(max, Math.max(MIN_W, drag.current.startW + (drag.current.startX - ev.clientX)));
      widthRef.current = next;
      setWidth(next);
    }
    function up() {
      drag.current = null;
      setDragging(false);
      localStorage.setItem(WIDTH_KEY, String(widthRef.current));
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
    }
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
  }

  const unread = events.filter((e) => !seenTs || e.ts > seenTs).length;
  const hasIngestError = events.some((e) => e.level === "error" || e.code.startsWith("universe."));

  function openNotes() {
    setNotesOpen(true);
    const newest = events[0]?.ts;
    if (newest) {
      localStorage.setItem(SEEN_KEY, newest);
      setSeenTs(newest);
    }
  }

  const scans = [
    ...(scanId === "custom" ? [{ id: "custom", name: "Custom" }] : []),
    ...BUILTIN_SCANS,
    ...saved,
  ];

  if (layout === "collapsed") {
    return (
      <div className="workspace">
        <div className="chart-stage" />
        <button className="screener-tab" type="button" onClick={() => setLayout("dock")}>
          Stock Screener
        </button>
      </div>
    );
  }

  return (
    <div className={`workspace ${layout === "full" ? "full" : ""}`}>
      {layout === "dock" ? <div className="chart-stage" /> : null}
      {layout === "dock" ? (
        <div
          className={`resize-handle ${dragging ? "dragging" : ""}`}
          onMouseDown={onHandleDown}
          title="Drag to resize"
        />
      ) : null}
      <aside
        className={`screener-panel ${layout === "full" ? "full" : ""}`}
        style={layout === "full" ? undefined : { width }}
      >
        {demo ? <div className="banner">Demo data. Live scan uses the warehouse API.</div> : null}
        {err ? (
          <div className="banner">
            {err.includes("no as_of")
              ? "Warehouse vacío: el API está up, pero todavía no hay sesiones ingestadas. Hay que correr el daily update."
              : err}{" "}
            {hasIngestError || events.length ? (
              <button type="button" className="link" onClick={openNotes}>
                ver notificaciones
              </button>
            ) : null}
          </div>
        ) : null}

        <div className="chrome">
          <button className="head-kicker" type="button">
            Stock Screener <Chevron />
          </button>
          <div className="win-btns">
            <button className="win-btn" type="button" title="Minimize" onClick={() => setLayout("collapsed")}>
              –
            </button>
            <button
              className="win-btn"
              type="button"
              title={layout === "full" ? "Restore" : "Maximize"}
              onClick={() => setLayout((v) => (v === "full" ? "dock" : "full"))}
            >
              {layout === "full" ? "❐" : "□"}
            </button>
            <button className="win-btn" type="button" title="Close" onClick={() => setLayout("collapsed")}>
              ×
            </button>
          </div>
        </div>

        <div className="head">
          <div className="head-row">
            <label className="head-name">
              <select value={scanId} onChange={(e) => applyScan(e.target.value)}>
                {scans.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
            </label>
            <button className={`save-btn ${dirty ? "" : "saved"}`} type="button" onClick={persistScan} title="Save">
              <Cloud />
              Save
            </button>
            <div className="head-tools">
              <button className="icon-btn bell-btn" type="button" title="System notifications" onClick={openNotes}>
                <Bell />
                {unread ? <span className="bell-badge">{unread > 9 ? "9+" : unread}</span> : null}
              </button>
              <button className="icon-btn" type="button" title="Settings" onClick={() => setShowCols((v) => !v)}>
                <Gear />
              </button>
            </div>
          </div>
        </div>

        <FilterBar filters={filters} onChange={onFilters} />

        <div className="table-bar">
          <span className="view-icons" aria-hidden>
            <button className="icon-btn on" type="button" title="Table">
              <TableIcon />
            </button>
          </span>
          <button className="overview-btn" type="button" onClick={() => setShowCols((v) => !v)}>
            <ColsIcon /> Overview
            <Chevron />
          </button>
          <input type="search" placeholder="Symbol" value={q} onChange={(e) => setQ(e.target.value)} />
          <span className="table-meta">
            {loading || clock?.ingest_running ? "Updating…" : `${visible.length} symbols`}
          </span>
          <div className="table-bar-right">
            <button className="icon-btn" type="button" title="Refresh" onClick={() => void run()}>
              <Refresh />
            </button>
            <button
              className="icon-btn"
              type="button"
              title="Fullscreen"
              onClick={() => setLayout((v) => (v === "full" ? "dock" : "full"))}
            >
              <Expand />
            </button>
            {showCols ? (
              <div className="cols-pop">
                {COLUMNS.map((c) => (
                  <label key={c.id}>
                    <input
                      type="checkbox"
                      checked={columns.includes(c.id)}
                      disabled={c.id === "ticker"}
                      onChange={() =>
                        setColumns((prev) =>
                          prev.includes(c.id) ? prev.filter((x) => x !== c.id) : [...prev, c.id],
                        )
                      }
                    />
                    {c.label}
                  </label>
                ))}
                <button type="button" className="link" onClick={() => setColumns([...DEFAULT_COLUMNS])}>
                  Reset
                </button>
              </div>
            ) : null}
          </div>
        </div>

        <ScreenerTable
          rows={visible}
          columns={columns}
          sort={sort}
          sortDir={sortDir}
          selected={selected}
          onSort={toggleSort}
          onSelect={setSelected}
          onAddColumn={() => setShowCols(true)}
        />
        <NotificationsPanel events={events} open={notesOpen} onClose={() => setNotesOpen(false)} />
      </aside>
    </div>
  );
}

function loadWidth(): number {
  const n = Number(localStorage.getItem(WIDTH_KEY));
  if (Number.isFinite(n) && n >= MIN_W) return n;
  return Math.max(MIN_W, Math.round(window.innerWidth * 0.42));
}

function value(row: ScreenerRow, col: ColumnId): string | number | null {
  if (col === "atr_pct") return atrPct(row.atr, row.price);
  const v = row[col as keyof ScreenerRow];
  if (typeof v === "number" || typeof v === "string") return v;
  return v ?? null;
}

function Chevron() {
  return (
    <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden>
      <path d="M2 3.5 L5 6.5 L8 3.5" fill="none" stroke="currentColor" strokeWidth="1.4" />
    </svg>
  );
}

function Cloud() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden>
      <path
        d="M4.5 12h7.2A2.8 2.8 0 0 0 14 9.4c0-1.4-1-2.6-2.4-2.8A3.3 3.3 0 0 0 5.2 5.6 2.7 2.7 0 0 0 2.5 8.3 2.2 2.2 0 0 0 4.5 12Z"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.3"
      />
      <path d="M8 10.5V6.8M8 6.8 6.4 8.3M8 6.8 9.6 8.3" fill="none" stroke="currentColor" strokeWidth="1.3" />
    </svg>
  );
}

function Bell() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden>
      <path
        d="M8 2.2a3.2 3.2 0 0 0-3.2 3.2v1.6c0 .7-.3 1.4-.8 1.9L3.2 10h9.6l-.8-1.1c-.5-.5-.8-1.2-.8-1.9V5.4A3.2 3.2 0 0 0 8 2.2Zm-2 10.3a2 2 0 0 0 4 0"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.3"
      />
    </svg>
  );
}

function Gear() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden>
      <path
        d="M8 10.2A2.2 2.2 0 1 0 8 5.8a2.2 2.2 0 0 0 0 4.4Zm6-2.2c0-.4-.3-.8-.7-1l-1-.3.2-1.1c.1-.4-.1-.8-.5-1L10.7 3.4c-.4-.2-.8-.1-1.1.2l-.8.8-.8-.8C7.7 3.3 7.3 3.2 6.9 3.4L5.6 4.6c-.4.2-.6.6-.5 1l.2 1.1-1 .3c-.4.2-.7.6-.7 1s.3.8.7 1l1 .3-.2 1.1c-.1.4.1.8.5 1l1.3 1.2c.4.2.8.1 1.1-.2l.8-.8.8.8c.3.3.7.4 1.1.2l1.3-1.2c.4-.2.6-.6.5-1l-.2-1.1 1-.3c.4-.2.7-.6.7-1Z"
        fill="currentColor"
      />
    </svg>
  );
}

function TableIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden>
      <rect x="2" y="3" width="12" height="10" rx="1.5" fill="none" stroke="currentColor" strokeWidth="1.3" />
      <path d="M2 7h12M6 3v10" fill="none" stroke="currentColor" strokeWidth="1.3" />
    </svg>
  );
}

function ColsIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden>
      <path d="M2 2h2.5v10H2zM6 2h2.5v10H6zM10 2h2.5v10H10z" fill="currentColor" />
    </svg>
  );
}

function Refresh() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden>
      <path
        d="M13 8a5 5 0 1 1-1.4-3.5"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.4"
      />
      <path d="M13 3.5V7H9.5" fill="none" stroke="currentColor" strokeWidth="1.4" />
    </svg>
  );
}

function Expand() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden>
      <path d="M3 6V3h3M10 3h3v3M13 10v3h-3M6 13H3v-3" fill="none" stroke="currentColor" strokeWidth="1.4" />
    </svg>
  );
}
