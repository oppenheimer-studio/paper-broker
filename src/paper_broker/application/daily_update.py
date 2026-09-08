from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from threading import Lock

from paper_broker.application.catchup import pending_sessions
from paper_broker.domain.models import (
    DailyBar,
    IngestStatus,
    MinuteOpenBar,
    Security,
)
from paper_broker.domain.ports import MarketCalendar, MinuteFeed, PriceFeed, UniverseFeed, Warehouse
from paper_broker.logging import get_logger

log = get_logger("daily_update")


class DailyUpdateService:
    def __init__(
        self,
        warehouse: Warehouse,
        universe: UniverseFeed,
        prices: PriceFeed,
        minutes: MinuteFeed,
        calendar: MarketCalendar,
        *,
        seed_sessions: int,
        max_tickers: int,
        concurrency: int,
        open_window_minutes: int,
        minio_sync=None,
        lake_path=None,
    ) -> None:
        self._wh = warehouse
        self._universe = universe
        self._prices = prices
        self._minutes = minutes
        self._calendar = calendar
        self._seed = seed_sessions
        self._max_tickers = max_tickers
        self._concurrency = max(1, concurrency)
        self._window = open_window_minutes
        self._minio = minio_sync
        self._lake = lake_path
        self._lock = Lock()
        self.running = False
        self.last_report: dict | None = None

    def clock(self):
        now = datetime.now(timezone.utc)
        expected = self._calendar.expected_as_of(now)
        last = self._wh.last_success_as_of()
        cal_end = expected or now.date()
        cal = self._calendar.sessions(cal_end - timedelta(days=120), cal_end)
        pending = pending_sessions(
            last_success=last, expected=expected, calendar=cal, seed_sessions=self._seed
        )
        return self._wh.clock(expected, pending, self.running)

    def run(self) -> dict:
        with self._lock:
            if self.running:
                log.warning("daily_already_running")
                return {"status": "already_running", "report": self.last_report}
            self.running = True
        try:
            report = self._run()
            self.last_report = report
            return report
        finally:
            self.running = False

    def _run(self) -> dict:
        if hasattr(self._calendar, "invalidate"):
            self._calendar.invalidate()
        now = datetime.now(timezone.utc)
        expected = self._calendar.expected_as_of(now)
        last = self._wh.last_success_as_of()
        if expected is None:
            log.error("no_expected_as_of")
            return {"status": "error", "error": "no QQQ calendar"}
        cal = self._calendar.sessions(expected - timedelta(days=120), expected)
        pending = pending_sessions(
            last_success=last, expected=expected, calendar=cal, seed_sessions=self._seed
        )
        log.info(
            "daily_start",
            last_success=str(last) if last else None,
            expected=str(expected),
            pending=[str(d) for d in pending],
        )
        if not pending:
            return {"status": "ok", "pending": [], "note": "nothing to do"}

        drafts = self._universe.fetch_us_stocks()
        securities = self._wh.upsert_securities(drafts)
        chosen = self._choose(securities)
        log.info("universe_ranked", n=len(chosen), cap=self._max_tickers)

        start, end = pending[0], pending[-1]
        eod_rows = self._ingest_eod(chosen, start, end)
        open_rows = self._ingest_minute_open(chosen, start, end)

        session_reports = []
        for session in pending:
            run = self._wh.start_run(session, notes="catch-up")
            try:
                derived_n = self._wh.rewrite_derived(
                    session,
                    avg_n=14,
                    atr_n=14,
                    relvol_n=14,
                    window_minutes=self._window,
                )
                note = f"eod={eod_rows} minute_open={open_rows} derived={derived_n}"
                self._wh.finish_run(run.run_id, IngestStatus.SUCCESS, note, eod_rows + open_rows + derived_n)
                session_reports.append({"as_of": str(session), "status": "success", "derived": derived_n})
                log.info("session_success", as_of=str(session), derived=derived_n)
            except Exception as exc:
                log.exception("session_failed", as_of=str(session))
                self._wh.finish_run(run.run_id, IngestStatus.ERROR, str(exc), 0)
                session_reports.append({"as_of": str(session), "status": "error", "error": str(exc)})
                break

        if self._minio and self._lake:
            try:
                self._minio.sync_tree(self._lake)
            except Exception:
                log.exception("minio_sync_failed")

        return {
            "status": "ok" if session_reports and session_reports[-1]["status"] == "success" else "partial",
            "pending": [str(d) for d in pending],
            "tickers": len(chosen),
            "eod_upserts": eod_rows,
            "minute_open_upserts": open_rows,
            "sessions": session_reports,
        }

    def _choose(self, securities: list[Security]) -> list[Security]:
        by_id = {s.security_id: s for s in securities}
        ranked_ids = self._wh.rank_security_ids()
        if not ranked_ids:
            ranked_ids = [s.security_id for s in securities]
        ordered: list[Security] = []
        seen: set[int] = set()
        qqq = next((s for s in securities if s.ticker == "QQQ"), None)
        if qqq:
            ordered.append(qqq)
            seen.add(qqq.security_id)
        for sid in ranked_ids:
            if sid in seen or sid not in by_id:
                continue
            sec = by_id[sid]
            if sec.listing_status == "benchmark":
                continue
            ordered.append(sec)
            seen.add(sid)
            if self._max_tickers and len([s for s in ordered if s.listing_status != "benchmark"]) >= self._max_tickers:
                break
        return ordered

    def _ingest_eod(self, securities: list[Security], start: date, end: date) -> int:
        def one(sec: Security) -> list[DailyBar]:
            have = self._wh.dates_with_eod(sec.security_id, start, end)
            need_end = end
            need_start = start
            if have == set(self._calendar.sessions(start, end)):
                log.info("eod_skip", ticker=sec.ticker, reason="already_complete")
                return []
            try:
                raw = self._prices.fetch_eod(sec.ticker, need_start, need_end)
            except Exception:
                log.exception("eod_fail", ticker=sec.ticker)
                return []
            bars = []
            for r in raw:
                if r.date < start or r.date > end or r.date in have:
                    continue
                bars.append(
                    DailyBar(
                        security_id=sec.security_id,
                        date=r.date,
                        open=r.open,
                        high=r.high,
                        low=r.low,
                        close=r.close,
                        adj_close=r.adj_close,
                        volume=r.volume,
                        source=r.source,
                    )
                )
            log.info("eod_ok", ticker=sec.ticker, n=len(bars), skipped=len(have))
            return bars

        written = 0
        with ThreadPoolExecutor(max_workers=self._concurrency) as pool:
            futs = {pool.submit(one, s): s.ticker for s in securities}
            for fut in as_completed(futs):
                ticker = futs[fut]
                try:
                    bars = fut.result()
                except Exception:
                    log.exception("eod_worker_fail", ticker=ticker)
                    continue
                if bars:
                    written += self._wh.write_daily_bars(bars)
        log.info("eod_done", rows=written)
        return written

    def _ingest_minute_open(self, securities: list[Security], start: date, end: date) -> int:
        def one(sec: Security) -> list[MinuteOpenBar]:
            have = self._wh.dates_with_minute_open(sec.security_id, start, end, self._window)
            if have == set(self._calendar.sessions(start, end)):
                log.info("minute_skip", ticker=sec.ticker, reason="already_complete")
                return []
            try:
                raw = self._minutes.fetch_open_windows(sec.ticker, start, end, self._window)
            except Exception:
                log.exception("minute_fail", ticker=sec.ticker)
                return []
            bars = []
            for r in raw:
                if r.date < start or r.date > end or r.date in have:
                    continue
                bars.append(
                    MinuteOpenBar(
                        security_id=sec.security_id,
                        date=r.date,
                        window_minutes=r.window_minutes,
                        open=r.open,
                        high=r.high,
                        low=r.low,
                        close=r.close,
                        volume=r.volume,
                        source=r.source,
                    )
                )
            log.info("minute_ok", ticker=sec.ticker, n=len(bars))
            return bars

        written = 0
        with ThreadPoolExecutor(max_workers=self._concurrency) as pool:
            futs = {pool.submit(one, s): s.ticker for s in securities}
            for fut in as_completed(futs):
                ticker = futs[fut]
                try:
                    bars = fut.result()
                except Exception:
                    log.exception("minute_worker_fail", ticker=ticker)
                    continue
                if bars:
                    written += self._wh.write_minute_open(bars)
        log.info("minute_open_done", rows=written)
        return written
