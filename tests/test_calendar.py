from datetime import date, datetime
from zoneinfo import ZoneInfo

from paper_broker.adapters.qqq_calendar import QqqCalendar
from paper_broker.domain.models import RawDailyBar

ET = ZoneInfo("America/New_York")
ASUNCION = ZoneInfo("America/Asuncion")


class _QqqFeed:
    def __init__(self, days: list[date]):
        self.days = days

    def fetch_eod(self, ticker, start, end):
        assert ticker == "QQQ"
        return [
            RawDailyBar(
                ticker="QQQ",
                date=d,
                open=1,
                high=1,
                low=1,
                close=1,
                adj_close=1,
                volume=1,
            )
            for d in self.days
            if start <= d <= end
        ]


def _cal(days: list[date]) -> QqqCalendar:
    return QqqCalendar(_QqqFeed(days))


# Fri 4 Sep 2026, Mon 7 Labor Day, Tue 8, Wed 9.
QQQ_DAYS = [
    date(2026, 9, 3),
    date(2026, 9, 4),
    date(2026, 9, 8),
    date(2026, 9, 9),
]


def test_one_am_asuncion_on_the_9th_is_session_8():
    now = datetime(2026, 9, 9, 1, 0, tzinfo=ASUNCION)
    assert _cal(QQQ_DAYS).expected_as_of(now) == date(2026, 9, 8)


def test_five_pm_et_on_the_8th_does_not_take_today():
    now = datetime(2026, 9, 8, 17, 0, tzinfo=ET)
    assert _cal(QQQ_DAYS).expected_as_of(now) == date(2026, 9, 4)


def test_saturday_one_am_asuncion_is_friday():
    days = [
        date(2026, 9, 3),
        date(2026, 9, 4),
    ]
    now = datetime(2026, 9, 5, 1, 0, tzinfo=ASUNCION)
    assert _cal(days).expected_as_of(now) == date(2026, 9, 4)


def test_no_bars_returns_none():
    now = datetime(2026, 9, 9, 1, 0, tzinfo=ASUNCION)
    assert _cal([]).expected_as_of(now) is None
