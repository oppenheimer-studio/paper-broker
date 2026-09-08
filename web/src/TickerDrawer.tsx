import { useEffect, useMemo, useState } from "react";
import { getBars } from "./api";
import * as fmt from "./format";
import type { Bar, ScreenerRow } from "./types";

type Props = {
  row: ScreenerRow;
  onClose: () => void;
};

export function TickerDrawer({ row, onClose }: Props) {
  const [bars, setBars] = useState<Bar[]>([]);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setErr(null);
    getBars(row.ticker, 60)
      .then((d) => {
        if (alive) setBars(d.bars ?? []);
      })
      .catch((e: Error) => {
        if (alive) setErr(e.message);
      });
    return () => {
      alive = false;
    };
  }, [row.ticker]);

  const path = useMemo(() => sparkPath(bars), [bars]);

  return (
    <aside className="drawer">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <h2>{row.ticker}</h2>
          <div className="muted">
            {row.name} · {row.exchange || "—"}
          </div>
        </div>
        <button className="btn btn-ghost" type="button" onClick={onClose}>
          Close
        </button>
      </div>
      <svg className="spark" viewBox="0 0 300 90" preserveAspectRatio="none">
        <path d={path} fill="none" stroke="#2962ff" strokeWidth="1.5" />
      </svg>
      {err ? <div className="err">{err}</div> : null}
      <Stat label="Price" value={fmt.price(row.price)} />
      <Stat label="Rel Vol" value={fmt.ratio(row.rel_vol_at)} />
      <Stat label="Rel Vol sessions" value={fmt.integer(row.rel_vol_at_sessions)} />
      <Stat label="Avg volume" value={fmt.compact(row.avg_volume)} />
      <Stat label="Dollar volume" value={fmt.compact(row.dollar_volume)} />
      <Stat label="ATR" value={fmt.price(row.atr)} />
      <Stat label="ATR %" value={fmt.pct(fmt.atrPct(row.atr, row.price))} />
      <Stat label="Market cap" value={fmt.compact(row.market_cap)} />
      <Stat label="First 5m volume" value={fmt.compact(row.first5m_volume)} />
    </aside>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
      <span className="muted">{label}</span>
      <span style={{ fontFamily: "var(--mono)" }}>{value}</span>
    </div>
  );
}

function sparkPath(bars: Bar[]): string {
  if (!bars.length) return "";
  const closes = bars.map((b) => b.close);
  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const span = max - min || 1;
  return closes
    .map((c, i) => {
      const x = (i / Math.max(closes.length - 1, 1)) * 300;
      const y = 90 - ((c - min) / span) * 80 - 5;
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`;
    })
    .join(" ");
}
