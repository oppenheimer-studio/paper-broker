from datetime import date

from paper_broker.adapters.duckdb_warehouse import DuckDbWarehouse
from paper_broker.adapters.nasdaq import UniverseSnapshot
from paper_broker.adapters.seed_universe import seed_drafts
from paper_broker.application.daily_update import DailyUpdateService
from paper_broker.domain.models import RawDailyBar, SecurityDraft


class Cal:
    def expected_as_of(self, now):
        return date(2026, 9, 4)

    def sessions(self, start, end):
        return [d for d in [date(2026, 9, 3), date(2026, 9, 4)] if start <= d <= end]


class Feed:
    def fetch_eod(self, ticker, start, end):
        bars = []
        day = start
        while day <= end:
            bars.append(
                RawDailyBar(
                    ticker=ticker,
                    date=day,
                    open=10,
                    high=11,
                    low=9,
                    close=10.5,
                    adj_close=10.5,
                    volume=2_000_000,
                )
            )
            day = date.fromordinal(day.toordinal() + 1)
        return bars

    def fetch_open_windows(self, ticker, start, end, window_minutes):
        return []

    def fetch_shares(self, ticker):
        return None


class SeedUniverse:
    def fetch_universe(self):
        return UniverseSnapshot(drafts=seed_drafts()[:5], source="seed", warnings=["nasdaq 406"])

    def fetch_us_stocks(self):
        return self.fetch_universe().drafts


class BoomUniverse:
    def fetch_us_stocks(self):
        raise RuntimeError("nasdaq 406")


def _svc(tmp_path, universe):
    wh = DuckDbWarehouse(tmp_path)
    feed = Feed()
    return wh, DailyUpdateService(
        wh,
        universe,
        feed,
        feed,
        Cal(),
        seed_sessions=1,
        max_tickers=3,
        concurrency=1,
        open_window_minutes=5,
    )


def test_daily_catch_all_records_event(tmp_path):
    wh, svc = _svc(tmp_path, BoomUniverse())
    report = svc.run()
    assert report["status"] == "error"
    assert svc.last_report is not None
    codes = {e.code for e in wh.list_events()}
    assert "daily.failed" in codes
    assert "daily.started" in codes


def test_daily_seed_fallback_emits_and_finishes(tmp_path):
    wh, svc = _svc(tmp_path, SeedUniverse())
    report = svc.run()
    assert report["status"] in {"ok", "partial"}
    assert report["universe_source"] == "seed"
    codes = {e.code for e in wh.list_events()}
    assert "universe.fallback" in codes
    assert "daily.finished" in codes
    assert wh.last_success_as_of() == date(2026, 9, 4)


def test_max_tickers_zero_ingests_full_universe(tmp_path):
    drafts = seed_drafts()
    wh = DuckDbWarehouse(tmp_path)

    class Uni:
        def fetch_universe(self):
            return UniverseSnapshot(drafts=drafts, source="nasdaq", warnings=[])

        def fetch_us_stocks(self):
            return drafts

    feed = Feed()
    svc = DailyUpdateService(
        wh,
        Uni(),
        feed,
        feed,
        Cal(),
        seed_sessions=1,
        max_tickers=0,
        concurrency=1,
        open_window_minutes=5,
    )
    report = svc.run()
    assert report["universe_n"] == len(drafts)
    assert report["ingest_n"] == len(drafts)
    assert report["tickers"] == len(drafts)


def test_qqq_missing_eod_marks_session_error(tmp_path):
    class NoQqq(Feed):
        def fetch_eod(self, ticker, start, end):
            if ticker == "QQQ":
                return []
            return super().fetch_eod(ticker, start, end)

    wh = DuckDbWarehouse(tmp_path)

    class Uni:
        def fetch_universe(self):
            return UniverseSnapshot(drafts=seed_drafts()[:3], source="nasdaq", warnings=[])

        def fetch_us_stocks(self):
            return self.fetch_universe().drafts

    feed = NoQqq()
    svc = DailyUpdateService(
        wh,
        Uni(),
        feed,
        feed,
        Cal(),
        seed_sessions=1,
        max_tickers=0,
        concurrency=1,
        open_window_minutes=5,
    )
    report = svc.run()
    assert report["sessions"][0]["status"] == "error"
    assert "QQQ missing EOD" in report["sessions"][0]["error"]
    assert wh.last_success_as_of() is None


def test_daily_continues_after_session_error(tmp_path):
    wh = DuckDbWarehouse(tmp_path)
    drafts = [SecurityDraft(ticker="AAA", name="Aaa", exchange="NYSE")]
    wh.upsert_securities(drafts)

    class Uni:
        def fetch_universe(self):
            return UniverseSnapshot(drafts=seed_drafts()[:3], source="nasdaq", warnings=[])

        def fetch_us_stocks(self):
            return self.fetch_universe().drafts

    class BrokenDerived:
        def __init__(self, inner):
            self._inner = inner
            self.n = 0

        def rewrite_derived(self, *args, **kwargs):
            self.n += 1
            if self.n == 1:
                raise RuntimeError("derived boom")
            return self._inner.rewrite_derived(*args, **kwargs)

        def __getattr__(self, name):
            return getattr(self._inner, name)

    wrapped = BrokenDerived(wh)
    feed = Feed()
    svc = DailyUpdateService(
        wrapped,
        Uni(),
        feed,
        feed,
        Cal(),
        seed_sessions=2,
        max_tickers=2,
        concurrency=1,
        open_window_minutes=5,
    )
    report = svc.run()
    statuses = [s["status"] for s in report["sessions"]]
    assert "error" in statuses
    assert "success" in statuses
    assert report["status"] == "partial"
