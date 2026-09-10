from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

import duckdb
import pandas as pd

from paper_broker.domain.indicators import rel_vol_at, sma, wilder_atr
from paper_broker.domain.models import (
    AssetType,
    Clock,
    CorporateAction,
    DailyBar,
    FilterOp,
    IngestRun,
    IngestStatus,
    MinuteOpenBar,
    SystemEvent,
    QueryRequest,
    ScreenerRequest,
    ScreenerRow,
    Security,
    SecurityDraft,
)
from paper_broker.domain.screener_spec import OPS_SQL, resolve_filters
from paper_broker.logging import get_logger

log = get_logger("warehouse")

ALLOWED_TABLES = {
    "securities": {
        "security_id",
        "ticker",
        "name",
        "exchange",
        "asset_type",
        "listing_status",
        "market",
        "sector",
        "industry",
        "shares_outstanding",
    },
    "daily_data": {"security_id", "date", "open", "high", "low", "close", "adj_close", "volume", "source"},
    "minute_open": {
        "security_id",
        "date",
        "window_minutes",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "source",
    },
    "derived_daily_data": {
        "security_id",
        "date",
        "price",
        "avg_volume",
        "atr",
        "first5m_volume",
        "rel_vol_at",
        "rel_vol_at_sessions",
        "dollar_volume",
        "market_cap",
        "avg_volume_lookback",
        "atr_lookback",
        "rel_vol_lookback",
        "window_minutes",
    },
    "daily_market": {"date", "vix", "us10y", "us2y", "tbill", "dxy", "oil", "gold"},
    "corporate_actions": {
        "security_id",
        "date",
        "action",
        "value",
        "numerator",
        "denominator",
        "source",
    },
    "ingest_runs": {"run_id", "as_of", "status", "started_at", "finished_at", "notes", "rows_upserted"},
    "system_events": {"id", "ts", "level", "source", "code", "title", "detail", "data"},
}

ALLOWED_AGGS = {"avg", "sum", "min", "max", "count"}
ALLOWED_OPS = {"eq": "=", "neq": "<>", "gt": ">", "gte": ">=", "lt": "<", "lte": "<=", "in": "in"}


def _empty(columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame(columns=columns)


class DuckDbWarehouse:
    def __init__(self, lake: Path) -> None:
        self.lake = Path(lake)
        self.lake.mkdir(parents=True, exist_ok=True)
        self._con = duckdb.connect(str(self.lake / "catalog.duckdb"))
        self._events_lock = Lock()

    def close(self) -> None:
        self._con.close()

    def _path(self, *parts: str) -> Path:
        return self.lake.joinpath(*parts)

    def _read_parquet(self, rel: str, columns: list[str]) -> pd.DataFrame:
        path = self._path(rel)
        if path.is_file():
            return pd.read_parquet(path)
        glob = self.lake / rel
        files = list(glob.parent.glob(glob.name)) if "*" in rel else list(path.rglob("*.parquet"))
        if not files:
            return _empty(columns)
        return pd.read_parquet(files)

    def _write_hive_upsert(self, table: str, df: pd.DataFrame, keys: list[str]) -> int:
        if df.empty:
            return 0
        written = 0
        df = df.copy()
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        folder = self._path(table)
        folder.mkdir(parents=True, exist_ok=True)
        for day, part in df.groupby("date", sort=True):
            dest = folder / f"{day}.parquet"
            incoming = part.reset_index(drop=True)
            if dest.exists():
                old = pd.read_parquet(dest)
                incoming = pd.concat([old, incoming], ignore_index=True)
                incoming = incoming.drop_duplicates(keys, keep="last")
            incoming["date"] = incoming["date"].astype(str)
            incoming.to_parquet(dest, index=False)
            written += len(part)
        return written

    def _read_hive(self, table: str, columns: list[str]) -> pd.DataFrame:
        root = self._path(table)
        files = list(root.glob("*.parquet"))
        if not files:
            return _empty(columns)
        frames = []
        for path in files:
            part = pd.read_parquet(path)
            frames.append(part)
        df = pd.concat(frames, ignore_index=True)
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"]).dt.date
        return df

    def upsert_securities(self, drafts: list[SecurityDraft]) -> list[Security]:
        cols = list(ALLOWED_TABLES["securities"])
        existing = self._read_parquet("securities.parquet", cols)
        by_ticker = {}
        next_id = 1
        if not existing.empty:
            next_id = int(existing["security_id"].max()) + 1
            for _, row in existing.iterrows():
                by_ticker[str(row["ticker"])] = row.to_dict()
        for d in drafts:
            ticker = d.ticker.upper()
            if ticker in by_ticker:
                row = by_ticker[ticker]
                row["name"] = d.name
                row["exchange"] = d.exchange
                row["asset_type"] = d.asset_type.value
                row["listing_status"] = d.listing_status
                row["market"] = d.market
            else:
                by_ticker[ticker] = {
                    "security_id": next_id,
                    "ticker": ticker,
                    "name": d.name,
                    "exchange": d.exchange,
                    "asset_type": d.asset_type.value,
                    "listing_status": d.listing_status,
                    "market": d.market,
                    "sector": None,
                    "industry": None,
                    "shares_outstanding": None,
                }
                next_id += 1
        out = pd.DataFrame(list(by_ticker.values()))
        out.to_parquet(self._path("securities.parquet"), index=False)
        log.info("securities_upserted", n=len(out), new=len(drafts))
        return [self._security_from_row(r) for r in out.to_dict(orient="records")]

    def _security_from_row(self, r: dict[str, Any]) -> Security:
        return Security(
            security_id=int(r["security_id"]),
            ticker=str(r["ticker"]),
            name=str(r.get("name") or r["ticker"]),
            exchange=str(r.get("exchange") or ""),
            asset_type=AssetType(str(r.get("asset_type") or "stock")),
            listing_status=str(r.get("listing_status") or "active"),
            market=str(r.get("market") or "US"),
            sector=r.get("sector"),
            industry=r.get("industry"),
        )

    def list_securities(self, market: str | None = "US") -> list[Security]:
        df = self._read_parquet("securities.parquet", list(ALLOWED_TABLES["securities"]))
        if df.empty:
            return []
        if market:
            df = df[df["market"] == market]
        return [self._security_from_row(r) for r in df.to_dict(orient="records")]

    def security_by_ticker(self, ticker: str) -> Security | None:
        ticker = ticker.upper()
        for s in self.list_securities(market=None):
            if s.ticker == ticker:
                return s
        return None

    def ticker_map(self) -> dict[str, int]:
        return {s.ticker: s.security_id for s in self.list_securities(market=None)}

    def id_map(self) -> dict[int, Security]:
        return {s.security_id: s for s in self.list_securities(market=None)}

    def rank_security_ids(self) -> list[int]:
        secs = self._read_parquet("securities.parquet", list(ALLOWED_TABLES["securities"]))
        if secs.empty:
            return []
        derived = self._read_hive("derived_daily_data", list(ALLOWED_TABLES["derived_daily_data"]))
        daily = self._read_hive("daily_data", list(ALLOWED_TABLES["daily_data"]))
        mcap = pd.Series(dtype="float64")
        dvol = pd.Series(dtype="float64")
        if not derived.empty:
            last = derived.sort_values("date").groupby("security_id").tail(1)
            mcap = last.set_index("security_id")["market_cap"]
            dvol = last.set_index("security_id")["dollar_volume"]
        if not daily.empty and (dvol.empty or dvol.isna().all()):
            last_d = daily.sort_values("date").groupby("security_id").tail(1)
            dvol = last_d.set_index("security_id")["close"] * last_d.set_index("security_id")["volume"]
        ranked = secs.copy()
        ranked["mcap"] = ranked["security_id"].map(mcap)
        ranked["dvol"] = ranked["security_id"].map(dvol)
        ranked = ranked.sort_values(["mcap", "dvol"], ascending=False, na_position="last")
        return [int(x) for x in ranked["security_id"].tolist()]

    def dates_with_eod(self, security_id: int, start: date, end: date) -> set[date]:
        df = self._read_hive("daily_data", list(ALLOWED_TABLES["daily_data"]))
        if df.empty:
            return set()
        df["date"] = pd.to_datetime(df["date"]).dt.date
        hit = df[(df["security_id"] == security_id) & (df["date"] >= start) & (df["date"] <= end)]
        return set(hit["date"].tolist())

    def dates_with_minute_open(
        self, security_id: int, start: date, end: date, window_minutes: int
    ) -> set[date]:
        df = self._read_hive("minute_open", list(ALLOWED_TABLES["minute_open"]))
        if df.empty:
            return set()
        df["date"] = pd.to_datetime(df["date"]).dt.date
        hit = df[
            (df["security_id"] == security_id)
            & (df["window_minutes"] == window_minutes)
            & (df["date"] >= start)
            & (df["date"] <= end)
        ]
        return set(hit["date"].tolist())

    def write_daily_bars(self, bars: list[DailyBar]) -> int:
        if not bars:
            return 0
        df = pd.DataFrame([b.model_dump() for b in bars])
        n = self._write_hive_upsert("daily_data", df, ["security_id", "date"])
        log.info("daily_bars_written", n=n)
        return n

    def write_minute_open(self, bars: list[MinuteOpenBar]) -> int:
        if not bars:
            return 0
        df = pd.DataFrame([b.model_dump() for b in bars])
        n = self._write_hive_upsert("minute_open", df, ["security_id", "date", "window_minutes"])
        log.info("minute_open_written", n=n)
        return n

    def write_corporate_actions(self, rows: list[CorporateAction]) -> int:
        if not rows:
            return 0
        df = pd.DataFrame([r.model_dump() for r in rows])
        n = self._write_hive_upsert("corporate_actions", df, ["security_id", "date", "action"])
        log.info("corporate_actions_written", n=n)
        return n

    def rewrite_derived(
        self, as_of: date, avg_n: int, atr_n: int, relvol_n: int, window_minutes: int
    ) -> int:
        lookback_days = max(avg_n, atr_n, relvol_n) + 5
        daily = self._read_hive("daily_data", list(ALLOWED_TABLES["daily_data"]))
        if daily.empty:
            return 0
        daily["date"] = pd.to_datetime(daily["date"]).dt.date
        daily = daily[daily["date"] <= as_of]
        minute = self._read_hive("minute_open", list(ALLOWED_TABLES["minute_open"]))
        if not minute.empty:
            minute["date"] = pd.to_datetime(minute["date"]).dt.date
            minute = minute[
                (minute["date"] <= as_of) & (minute["window_minutes"] == window_minutes)
            ]
        secs = self._read_parquet("securities.parquet", list(ALLOWED_TABLES["securities"]))
        shares = {}
        if not secs.empty:
            shares = {
                int(r["security_id"]): r.get("shares_outstanding")
                for r in secs.to_dict(orient="records")
            }
        rows: list[dict[str, Any]] = []
        for sid, g in daily.groupby("security_id"):
            g = g.sort_values("date").tail(lookback_days)
            if as_of not in set(g["date"]):
                continue
            g = g.reset_index(drop=True)
            high = g["high"].astype(float)
            low = g["low"].astype(float)
            close = g["close"].astype(float)
            vol = g["volume"].astype(float)
            atr_s = wilder_atr(high, low, close, atr_n)
            avg_s = sma(vol, avg_n)
            today = g[g["date"] == as_of].iloc[-1]
            price = float(today["close"])
            dollar = price * float(today["volume"])
            sh = shares.get(int(sid))
            mcap = float(sh) * price if sh and pd.notna(sh) else None
            first5 = None
            prior_open: list[float] = []
            if not minute.empty:
                m = minute[minute["security_id"] == sid].sort_values("date")
                m = m[m["date"] <= as_of]
                if not m.empty:
                    last = m.iloc[-1]
                    if last["date"] == as_of:
                        first5 = float(last["volume"])
                    prior = m[m["date"] < as_of].tail(relvol_n)
                    prior_open = [float(x) for x in prior["volume"].tolist()]
            rv, n_sess = rel_vol_at(first5, prior_open)
            rows.append(
                {
                    "security_id": int(sid),
                    "date": as_of,
                    "price": price,
                    "avg_volume": float(avg_s.iloc[-1]) if pd.notna(avg_s.iloc[-1]) else None,
                    "atr": float(atr_s.iloc[-1]) if pd.notna(atr_s.iloc[-1]) else None,
                    "first5m_volume": first5,
                    "rel_vol_at": rv,
                    "rel_vol_at_sessions": n_sess,
                    "dollar_volume": dollar,
                    "market_cap": mcap,
                    "avg_volume_lookback": avg_n,
                    "atr_lookback": atr_n,
                    "rel_vol_lookback": relvol_n,
                    "window_minutes": window_minutes,
                }
            )
        if not rows:
            return 0
        df = pd.DataFrame(rows)
        folder = self._path("derived_daily_data")
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / f"{as_of.isoformat()}.parquet"
        df["date"] = df["date"].astype(str)
        df.to_parquet(dest, index=False)
        log.info("derived_rewritten", as_of=str(as_of), n=len(df))
        return len(df)

    def _runs(self) -> pd.DataFrame:
        return self._read_parquet("meta/ingest_runs.parquet", list(ALLOWED_TABLES["ingest_runs"]))

    def _save_runs(self, df: pd.DataFrame) -> None:
        path = self._path("meta")
        path.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path / "ingest_runs.parquet", index=False)

    def last_success_as_of(self) -> date | None:
        df = self._runs()
        if df.empty:
            return None
        ok = df[df["status"] == IngestStatus.SUCCESS.value]
        if ok.empty:
            return None
        ok = ok.copy()
        ok["as_of"] = pd.to_datetime(ok["as_of"]).dt.date
        return max(ok["as_of"])

    def start_run(self, as_of: date, notes: str = "") -> IngestRun:
        run = IngestRun(
            run_id=str(uuid.uuid4()),
            as_of=as_of,
            status=IngestStatus.RUNNING,
            started_at=datetime.now(timezone.utc),
            notes=notes,
        )
        df = self._runs()
        row = pd.DataFrame([run.model_dump()])
        df = pd.concat([df, row], ignore_index=True) if not df.empty else row
        self._save_runs(df)
        log.info("ingest_run_started", run_id=run.run_id, as_of=str(as_of))
        return run

    def finish_run(self, run_id: str, status: IngestStatus, notes: str, rows_upserted: int) -> None:
        df = self._runs()
        if df.empty:
            return
        mask = df["run_id"] == run_id
        df.loc[mask, "status"] = status.value
        df.loc[mask, "notes"] = notes
        df.loc[mask, "rows_upserted"] = rows_upserted
        df.loc[mask, "finished_at"] = datetime.now(timezone.utc)
        self._save_runs(df)
        log.info("ingest_run_finished", run_id=run_id, status=status.value, rows=rows_upserted, notes=notes)

    def clock(self, expected: date | None, pending: list[date], ingest_running: bool) -> Clock:
        last = self.last_success_as_of()
        return Clock(
            as_of=last,
            last_success=last,
            expected=expected,
            pending_sessions=pending,
            ingest_running=ingest_running,
        )

    def _events_df(self) -> pd.DataFrame:
        return self._read_parquet("meta/system_events.parquet", list(ALLOWED_TABLES["system_events"]))

    def _save_events(self, df: pd.DataFrame) -> None:
        path = self._path("meta")
        path.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path / "system_events.parquet", index=False)

    def append_event(
        self,
        *,
        level: str,
        source: str,
        code: str,
        title: str,
        detail: str = "",
        data: dict[str, Any] | None = None,
    ) -> SystemEvent:
        event = SystemEvent(
            id=str(uuid.uuid4()),
            ts=datetime.now(timezone.utc),
            level=level,
            source=source,
            code=code,
            title=title,
            detail=detail or "",
            data=json.dumps(data or {}, default=str),
        )
        with self._events_lock:
            df = self._events_df()
            row = pd.DataFrame([event.model_dump()])
            df = pd.concat([df, row], ignore_index=True) if not df.empty else row
            if len(df) > 2000:
                df = df.tail(2000).reset_index(drop=True)
            self._save_events(df)
        log.info("system_event", level=level, code=code, title=title)
        return event

    def list_events(self, limit: int = 50) -> list[SystemEvent]:
        df = self._events_df()
        if df.empty:
            return []
        df = df.copy()
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
        df = df.sort_values("ts", ascending=False).head(max(1, limit))
        out: list[SystemEvent] = []
        for r in df.to_dict(orient="records"):
            ts = r["ts"]
            if hasattr(ts, "to_pydatetime"):
                ts = ts.to_pydatetime()
            out.append(
                SystemEvent(
                    id=str(r["id"]),
                    ts=ts,
                    level=str(r["level"]),
                    source=str(r["source"]),
                    code=str(r["code"]),
                    title=str(r["title"]),
                    detail=str(r.get("detail") or ""),
                    data=str(r.get("data") or "{}"),
                )
            )
        return out

    def query(self, req: QueryRequest) -> list[dict[str, Any]]:
        if req.table not in ALLOWED_TABLES:
            raise ValueError(f"table not allowed: {req.table}")
        allowed = ALLOWED_TABLES[req.table]
        ident = []
        for item in req.select:
            if isinstance(item, str):
                if item != "*" and item not in allowed:
                    raise ValueError(f"column not allowed: {item}")
                ident.append("*" if item == "*" else self._ident(item))
            elif isinstance(item, dict):
                agg = str(item.get("agg", "")).lower()
                field = str(item.get("field", ""))
                alias = str(item.get("as", f"{agg}_{field}"))
                if agg not in ALLOWED_AGGS or field not in allowed:
                    raise ValueError("bad aggregation")
                ident.append(f"{agg}({self._ident(field)}) AS {self._ident(alias)}")
            else:
                raise ValueError("bad select")
        select_sql = ", ".join(ident) if ident else "*"
        rel = self._relation_sql(req.table)
        sql = f"SELECT {select_sql} FROM {rel}"
        params: list[Any] = []
        clauses = []
        for w in req.where:
            if w.field not in allowed:
                raise ValueError(f"column not allowed: {w.field}")
            op = ALLOWED_OPS.get(w.op)
            if not op:
                raise ValueError(f"op not allowed: {w.op}")
            if op == "in":
                values = list(w.value)
                placeholders = ", ".join(["?"] * len(values))
                clauses.append(f"{self._ident(w.field)} IN ({placeholders})")
                params.extend(values)
            else:
                clauses.append(f"{self._ident(w.field)} {op} ?")
                params.append(w.value)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        if req.group_by:
            for g in req.group_by:
                if g not in allowed:
                    raise ValueError(f"column not allowed: {g}")
            sql += " GROUP BY " + ", ".join(self._ident(g) for g in req.group_by)
        if req.order_by:
            bits = []
            for o in req.order_by:
                direction = "DESC" if o.dir.lower() == "desc" else "ASC"
                bits.append(f"{self._ident(o.field)} {direction}")
            sql += " ORDER BY " + ", ".join(bits)
        sql += " LIMIT ?"
        params.append(req.limit)
        cur = self._con.execute(sql, params)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]

    def _ident(self, name: str) -> str:
        if not name.replace("_", "").isalnum():
            raise ValueError(f"bad identifier {name}")
        return f'"{name}"'

    def _relation_sql(self, table: str) -> str:
        if table == "securities":
            p = self._path("securities.parquet")
            if not p.exists():
                return "(SELECT NULL AS security_id WHERE 1=0)"
            return f"read_parquet('{p.as_posix()}')"
        if table == "ingest_runs":
            p = self._path("meta/ingest_runs.parquet")
            if not p.exists():
                return "(SELECT NULL AS run_id WHERE 1=0)"
            return f"read_parquet('{p.as_posix()}')"
        if table == "system_events":
            p = self._path("meta/system_events.parquet")
            if not p.exists():
                return "(SELECT NULL AS id WHERE 1=0)"
            return f"read_parquet('{p.as_posix()}')"
        root = self._path(table)
        files = list(root.rglob("*.parquet"))
        if not files:
            return "(SELECT NULL AS dummy WHERE 1=0)"
        glob = (root / "*.parquet").as_posix()
        return f"read_parquet('{glob}', union_by_name=true)"

    def run_screener(self, req: ScreenerRequest, as_of: date | None) -> list[ScreenerRow]:
        filters = resolve_filters(req)
        derived = self._read_hive("derived_daily_data", list(ALLOWED_TABLES["derived_daily_data"]))
        secs = self._read_parquet("securities.parquet", list(ALLOWED_TABLES["securities"]))
        if derived.empty or secs.empty:
            return []
        derived["date"] = pd.to_datetime(derived["date"]).dt.date
        if as_of is not None:
            snap = derived[derived["date"] == as_of].copy()
        else:
            derived = derived.sort_values("date")
            snap = derived.groupby("security_id", as_index=False).tail(1)
        if snap.empty:
            return []
        df = snap.merge(secs, on="security_id", how="inner")
        field_col = {
            "price": "price",
            "avg_volume": "avg_volume",
            "atr": "atr",
            "rel_vol_at": "rel_vol_at",
            "market": "market",
            "dollar_volume": "dollar_volume",
            "market_cap": "market_cap",
        }
        for f in filters:
            if df.empty:
                return []
            col = field_col[f.field]
            series = df[col]
            op = f.op
            val = f.value
            if op == FilterOp.GT:
                mask = series > val
            elif op == FilterOp.GTE:
                mask = series >= val
            elif op == FilterOp.LT:
                mask = series < val
            elif op == FilterOp.LTE:
                mask = series <= val
            else:
                mask = series == val
            df = df[mask.fillna(False)]
        if df.empty:
            return []
        sort = req.sort or "market_cap"
        if sort == "as_of":
            sort = "date"
        if sort in df.columns:
            df = df.sort_values(sort, ascending=req.sort_dir != "desc", na_position="last")
        df = df.head(req.limit)
        rows: list[ScreenerRow] = []
        for r in df.to_dict(orient="records"):
            raw_d = r.get("date")
            if hasattr(raw_d, "date"):
                raw_d = raw_d.date()
            rows.append(
                ScreenerRow(
                    security_id=int(r["security_id"]),
                    ticker=str(r["ticker"]),
                    name=str(r.get("name") or r["ticker"]),
                    exchange=str(r.get("exchange") or ""),
                    market=str(r.get("market") or "US"),
                    as_of=raw_d if isinstance(raw_d, date) else None,
                    price=_f(r.get("price")),
                    avg_volume=_f(r.get("avg_volume")),
                    atr=_f(r.get("atr")),
                    rel_vol_at=_f(r.get("rel_vol_at")),
                    rel_vol_at_sessions=int(r["rel_vol_at_sessions"]) if pd.notna(r.get("rel_vol_at_sessions")) else None,
                    dollar_volume=_f(r.get("dollar_volume")),
                    market_cap=_f(r.get("market_cap")),
                    first5m_volume=_f(r.get("first5m_volume")),
                )
            )
        return rows

    def bars(self, ticker: str, start: date | None, end: date | None, limit: int) -> list[dict[str, Any]]:
        sec = self.security_by_ticker(ticker)
        if not sec:
            return []
        df = self._read_hive("daily_data", list(ALLOWED_TABLES["daily_data"]))
        if df.empty:
            return []
        df["date"] = pd.to_datetime(df["date"]).dt.date
        df = df[df["security_id"] == sec.security_id]
        if start:
            df = df[df["date"] >= start]
        if end:
            df = df[df["date"] <= end]
        df = df.sort_values("date").tail(limit)
        df["ticker"] = sec.ticker
        return df.to_dict(orient="records")

    def set_shares(self, security_id: int, shares: int) -> None:
        df = self._read_parquet("securities.parquet", list(ALLOWED_TABLES["securities"]))
        if df.empty:
            return
        df.loc[df["security_id"] == security_id, "shares_outstanding"] = shares
        df.to_parquet(self._path("securities.parquet"), index=False)


def _f(v: Any) -> float | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
