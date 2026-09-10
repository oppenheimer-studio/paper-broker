from __future__ import annotations

import time
from datetime import date, datetime, time as dtime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx

from paper_broker.adapters.rate_limit import HourlyRateLimiter, RateLimitTripped
from paper_broker.domain.models import RawCorporateAction, RawDailyBar, RawMinuteOpen
from paper_broker.logging import get_logger

log = get_logger("yahoo")
ET = ZoneInfo("America/New_York")
CHART_HOSTS = ("query1.finance.yahoo.com", "query2.finance.yahoo.com")
DEFAULT_MAX_REQUESTS_PER_HOUR = 2500


class YahooError(Exception):
    def __init__(self, ticker: str, status: int, detail: str) -> None:
        super().__init__(f"yahoo {ticker} -> {status} {detail}")
        self.ticker = ticker
        self.status = status


class YahooFeed:
    def __init__(
        self,
        user_agent: str,
        timeout: float,
        max_requests_per_hour: int = DEFAULT_MAX_REQUESTS_PER_HOUR,
        limiter: HourlyRateLimiter | None = None,
    ) -> None:
        self._client = httpx.Client(
            timeout=timeout,
            headers={
                "user-agent": user_agent,
                "accept": "application/json,*/*",
                "accept-language": "en-US,en;q=0.9",
            },
            follow_redirects=True,
        )
        self._limiter = limiter or HourlyRateLimiter(max_requests_per_hour)

    def close(self) -> None:
        self._client.close()

    def reset_circuit(self) -> None:
        self._limiter.reset_trip()

    @property
    def circuit_open(self) -> bool:
        return self._limiter.tripped

    @property
    def http(self) -> httpx.Client:
        return self._client

    def fetch_eod(self, ticker: str, start: date, end: date) -> list[RawDailyBar]:
        bars, _actions = self.fetch_session(ticker, start, end)
        return bars

    def fetch_session(
        self, ticker: str, start: date, end: date
    ) -> tuple[list[RawDailyBar], list[RawCorporateAction]]:
        period1 = int(datetime.combine(start, dtime.min, tzinfo=ET).timestamp())
        period2 = int(datetime.combine(end + timedelta(days=1), dtime.min, tzinfo=ET).timestamp())
        payload = self._chart(ticker, "1d", period1, period2, events="div%7Csplit")
        bars = self._parse_daily(ticker, payload)
        actions = self._parse_actions(ticker, payload)
        return bars, actions

    def fetch_open_windows(
        self, ticker: str, start: date, end: date, window_minutes: int
    ) -> list[RawMinuteOpen]:
        period1 = int(datetime.combine(start, dtime.min, tzinfo=ET).timestamp())
        period2 = int(datetime.combine(end + timedelta(days=1), dtime.min, tzinfo=ET).timestamp())
        payload = self._chart(ticker, "1m", period1, period2, events="")
        out = self._parse_open_windows(ticker, payload, window_minutes, start, end)
        if out:
            return out
        if self._limiter.tripped:
            return []
        log.warning("minute_empty_retry", ticker=ticker, start=str(start), end=str(end))
        payload = self._chart(ticker, "1m", period1, period2, events="", prefer_host=CHART_HOSTS[1])
        return self._parse_open_windows(ticker, payload, window_minutes, start, end)

    def fetch_shares(self, ticker: str) -> int | None:
        url = (
            "https://query2.finance.yahoo.com/v10/finance/quoteSummary/"
            f"{ticker}?modules=defaultKeyStatistics"
        )
        try:
            data = self._get_json(url, ticker=ticker)
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

    def _chart(
        self,
        ticker: str,
        interval: str,
        period1: int,
        period2: int,
        events: str,
        prefer_host: str | None = None,
    ) -> dict:
        q = f"interval={interval}&period1={period1}&period2={period2}"
        if events:
            q += f"&events={events}"
        hosts = (prefer_host, *[h for h in CHART_HOSTS if h != prefer_host]) if prefer_host else CHART_HOSTS
        last_err: YahooError | None = None
        for host in hosts:
            if not host:
                continue
            url = f"https://{host}/v8/finance/chart/{ticker}?{q}"
            try:
                payload = self._get_json(url, ticker=ticker)
            except YahooError as exc:
                last_err = exc
                log.warning(
                    "yahoo_chart_fail",
                    ticker=ticker,
                    host=host,
                    interval=interval,
                    status=exc.status,
                )
                if exc.status == 429:
                    break
                continue
            result = (payload.get("chart") or {}).get("result") or []
            if result:
                return payload
            log.warning("yahoo_empty_chart", ticker=ticker, host=host, interval=interval)
        if last_err:
            raise last_err
        return {"chart": {"result": []}}

    def _get_json(self, url: str, *, ticker: str) -> dict:
        last_exc: Exception | None = None
        for attempt in range(2):
            try:
                waited = self._limiter.acquire()
            except RateLimitTripped as exc:
                raise YahooError(ticker, 429, str(exc)) from exc
            if waited:
                log.info("yahoo_rate_pace", ticker=ticker, waited_s=round(waited, 1))
            try:
                res = self._client.get(url)
                if res.status_code == 429:
                    cooldown = self._limiter.penalize()
                    log.warning(
                        "yahoo_rate_limited",
                        ticker=ticker,
                        attempt=attempt + 1,
                        cooldown_s=round(cooldown, 1),
                        consecutive=self._limiter.consecutive_429,
                        tripped=self._limiter.tripped,
                    )
                    last_exc = YahooError(ticker, 429, "rate limited")
                    continue
                if res.status_code >= 400:
                    raise YahooError(ticker, res.status_code, res.text[:200])
                self._limiter.note_success()
                return res.json()
            except httpx.HTTPError as exc:
                last_exc = exc
                log.warning("yahoo_http_error", ticker=ticker, attempt=attempt + 1, error=str(exc))
                time.sleep(0.4 * (attempt + 1))
        if isinstance(last_exc, YahooError):
            raise last_exc
        raise YahooError(ticker, 0, str(last_exc) if last_exc else "retry exhausted")

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

    def _parse_actions(self, ticker: str, payload: dict) -> list[RawCorporateAction]:
        result = (payload.get("chart") or {}).get("result") or []
        if not result:
            return []
        events = result[0].get("events") or {}
        out: list[RawCorporateAction] = []
        for item in (events.get("dividends") or {}).values():
            unix = item.get("date")
            amount = item.get("amount")
            if unix is None or not isinstance(amount, (int, float)):
                continue
            day = datetime.fromtimestamp(int(unix), tz=timezone.utc).astimezone(ET).date()
            out.append(
                RawCorporateAction(
                    ticker=ticker,
                    date=day,
                    action="dividend",
                    value=float(amount),
                    source="yahoo",
                )
            )
        for item in (events.get("splits") or {}).values():
            unix = item.get("date")
            num = item.get("numerator")
            den = item.get("denominator")
            if unix is None:
                continue
            day = datetime.fromtimestamp(int(unix), tz=timezone.utc).astimezone(ET).date()
            ratio = None
            if isinstance(num, (int, float)) and isinstance(den, (int, float)) and den:
                ratio = float(num) / float(den)
            out.append(
                RawCorporateAction(
                    ticker=ticker,
                    date=day,
                    action="split",
                    value=ratio,
                    numerator=float(num) if isinstance(num, (int, float)) else None,
                    denominator=float(den) if isinstance(den, (int, float)) else None,
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
