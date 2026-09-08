from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from paper_broker.domain.models import RawDailyBar
from paper_broker.logging import get_logger

log = get_logger("calendar")
ET = ZoneInfo("America/New_York")
QQQ = "QQQ"


class QqqCalendar:
    """Session calendar = dates QQQ has a daily bar. Never GSPC."""

    def __init__(self, price_feed) -> None:
        self._feed = price_feed
        self._cache: list[date] | None = None

    def expected_as_of(self, now: datetime) -> date | None:
        sessions = self.sessions(now.date() - timedelta(days=21), now.date() + timedelta(days=1))
        if not sessions:
            return None
        now_et = now.astimezone(ET) if now.tzinfo else now.replace(tzinfo=ET)
        # Before ~18:00 ET the official close may not be in the Yahoo 1d chart yet.
        latest = sessions[-1]
        if now_et.hour < 18 and latest == now_et.date() and len(sessions) >= 2:
            return sessions[-2]
        return latest

    def sessions(self, start: date, end: date) -> list[date]:
        bars = self._bars()
        return [b.date for b in bars if start <= b.date <= end]

    def _bars(self) -> list[RawDailyBar]:
        if self._cache is None:
            end = datetime.now(ET).date()
            start = end - timedelta(days=120)
            self._cache = self._feed.fetch_eod(QQQ, start, end)
            log.info("qqq_calendar_loaded", n=len(self._cache), last=str(self._cache[-1].date) if self._cache else None)
        return self._cache

    def invalidate(self) -> None:
        self._cache = None
