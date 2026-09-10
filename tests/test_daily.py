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


def test_minutes_phase_does_not_mark_success(tmp_path):
    from paper_broker.domain.models import RawMinuteOpen

    class MinuteFeed(Feed):
        def fetch_open_windows(self, ticker, start, end, window_minutes):
            day = start
            out = []
            while day <= end:
                out.append(
                    RawMinuteOpen(
                        ticker=ticker,
                        date=day,
                        window_minutes=window_minutes,
                        open=10,
                        high=11,
                        low=9,
                        close=10.2,
                        volume=50_000,
                    )
                )
                day = date.fromordinal(day.toordinal() + 1)
            return out

    wh, svc = _svc(tmp_path, SeedUniverse())
    svc._minutes = MinuteFeed()
    report = svc.run("minutes")
    assert report["phase"] == "minutes"
    assert report["minute_open_upserts"] > 0
    assert report["sessions"] == []
    assert wh.last_success_as_of() is None


def test_eod_gives_up_when_defeatbeta_not_ready(tmp_path):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    class NeverReady:
        def sessions_ready(self, dates):
            return False

        def fetch_range(self, start, end):
            raise AssertionError("must not fetch")

    wh = DuckDbWarehouse(tmp_path)
    svc = DailyUpdateService(
        wh,
        SeedUniverse(),
        Feed(),
        Feed(),
        Cal(),
        seed_sessions=1,
        max_tickers=3,
        concurrency=1,
        open_window_minutes=5,
        eod_bulk=NeverReady(),
        eod_ready_attempts=6,
        eod_ready_wait_s=0,
        eod_give_up_hour=9,
        now_fn=lambda: datetime(2026, 9, 9, 12, 5, tzinfo=ZoneInfo("UTC")),
    )
    report = svc.run("eod")
    assert report["status"] == "error"
    assert report["error"] == "defeatbeta_not_ready"
    assert wh.last_success_as_of() is None
    codes = {e.code for e in wh.list_events()}
    assert "daily.eod_not_ready" in codes


def test_eod_retries_until_defeatbeta_ready(tmp_path):
    from paper_broker.domain.models import RawCorporateAction, RawDailyBar

    class LaterReady:
        def __init__(self):
            self.checks = 0

        def sessions_ready(self, dates):
            self.checks += 1
            return self.checks >= 3

        def fetch_range(self, start, end):
            bars = []
            day = start
            while day <= end:
                for ticker in ("QQQ", "SPY", "AAPL", "MSFT", "NVDA"):
                    bars.append(
                        RawDailyBar(
                            ticker=ticker,
                            date=day,
                            open=10,
                            high=11,
                            low=9,
                            close=10.5,
                            adj_close=10.5,
                            volume=1_000_000,
                            source="defeatbeta",
                        )
                    )
                day = date.fromordinal(day.toordinal() + 1)
            return bars, [
                RawCorporateAction(
                    ticker="AAPL",
                    date=start,
                    action="dividend",
                    value=0.22,
                    source="defeatbeta",
                )
            ]

    from datetime import datetime
    from zoneinfo import ZoneInfo

    bulk = LaterReady()
    sleeps = []
    wh = DuckDbWarehouse(tmp_path)
    svc = DailyUpdateService(
        wh,
        SeedUniverse(),
        Feed(),
        Feed(),
        Cal(),
        seed_sessions=1,
        max_tickers=0,
        concurrency=1,
        open_window_minutes=5,
        eod_bulk=bulk,
        eod_ready_attempts=6,
        eod_ready_wait_s=0.01,
        sleeper=lambda s: sleeps.append(s),
        now_fn=lambda: datetime(2026, 9, 9, 9, 0, tzinfo=ZoneInfo("UTC")),
    )
    report = svc.run("eod")
    assert bulk.checks == 3
    assert sleeps == [0.01, 0.01]
    assert report["status"] in {"ok", "partial"}
    assert report["eod_source"] == "defeatbeta"
    assert report["corporate_actions"] >= 1
    assert wh.last_success_as_of() == date(2026, 9, 4)


def test_eod_yahoo_fallback_for_missing_ticker(tmp_path):
    from paper_broker.domain.models import RawDailyBar

    class PartialBulk:
        def sessions_ready(self, dates):
            return True

        def fetch_range(self, start, end):
            bars = []
            day = start
            while day <= end:
                bars.append(
                    RawDailyBar(
                        ticker="QQQ",
                        date=day,
                        open=1,
                        high=2,
                        low=1,
                        close=1.5,
                        adj_close=1.5,
                        volume=10,
                        source="defeatbeta",
                    )
                )
                day = date.fromordinal(day.toordinal() + 1)
            return bars, []

    wh = DuckDbWarehouse(tmp_path)
    svc = DailyUpdateService(
        wh,
        SeedUniverse(),
        Feed(),
        Feed(),
        Cal(),
        seed_sessions=1,
        max_tickers=0,
        concurrency=1,
        open_window_minutes=5,
        eod_bulk=PartialBulk(),
    )
    report = svc.run("eod")
    assert report["eod_source"] == "mixed"
    assert report["status"] in {"ok", "partial"}
    assert report["eod_upserts"] >= 5
    assert report["eod_ok"] == 5


def test_already_running_emits_event(tmp_path):
    wh, svc = _svc(tmp_path, SeedUniverse())
    svc._eod_busy = True
    svc._minutes_busy = True
    report = svc.run("eod")
    assert report["status"] == "already_running"
    codes = {e.code for e in wh.list_events()}
    assert "daily.already_running" in codes


def test_minutes_ingesting_stays_true_across_retry(tmp_path):
    from paper_broker.domain.models import RawMinuteOpen

    seen = []
    wh, svc = _svc(tmp_path, SeedUniverse())

    orig = svc._ingest_minute_open

    def wrapped(securities, start, end):
        seen.append(svc._minutes_ingesting)
        result = orig(securities, start, end)
        seen.append(svc._minutes_ingesting)
        return result

    class OnceEmpty(Feed):
        n = 0

        def fetch_open_windows(self, ticker, start, end, window_minutes):
            self.n += 1
            if self.n == 1:
                return []
            day = start
            out = []
            while day <= end:
                out.append(
                    RawMinuteOpen(
                        ticker=ticker,
                        date=day,
                        window_minutes=window_minutes,
                        open=10,
                        high=11,
                        low=9,
                        close=10.2,
                        volume=50_000,
                    )
                )
                day = date.fromordinal(day.toordinal() + 1)
            return out

    svc._minutes = OnceEmpty()
    svc._ingest_minute_open = wrapped
    svc.run("minutes")
    assert seen
    assert all(seen), seen


def test_eod_refreshes_calendar_after_hf_ready(tmp_path):
    class FlipCal:
        n = 0

        def invalidate(self):
            self.n += 1

        def expected_as_of(self, now):
            return date(2026, 9, 9) if self.n >= 2 else date(2026, 9, 8)

        def sessions(self, start, end):
            days = [date(2026, 9, 8), date(2026, 9, 9)]
            return [d for d in days if start <= d <= end]

    class Ready:
        ranges: list = []

        def sessions_ready(self, dates):
            return True

        def fetch_range(self, start, end):
            self.ranges.append((start, end))
            bars = []
            day = start
            while day <= end:
                for ticker in ("QQQ", "SPY", "AAPL", "MSFT", "NVDA"):
                    bars.append(
                        RawDailyBar(
                            ticker=ticker,
                            date=day,
                            open=10,
                            high=11,
                            low=9,
                            close=10.5,
                            adj_close=10.5,
                            volume=1_000_000,
                            source="defeatbeta",
                        )
                    )
                day = date.fromordinal(day.toordinal() + 1)
            return bars, []

    bulk = Ready()
    wh = DuckDbWarehouse(tmp_path)
    svc = DailyUpdateService(
        wh,
        SeedUniverse(),
        Feed(),
        Feed(),
        FlipCal(),
        seed_sessions=1,
        max_tickers=0,
        concurrency=1,
        open_window_minutes=5,
        eod_bulk=bulk,
    )
    report = svc.run("eod")
    assert bulk.ranges
    assert bulk.ranges[0][1] == date(2026, 9, 9)
    assert date(2026, 9, 9).isoformat() in report["pending"]
    assert report["status"] in {"ok", "partial"}


def test_eod_skips_yahoo_fallback_while_minutes_ingesting(tmp_path):
    class PartialBulk:
        def sessions_ready(self, dates):
            return True

        def fetch_range(self, start, end):
            bars = []
            day = start
            while day <= end:
                bars.append(
                    RawDailyBar(
                        ticker="QQQ",
                        date=day,
                        open=1,
                        high=2,
                        low=1,
                        close=1.5,
                        adj_close=1.5,
                        volume=10,
                        source="defeatbeta",
                    )
                )
                day = date.fromordinal(day.toordinal() + 1)
            return bars, []

    yahoo_calls = []

    class Counting(Feed):
        def fetch_eod(self, ticker, start, end):
            yahoo_calls.append(ticker)
            return super().fetch_eod(ticker, start, end)

        def fetch_session(self, ticker, start, end):
            yahoo_calls.append(ticker)
            return super().fetch_eod(ticker, start, end), []

    wh = DuckDbWarehouse(tmp_path)
    feed = Counting()
    svc = DailyUpdateService(
        wh,
        SeedUniverse(),
        feed,
        feed,
        Cal(),
        seed_sessions=1,
        max_tickers=0,
        concurrency=1,
        open_window_minutes=5,
        eod_bulk=PartialBulk(),
    )
    svc._begin_peer_write = lambda who: None
    svc._minutes_ingesting = True
    report = svc.run("eod")
    assert not yahoo_calls
    assert report["eod_source"] == "defeatbeta"
    assert report["eod_ok"] == 1

