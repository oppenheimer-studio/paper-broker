from __future__ import annotations

import time
from datetime import date, datetime, time as dtime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx

from paper_broker.domain.models import RawDailyBar, RawMinuteOpen
from paper_broker.logging import get_logger

log = get_logger("yahoo")
ET = ZoneInfo("America/New_York")


class YahooError(Exception):
    def __init__(self, ticker: str, status: int, detail: str) -> None:
        super().__init__(f"yahoo {ticker} -> {status} {detail}")
        self.ticker = ticker
        self.status = status


class YahooFeed:
    def __init__(self, user_agent: str, timeout: float) -> None:
        self._client = httpx.Client(
            timeout=timeout,
            headers={"user-agent": user_agent, "accept": "application/json"},
            follow_redirects=True,
        )

    def close(self) -> None:
        self._client.close()

    @property
    def http(self) -> httpx.Client:
        return self._client

    def fetch_eod(self, ticker: str, start: date, end: date) -> list[RawDailyBar]:
        period1 = int(datetime.combine(start, dtime.min, tzinfo=ET).timestamp())
        period2 = int(datetime.combine(end + timedelta(days=1), dtime.min, tzinfo=ET).timestamp())
        payload = self._chart(ticker, "1d", period1, period2, events="div%7Csplit")
        return self._parse_daily(ticker, payload)

    def fetch_open_windows(
        self, ticker: str, start: date, end: date, window_minutes: int
    ) -> list[RawMinuteOpen]:
        # Yahoo 1m is ~7d; requesting a wider window still returns what they have.
        period1 = int(datetime.combine(start, dtime.min, tzinfo=ET).timestamp())
        period2 = int(datetime.combine(end + timedelta(days=1), dtime.min, tzinfo=ET).timestamp())
        payload = self._chart(ticker, "1m", period1, period2, events="")
        return self._parse_open_windows(ticker, payload, window_minutes, start, end)

    def fetch_shares(self, ticker: str) -> int | None:
        url = (
            "https://query2.finance.yahoo.com/v10/finance/quoteSummary/"
            f"{ticker}?modules=defaultKeyStatistics"
        )
        try:
            data = self._get_json(url)
        except YahooError as exc:
            log.warning("shares_skip", ticker=ticker, status=exc.status)
            return None
        try:
            raw = data["quoteSummary"]["result"][0]["defaultKeyStatistics"]["sharesOutstanding"][
                "raw"
            ]
            return int(raw) if raw else None
        except (KeyError, IndexError, TypeError, ValueError):
            return None

    def _chart(self, ticker: str, interval: str, period1: int, period2: int, events: str) -> dict:
        q = f"interval={interval}&period1={period1}&period2={period2}"
        if events:
            q += f"&events={events}"
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?{q}"
        return self._get_json(url)

    def _get_json(self, url: str) -> dict:
        last_exc: Exception | None = None
        for attempt in range(4):
            try:
                res = self._client.get(url)
                if res.status_code == 429:
                    wait = 1.5 * (attempt + 1)
                    log.warning("yahoo_rate_limited", url=url, wait_s=wait)
                    time.sleep(wait)
                    continue
                if res.status_code >= 400:
                    raise YahooError(url, res.status_code, res.text[:200])
                return res.json()
            except httpx.HTTPError as exc:
                last_exc = exc
                time.sleep(0.4 * (attempt + 1))
        raise YahooError(url, 0, str(last_exc) if last_exc else "retry exhausted")

    def _parse_daily(self, ticker: str, payload: dict) -> list[RawDailyBar]:
        result = (payload.get("chart") or {}).get("result") or []
        if not result:
            return []
        node = result[0]
        ts = node.get("timestamp") or []
        quote = (node.get("indicators") or {}).get("quote") or [{}]
        q = quote[0]
        adj = ((node.get("indicators") or {}).get("adjclose") or [{}])[0].get("adjclose") or []
        out: list[RawDailyBar] = []
        opens, highs, lows, closes, vols = (
            q.get("open") or [],
            q.get("high") or [],
            q.get("low") or [],
            q.get("close") or [],
            q.get("volume") or [],
        )
        for i, unix in enumerate(ts):
            o, h, l, c = _nth(opens, i), _nth(highs, i), _nth(lows, i), _nth(closes, i)
            if not all(isinstance(x, (int, float)) for x in (o, h, l, c)):
                continue
            vol = _nth(vols, i) or 0
            adj_c = _nth(adj, i)
            if not isinstance(adj_c, (int, float)):
                adj_c = c
            day = datetime.fromtimestamp(unix, tz=timezone.utc).astimezone(ET).date()
            out.append(
                RawDailyBar(
                    ticker=ticker,
                    date=day,
                    open=float(o),
                    high=float(h),
                    low=float(l),
                    close=float(c),
                    adj_close=float(adj_c),
                    volume=float(vol),
                    source="yahoo",
                )
            )
        return out

    def _parse_open_windows(
        self, ticker: str, payload: dict, window_minutes: int, start: date, end: date
    ) -> list[RawMinuteOpen]:
        result = (payload.get("chart") or {}).get("result") or []
        if not result:
            return []
        node = result[0]
        ts = node.get("timestamp") or []
        q = ((node.get("indicators") or {}).get("quote") or [{}])[0]
        buckets: dict[date, list[tuple[datetime, float, float, float, float, float]]] = {}
        open_t = dtime(9, 30)
        close_t = (
            datetime.combine(date(2000, 1, 1), open_t) + timedelta(minutes=window_minutes)
        ).time()
        for i, unix in enumerate(ts):
            dt = datetime.fromtimestamp(unix, tz=timezone.utc).astimezone(ET)
            day = dt.date()
            if day < start or day > end:
                continue
            t = dt.time()
            if t < open_t or t >= close_t:
                continue
            o, h, l, c = _nth(q.get("open") or [], i), _nth(q.get("high") or [], i), _nth(q.get("low") or [], i), _nth(q.get("close") or [], i)
            if not all(isinstance(x, (int, float)) for x in (o, h, l, c)):
                continue
            vol = float(_nth(q.get("volume") or [], i) or 0)
            buckets.setdefault(day, []).append((dt, float(o), float(h), float(l), float(c), vol))
        out: list[RawMinuteOpen] = []
        for day, rows in buckets.items():
            rows.sort(key=lambda x: x[0])
            out.append(
                RawMinuteOpen(
                    ticker=ticker,
                    date=day,
                    window_minutes=window_minutes,
                    open=rows[0][1],
                    high=max(r[2] for r in rows),
                    low=min(r[3] for r in rows),
                    close=rows[-1][4],
                    volume=sum(r[5] for r in rows),
                    source="yahoo",
                )
            )
        return out


def _nth(seq, i):
    return seq[i] if i < len(seq) else None
