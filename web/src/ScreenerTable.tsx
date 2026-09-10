import { COLUMNS } from "./catalog";
import * as fmt from "./format";
import type { ColumnId, ScreenerRow } from "./types";

type Props = {
  rows: ScreenerRow[];
  columns: ColumnId[];
  sort: ColumnId;
  sortDir: "asc" | "desc";
  selected: string | null;
  onSort: (key: ColumnId) => void;
  onSelect: (ticker: string) => void;
  onAddColumn: () => void;
};

function cell(row: ScreenerRow, col: ColumnId): string {
  switch (col) {
    case "ticker":
      return row.ticker;
    case "name":
      return row.name || "—";
    case "exchange":
      return row.exchange || "—";
    case "market":
      return row.market || "—";
    case "as_of":
      return row.as_of || "—";
    case "price":
      return row.price == null ? "—" : `${fmt.price(row.price)} USD`;
    case "rel_vol_at":
      return fmt.ratio(row.rel_vol_at);
    case "rel_vol_at_sessions":
      return fmt.integer(row.rel_vol_at_sessions);
    case "avg_volume":
      return fmt.compact(row.avg_volume, 0);
    case "dollar_volume":
      return fmt.compact(row.dollar_volume, 1);
    case "atr":
      return fmt.price(row.atr);
    case "atr_pct":
      return fmt.pct(fmt.atrPct(row.atr, row.price));
    case "market_cap":
      return fmt.compact(row.market_cap, 1);
    case "first5m_volume":
      return fmt.compact(row.first5m_volume, 0);
    default:
      return "—";
  }
}

export function ScreenerTable({
  rows,
  columns,
  sort,
  sortDir,
  selected,
  onSort,
  onSelect,
  onAddColumn,
}: Props) {
  if (!rows.length) {
    return <div className="empty">No symbols match this scan.</div>;
  }
  return (
    <div className="table-wrap">
      <table className="screener">
        <thead>
          <tr>
            {columns.map((id) => {
              const meta = COLUMNS.find((c) => c.id === id);
              const arrow = sort === id ? (sortDir === "asc" ? " ↑" : " ↓") : "";
              return (
                <th
                  key={id}
                  className={`${id === "ticker" ? "sym" : ""} ${sort === id ? "sorted" : ""}`}
                  style={{ textAlign: meta?.align === "right" ? "right" : "left" }}
                  onClick={() => onSort(id)}
                >
                  {meta?.label ?? id}
                  {arrow}
                  {id === "ticker" ? <span className="sym-count">{rows.length}</span> : null}
                </th>
              );
            })}
            <th style={{ width: 36 }} onClick={onAddColumn}>
              +
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={row.security_id}
              className={selected === row.ticker ? "selected" : ""}
              onClick={() => onSelect(row.ticker)}
            >
              {columns.map((id) => {
                const meta = COLUMNS.find((c) => c.id === id);
                const right = meta?.align === "right";
                return (
                  <td
                    key={id}
                    className={`${id === "ticker" ? "sym" : ""} ${right ? "num" : ""}`}
                  >
                    {cell(row, id)}
                  </td>
                );
              })}
              <td />
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
