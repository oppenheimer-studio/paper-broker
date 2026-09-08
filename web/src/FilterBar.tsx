import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  FIELDS,
  LOOKBACKS,
  OPS,
  PINNED,
  WINDOWS,
  chipLabel,
  defaultFilter,
  fieldMeta,
} from "./catalog";
import type { Filter, FilterOp, ScreenerField } from "./types";

type Props = {
  filters: Filter[];
  onChange: (next: Filter[]) => void;
};

export function FilterBar({ filters, onChange }: Props) {
  const [openField, setOpenField] = useState<ScreenerField | null>(null);
  const [addOpen, setAddOpen] = useState(false);
  const [q, setQ] = useState("");
  const bankRef = useRef<HTMLDivElement>(null);
  const chipRefs = useRef<Partial<Record<ScreenerField, HTMLButtonElement | null>>>({});
  const addRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    function onDoc(e: MouseEvent) {
      const t = e.target as Node;
      if (bankRef.current?.contains(t)) return;
      if ((t as HTMLElement).closest?.(".tv-float")) return;
      setOpenField(null);
      setAddOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  const extra = filters.filter((f) => !PINNED.includes(f.field));
  const chips: ScreenerField[] = [...PINNED, ...extra.map((f) => f.field)];

  function active(id: ScreenerField): Filter | undefined {
    return filters.find((f) => f.field === id);
  }

  function upsert(next: Filter) {
    const rest = filters.filter((f) => f.field !== next.field);
    onChange([...rest, next]);
  }

  function clear(id: ScreenerField) {
    onChange(filters.filter((f) => f.field !== id));
    if (openField === id) setOpenField(null);
  }

  function openChip(id: ScreenerField) {
    setAddOpen(false);
    if (openField === id) {
      setOpenField(null);
      return;
    }
    setOpenField(id);
    if (!active(id)) upsert(defaultFilter(id));
  }

  const catalog = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return FIELDS.filter(
      (f) =>
        !needle ||
        f.label.toLowerCase().includes(needle) ||
        f.short.toLowerCase().includes(needle) ||
        f.group.toLowerCase().includes(needle),
    );
  }, [q]);

  const groups = [...new Set(catalog.map((f) => f.group))];
  const openValue = openField
    ? (active(openField) ?? defaultFilter(openField))
    : null;

  return (
    <div className="filter-wrap" ref={bankRef}>
      <div className="filter-bank">
        {chips.map((id) => {
          const f = active(id);
          const meta = fieldMeta(id);
          const on = Boolean(f);
          return (
            <div key={id} className="chip-wrap">
              <button
                type="button"
                ref={(el) => {
                  chipRefs.current[id] = el;
                }}
                className={`chip ${on ? "chip-on" : ""} ${openField === id ? "chip-open" : ""}`}
                onClick={() => openChip(id)}
              >
                <span>{on && f ? chipLabel(f) : meta.short}</span>
                {on ? (
                  <span
                    className="chip-x"
                    onClick={(e) => {
                      e.stopPropagation();
                      clear(id);
                    }}
                    role="button"
                    aria-label={`Clear ${meta.short}`}
                  >
                    ×
                  </span>
                ) : (
                  <Chevron />
                )}
              </button>
            </div>
          );
        })}

        <div className="chip-wrap">
          <button
            ref={addRef}
            type="button"
            className="chip chip-icon"
            title="Add new filter"
            onClick={() => {
              setOpenField(null);
              setAddOpen((v) => !v);
              setQ("");
            }}
          >
            +
          </button>
        </div>
      </div>

      {openField && openValue ? (
        <FloatMenu anchor={chipRefs.current[openField] ?? null}>
          <FilterPopover
            value={openValue}
            onChange={upsert}
            onReset={() => upsert(defaultFilter(openField))}
            onDelete={() => clear(openField)}
          />
        </FloatMenu>
      ) : null}

      {addOpen ? (
        <FloatMenu anchor={addRef.current} width={260}>
          <div className="add-menu">
            <input
              autoFocus
              className="menu-search"
              placeholder="Search"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
            {groups.map((g) => (
              <div key={g}>
                <div className="menu-group">
                  {g}
                  <span>{catalog.filter((f) => f.group === g).length}</span>
                </div>
                {catalog
                  .filter((f) => f.group === g)
                  .map((f) => (
                    <button
                      key={f.id}
                      type="button"
                      className="menu-item"
                      onClick={() => {
                        openChip(f.id);
                        setAddOpen(false);
                      }}
                    >
                      <span>{f.label}</span>
                      {active(f.id) ? <span className="dot" /> : null}
                    </button>
                  ))}
              </div>
            ))}
            {!catalog.length ? <div className="menu-empty">No filters</div> : null}
          </div>
        </FloatMenu>
      ) : null}
    </div>
  );
}

function FloatMenu({
  anchor,
  children,
  width,
}: {
  anchor: HTMLElement | null;
  children: React.ReactNode;
  width?: number;
}) {
  const [pos, setPos] = useState({ top: 0, left: 0 });

  useLayoutEffect(() => {
    if (!anchor) return;
    function place() {
      if (!anchor) return;
      const r = anchor.getBoundingClientRect();
      const w = width ?? 280;
      const left = Math.min(r.left, window.innerWidth - w - 8);
      setPos({ top: r.bottom + 6, left: Math.max(8, left) });
    }
    place();
    window.addEventListener("resize", place);
    return () => window.removeEventListener("resize", place);
  }, [anchor, width]);

  return createPortal(
    <div className="tv-float menu" style={{ top: pos.top, left: pos.left, width: width ?? 280 }}>
      {children}
    </div>,
    document.body,
  );
}

function FilterPopover({
  value,
  onChange,
  onReset,
  onDelete,
}: {
  value: Filter;
  onChange: (f: Filter) => void;
  onReset: () => void;
  onDelete: () => void;
}) {
  const meta = fieldMeta(value.field);
  return (
    <div className="popover">
      <div className="pop-head">
        <div>
          <div className="pop-title">{meta.label}</div>
          <div className="pop-hint">{meta.hint}</div>
        </div>
        <div className="pop-actions">
          <button type="button" className="link" onClick={onReset}>
            Reset
          </button>
          <button type="button" className="icon-btn" onClick={onDelete} aria-label="Remove">
            ⌫
          </button>
        </div>
      </div>

      {meta.lookback ? (
        <div className="pop-params">
          <select
            value={value.lookback ?? 14}
            onChange={(e) => onChange({ ...value, lookback: Number(e.target.value) })}
          >
            {LOOKBACKS.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
          <select defaultValue="1d" disabled>
            <option value="1d">1 day</option>
          </select>
        </div>
      ) : null}

      {meta.window ? (
        <div className="pop-params">
          <select
            value={value.window_minutes ?? 5}
            onChange={(e) => onChange({ ...value, window_minutes: Number(e.target.value) })}
          >
            {WINDOWS.map((n) => (
              <option key={n} value={n}>
                {n} min
              </option>
            ))}
          </select>
        </div>
      ) : null}

      <label className="pop-field">
        <select
          value={value.op}
          onChange={(e) => onChange({ ...value, op: e.target.value as FilterOp })}
        >
          {OPS.map((op) => (
            <option key={op.id} value={op.id}>
              {op.label}
            </option>
          ))}
        </select>
      </label>

      <label className="pop-field">
        <select defaultValue="value" disabled>
          <option value="value">Value</option>
        </select>
      </label>

      <label className="pop-field">
        {meta.valueKind === "text" ? (
          <input
            type="text"
            value={String(value.value)}
            onChange={(e) => onChange({ ...value, value: e.target.value })}
          />
        ) : (
          <input
            type="number"
            step="any"
            value={value.value}
            onChange={(e) => onChange({ ...value, value: Number(e.target.value) })}
          />
        )}
      </label>

      {meta.presets?.length ? (
        <div className="presets">
          {meta.presets.map((p) => (
            <button
              key={p}
              type="button"
              className={`preset ${value.value === p ? "on" : ""}`}
              onClick={() => onChange({ ...value, value: p })}
            >
              {fieldMeta(value.field).unit && p < 1000 ? String(p) : compactPreset(p)}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function compactPreset(n: number): string {
  if (n >= 1e9) return `${n / 1e9}B`;
  if (n >= 1e6) return `${n / 1e6}M`;
  if (n >= 1e3) return `${n / 1e3}K`;
  return String(n);
}

function Chevron() {
  return (
    <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden>
      <path d="M2 3.5 L5 6.5 L8 3.5" fill="none" stroke="currentColor" strokeWidth="1.4" />
    </svg>
  );
}
