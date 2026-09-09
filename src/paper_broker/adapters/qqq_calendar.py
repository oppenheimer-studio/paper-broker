from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from paper_broker.domain.models import RawDailyBar
from paper_broker.logging import get_logger

log = get_logger("calendar")
ET = ZoneInfo("America/New_York")
ASUNCION = ZoneInfo("America/Asuncion")
QQQ = "QQQ"


class QqqCalendar:
    """Session calendar = dates QQQ has a daily bar. Never GSPC.

    expected_as_of is the last QQQ session strictly before today's ET date.
    A 01:00 America/Asuncion run therefore picks yesterday's US cash session.
    """

    def __init__(self, price_feed, warehouse=None) -> None:
        self._feed = price_feed
        self._warehouse = warehouse
        self._cache: list[RawDailyBar] | None = None

    def expected_as_of(self, now: datetime) -> date | None:
        now_utc = now.astimezone(timezone.utc) if now.tzinfo else now.replace(tzinfo=timezone.utc)
        now_et = now_utc.astimezone(ET)
        now_py = now_utc.astimezone(ASUNCION)
        today_et = now_et.date()
        bars = self._bars()
        prior = [b.date for b in bars if b.date < today_et]
        expected = prior[-1] if prior else None
        log.info(
            "calendar_expected",
            now_utc=now_utc.isoformat(),
            now_et=now_et.isoformat(),
            now_asuncion=now_py.isoformat(),
            today_et=str(today_et),
            qqq_last=str(bars[-1].date) if bars else None,
            expected=str(expected) if expected else None,
            n_sessions=len(bars),
        )
        if expected is None:
            log.error("calendar_no_session_before_today", today_et=str(today_et))
        return expected

    def sessions(self, start: date, end: date) -> list[date]:
        bars = self._bars()
        return [b.date for b in bars if start <= b.date <= end]

    def _bars(self) -> list[RawDailyBar]:
        if self._cache is None:
            end = datetime.now(ET).date()
            start = end - timedelta(days=120)
            live: list[RawDailyBar] = []
            try:
                live = self._feed.fetch_eod(QQQ, start, end) or []
            except Exception:
                log.exception("qqq_calendar_fetch_failed", start=str(start), end=str(end))
            source = "yahoo"
            if not live:
                live = self._from_warehouse(start, end)
                source = "warehouse"
            self._cache = live
            log.info(
                "qqq_calendar_loaded",
                n=len(self._cache),
                last=str(self._cache[-1].date) if self._cache else None,
                source=source,
            )
        return self._cache

    def _from_warehouse(self, start: date, end: date) -> list[RawDailyBar]:
        if self._warehouse is None:
            return []
        try:
            rows = self._warehouse.bars(QQQ, start, end, 200)
        except Exception:
            log.exception("qqq_calendar_warehouse_failed")
            return []
        out: list[RawDailyBar] = []
        for r in rows:
            raw_d = r.get("date")
            if hasattr(raw_d, "date"):
                raw_d = raw_d.date()
            if not isinstance(raw_d, date):
                continue
            out.append(
                RawDailyBar(
                    ticker=QQQ,
                    date=raw_d,
                    open=float(r.get("open") or 0),
                    high=float(r.get("high") or 0),
                    low=float(r.get("low") or 0),
                    close=float(r.get("close") or 0),
                    adj_close=float(r.get("adj_close") or r.get("close") or 0),
                    volume=float(r.get("volume") or 0),
                    source=str(r.get("source") or "warehouse"),
                )
            )
        out.sort(key=lambda b: b.date)
        if out:
            log.warning(
                "qqq_calendar_warehouse_fallback",
                n=len(out),
                last=str(out[-1].date),
            )
        return out

    def invalidate(self) -> None:
        self._cache = None
