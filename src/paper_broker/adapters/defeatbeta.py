from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import duckdb
import httpx
import pandas as pd

from paper_broker.domain.models import RawCorporateAction, RawDailyBar
from paper_broker.logging import get_logger

log = get_logger("defeatbeta")

HF_BASE = "https://huggingface.co/datasets/defeatbeta/yahoo-finance-data/resolve/main"
PRICE_FILE = "stock_prices.parquet"
DIV_FILE = "stock_dividend_events.parquet"
SPLIT_FILE = "stock_split_events.parquet"
DATA_FILES = (PRICE_FILE, DIV_FILE, SPLIT_FILE)


class DefeatbetaFeed:
    """Bulk EOD + splits/divs from the public Hugging Face parquet lake."""

    def __init__(
        self,
        cache_dir: Path,
        *,
        timeout: float = 120,
        download_timeout: float = 600,
        base_url: str = HF_BASE,
        client: httpx.Client | None = None,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.base_url = base_url.rstrip("/")
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=timeout, follow_redirects=True)
        self._download_timeout = download_timeout
        self._con = duckdb.connect()

    def close(self) -> None:
        self._con.close()
        if self._owns_client:
            self._client.close()

    def sessions_ready(self, dates: list[date]) -> bool:
        needed = {d.isoformat() for d in dates if d}
        if not needed:
            return True
        spec = self._fetch_spec()
        if spec is None:
            return False
        if not self._refresh_files(spec):
            return False
        prices = self.cache_dir / PRICE_FILE
        if not prices.is_file():
            return False
        found = self._con.execute(
            """
            SELECT DISTINCT CAST(report_date AS VARCHAR) AS d
            FROM read_parquet(?)
            WHERE CAST(report_date AS VARCHAR) IN (SELECT UNNEST(?))
            """,
            [str(prices), list(needed)],
        ).fetchall()
        have = {row[0] for row in found}
        missing = sorted(needed - have)
        if missing:
            log.info("defeatbeta_missing_dates", missing=missing, spec_update=spec.get("update_time"))
            return False
        log.info("defeatbeta_ready", dates=sorted(needed), spec_update=spec.get("update_time"))
        return True

    def local_session_dates(self, ticker: str = "QQQ") -> list[date]:
        """QQQ (or other) session dates from an already-downloaded parquet. No HTTP."""
        path = self.cache_dir / PRICE_FILE
        if not path.is_file() or path.stat().st_size <= 0:
            return []
        try:
            rows = self._con.execute(
                """
                SELECT DISTINCT CAST(report_date AS VARCHAR)
                FROM read_parquet(?)
                WHERE upper(symbol) = ?
                ORDER BY 1
                """,
                [str(path), ticker.upper()],
            ).fetchall()
        except Exception:
            log.exception("defeatbeta_local_dates_failed", ticker=ticker)
            return []
        out: list[date] = []
        for row in rows:
            day = _as_date(row[0])
            if day is not None:
                out.append(day)
        return out

    def fetch_range(
        self, start: date, end: date
    ) -> tuple[list[RawDailyBar], list[RawCorporateAction]]:
        spec = self._fetch_spec()
        if spec is None or not self._refresh_files(spec):
            raise RuntimeError("defeatbeta files unavailable")
        start_s, end_s = start.isoformat(), end.isoformat()
        prices = self._con.execute(
            """
            SELECT symbol, CAST(report_date AS VARCHAR) AS report_date,
                   open, high, low, close, volume
            FROM read_parquet(?)
            WHERE CAST(report_date AS VARCHAR) BETWEEN ? AND ?
            """,
            [str(self.cache_dir / PRICE_FILE), start_s, end_s],
        ).fetchdf()
        bars: list[RawDailyBar] = []
        for row in prices.itertuples(index=False):
            day = _as_date(row.report_date)
            if day is None:
                continue
            close = float(row.close)
            bars.append(
                RawDailyBar(
                    ticker=str(row.symbol).upper(),
                    date=day,
                    open=float(row.open),
                    high=float(row.high),
                    low=float(row.low),
                    close=close,
                    adj_close=close,
                    volume=float(row.volume or 0),
                    source="defeatbeta",
                )
            )
        actions: list[RawCorporateAction] = []
        actions.extend(self._load_dividends(start_s, end_s))
        actions.extend(self._load_splits(start_s, end_s))
        log.info("defeatbeta_fetched", bars=len(bars), actions=len(actions), start=start_s, end=end_s)
        return bars, actions

    def _load_dividends(self, start_s: str, end_s: str) -> list[RawCorporateAction]:
        path = self.cache_dir / DIV_FILE
        if not path.is_file():
            return []
        df = self._con.execute(
            """
            SELECT symbol, CAST(report_date AS VARCHAR) AS report_date, amount
            FROM read_parquet(?)
            WHERE CAST(report_date AS VARCHAR) BETWEEN ? AND ?
            """,
            [str(path), start_s, end_s],
        ).fetchdf()
        out: list[RawCorporateAction] = []
        for row in df.itertuples(index=False):
            day = _as_date(row.report_date)
            if day is None:
                continue
            out.append(
                RawCorporateAction(
                    ticker=str(row.symbol).upper(),
                    date=day,
                    action="dividend",
                    value=float(row.amount),
                    source="defeatbeta",
                )
            )
        return out

    def _load_splits(self, start_s: str, end_s: str) -> list[RawCorporateAction]:
        path = self.cache_dir / SPLIT_FILE
        if not path.is_file():
            return []
        df = self._con.execute(
            """
            SELECT symbol, CAST(report_date AS VARCHAR) AS report_date, split_factor
            FROM read_parquet(?)
            WHERE CAST(report_date AS VARCHAR) BETWEEN ? AND ?
            """,
            [str(path), start_s, end_s],
        ).fetchdf()
        out: list[RawCorporateAction] = []
        for row in df.itertuples(index=False):
            day = _as_date(row.report_date)
            if day is None:
                continue
            num, den, ratio = _parse_split_factor(row.split_factor)
            out.append(
                RawCorporateAction(
                    ticker=str(row.symbol).upper(),
                    date=day,
                    action="split",
                    value=ratio,
                    numerator=num,
                    denominator=den,
                    source="defeatbeta",
                )
            )
        return out

    def _fetch_spec(self) -> dict | None:
        url = f"{self.base_url}/spec.json"
        try:
            res = self._client.get(url)
            res.raise_for_status()
            spec = res.json()
        except Exception:
            log.exception("defeatbeta_spec_fail", url=url)
            return None
        (self.cache_dir / "spec.json").write_text(json.dumps(spec), encoding="utf-8")
        return spec

    def _refresh_files(self, spec: dict) -> bool:
        stamps = spec.get("files") or {}
        meta_path = self.cache_dir / "cached_files.json"
        cached = {}
        if meta_path.is_file():
            try:
                cached = json.loads(meta_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                cached = {}
        ok = True
        for name in DATA_FILES:
            dest = self.cache_dir / name
            remote_ts = stamps.get(name)
            if dest.is_file() and cached.get(name) == remote_ts and dest.stat().st_size > 0:
                continue
            url = f"{self.base_url}/data/{name}"
            try:
                self._download(url, dest)
                cached[name] = remote_ts
                log.info("defeatbeta_downloaded", file=name, ts=remote_ts, bytes=dest.stat().st_size)
            except Exception:
                log.exception("defeatbeta_download_fail", file=name, url=url)
                ok = False
        meta_path.write_text(json.dumps(cached), encoding="utf-8")
        return ok

    def _download(self, url: str, dest: Path) -> None:
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        with self._client.stream("GET", url, timeout=self._download_timeout) as res:
            res.raise_for_status()
            with tmp.open("wb") as fh:
                for chunk in res.iter_bytes(1024 * 1024):
                    fh.write(chunk)
        tmp.replace(dest)


def _as_date(value) -> date | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, date) and not isinstance(value, pd.Timestamp):
        return value
    text = str(value)[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _parse_split_factor(raw) -> tuple[float | None, float | None, float | None]:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None, None, None
    text = str(raw).strip()
    for sep in (":", "/"):
        if sep in text:
            left, right = text.split(sep, 1)
            try:
                num, den = float(left), float(right)
            except ValueError:
                return None, None, None
            if den:
                return num, den, num / den
            return num, den, None
    try:
        ratio = float(text)
    except ValueError:
        return None, None, None
    return ratio, 1.0, ratio
