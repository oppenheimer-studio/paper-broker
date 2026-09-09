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

    def __init__(self, price_feed) -> None:
        self._feed = price_feed
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
            try:
                self._cache = self._feed.fetch_eod(QQQ, start, end)
            except Exception:
                log.exception("qqq_calendar_fetch_failed", start=str(start), end=str(end))
                self._cache = []
            log.info(
                "qqq_calendar_loaded",
                n=len(self._cache),
                last=str(self._cache[-1].date) if self._cache else None,
            )
        return self._cache

    def invalidate(self) -> None:
        self._cache = None
