from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from threading import Lock
from typing import Any
from zoneinfo import ZoneInfo

from paper_broker.application.catchup import pending_sessions
from paper_broker.domain.models import (
    CorporateAction,
    DailyBar,
    IngestStatus,
    MinuteOpenBar,
    Security,
)
from paper_broker.domain.ports import MarketCalendar, MinuteFeed, PriceFeed, UniverseFeed, Warehouse
from paper_broker.logging import get_logger

log = get_logger("daily_update")
ASUNCION = ZoneInfo("America/Asuncion")
ET = ZoneInfo("America/New_York")


@dataclass
class _EodPass:
    rows: int = 0
    actions: int = 0
    ok: list[str] = field(default_factory=list)
    fail: list[str] = field(default_factory=list)


@dataclass
class _MinutePass:
    rows: int = 0
    ok: list[str] = field(default_factory=list)
    empty: list[str] = field(default_factory=list)
    fail: list[str] = field(default_factory=list)


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

    def _emit(
        self,
        level: str,
        code: str,
        title: str,
        detail: str = "",
        data: dict[str, Any] | None = None,
    ) -> None:
        try:
            self._wh.append_event(
                level=level,
                source="daily",
                code=code,
                title=title,
                detail=detail,
                data=data,
            )
        except Exception:
            log.exception("event_emit_failed", code=code)

    def run(self) -> dict:
        with self._lock:
            if self.running:
                log.warning("daily_already_running")
                return {"status": "already_running", "report": self.last_report}
            self.running = True
        try:
            report = self._run()
            self.last_report = report
            status = report.get("status")
            level = "info" if status == "ok" else "warning" if status == "partial" else "error"
            self._emit(
                level,
                "daily.finished",
                "Daily update finished",
                detail=str(report.get("note") or report.get("error") or status),
                data=report,
            )
            return report
        except Exception as exc:
            log.exception("daily_failed")
            report = {"status": "error", "error": str(exc)}
            self.last_report = report
            self._emit(
                "error",
                "daily.failed",
                "Daily update crashed",
                detail=str(exc),
                data=report,
            )
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
        self._emit(
            "info",
            "daily.started",
            "Daily update started",
            detail=f"{len(pending)} pending session(s)",
            data={
                "last_success": str(last) if last else None,
                "expected": str(expected),
                "pending": [str(d) for d in pending],
                "now_utc": now.isoformat(),
                "now_et": now.astimezone(ET).isoformat(),
                "now_asuncion": now.astimezone(ASUNCION).isoformat(),
            },
        )
        log.info(
            "daily_start",
            last_success=str(last) if last else None,
            expected=str(expected),
            pending=[str(d) for d in pending],
            now_utc=now.isoformat(),
            now_et=now.astimezone(ET).isoformat(),
            now_asuncion=now.astimezone(ASUNCION).isoformat(),
        )
        if not pending:
            return {"status": "ok", "pending": [], "note": "nothing to do"}

        if hasattr(self._universe, "fetch_universe"):
            snap = self._universe.fetch_universe()
            drafts = snap.drafts
            source = snap.source
            warnings = list(snap.warnings)
        else:
            drafts = self._universe.fetch_us_stocks()
            source = "nasdaq"
            warnings = []

        if source != "nasdaq":
            self._emit(
                "warning",
                "universe.fallback",
                f"Universe fallback: {source}",
                detail="; ".join(warnings) or f"source={source}",
                data={"source": source, "warnings": warnings, "n": len(drafts)},
            )

        securities = self._wh.upsert_securities(drafts)
        chosen = self._choose(securities)
        log.info(
            "universe_ranked",
            universe_n=len(securities),
            ingest_n=len(chosen),
            cap=self._max_tickers,
            source=source,
        )

        start, end = pending[0], pending[-1]
        eod = self._ingest_eod(chosen, start, end)
        if eod.fail:
            retry_eod = [s for s in chosen if s.ticker in set(eod.fail)]
            log.info("eod_retry", n=len(retry_eod))
            extra = self._ingest_eod(retry_eod, start, end)
            eod = _EodPass(
                rows=eod.rows + extra.rows,
                actions=eod.actions + extra.actions,
                ok=sorted(set(eod.ok + extra.ok)),
                fail=extra.fail,
            )
        minutes = self._ingest_minute_open(chosen, start, end)
        if minutes.fail or minutes.empty:
            retry_m = [s for s in chosen if s.ticker in set(minutes.fail + minutes.empty)]
            log.info("minute_retry", n=len(retry_m))
            extra_m = self._ingest_minute_open(retry_m, start, end)
            minutes = _MinutePass(
                rows=minutes.rows + extra_m.rows,
                ok=sorted(set(minutes.ok + extra_m.ok)),
                empty=extra_m.empty,
                fail=extra_m.fail,
            )

        if eod.fail or minutes.fail or minutes.empty:
            self._emit(
                "warning",
                "daily.ticker_errors",
                "Some tickers failed during ingest",
                detail=(
                    f"universe={len(chosen)} eod_ok={len(eod.ok)} eod_fail={len(eod.fail)} "
                    f"minute_ok={len(minutes.ok)} minute_empty={len(minutes.empty)} "
                    f"minute_fail={len(minutes.fail)}"
                ),
                data={
                    "universe": len(chosen),
                    "eod_ok": len(eod.ok),
                    "eod_fail": eod.fail,
                    "minute_ok": len(minutes.ok),
                    "minute_empty": minutes.empty,
                    "minute_fail": minutes.fail,
                },
            )

        qqq = next((s for s in chosen if s.ticker == "QQQ"), None)
        session_reports = []
        for session in pending:
            run = self._wh.start_run(session, notes="catch-up")
            try:
                if qqq and session not in self._wh.dates_with_eod(qqq.security_id, session, session):
                    raise RuntimeError(f"QQQ missing EOD for {session}")
                derived_n = self._wh.rewrite_derived(
                    session,
                    avg_n=14,
                    atr_n=14,
                    relvol_n=14,
                    window_minutes=self._window,
                )
                note = (
                    f"eod={eod.rows} minute_open={minutes.rows} actions={eod.actions} "
                    f"derived={derived_n}"
                )
                self._wh.finish_run(
                    run.run_id, IngestStatus.SUCCESS, note, eod.rows + minutes.rows + derived_n
                )
                session_reports.append({"as_of": str(session), "status": "success", "derived": derived_n})
                log.info("session_success", as_of=str(session), derived=derived_n)
            except Exception as exc:
                log.exception("session_failed", as_of=str(session))
                self._wh.finish_run(run.run_id, IngestStatus.ERROR, str(exc), 0)
                session_reports.append({"as_of": str(session), "status": "error", "error": str(exc)})
                self._emit(
                    "error",
                    "daily.session_error",
                    f"Session {session} failed",
                    detail=str(exc),
                    data={"as_of": str(session)},
                )

        if self._minio and self._lake:
            try:
                self._minio.sync_tree(self._lake)
            except Exception as exc:
                log.exception("minio_sync_failed")
                self._emit(
                    "warning",
                    "daily.minio_sync_failed",
                    "MinIO sync failed",
                    detail=str(exc),
                )

        ok = [s for s in session_reports if s["status"] == "success"]
        if not session_reports:
            status = "error"
        elif len(ok) == len(session_reports):
            status = "ok"
        elif ok:
            status = "partial"
        else:
            status = "error"
        return {
            "status": status,
            "pending": [str(d) for d in pending],
            "tickers": len(chosen),
            "universe_n": len(securities),
            "ingest_n": len(chosen),
            "cap": self._max_tickers,
            "universe_source": source,
            "universe_warnings": warnings,
            "eod_upserts": eod.rows,
            "minute_open_upserts": minutes.rows,
            "corporate_actions": eod.actions,
            "eod_ok": len(eod.ok),
            "eod_fail": eod.fail,
            "minute_ok": len(minutes.ok),
            "minute_empty": minutes.empty,
            "minute_fail": minutes.fail,
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

    def _fetch_session(self, ticker: str, start: date, end: date):
        fetch_session = getattr(self._prices, "fetch_session", None)
        if callable(fetch_session):
            return fetch_session(ticker, start, end)
        return self._prices.fetch_eod(ticker, start, end), []

    def _ingest_eod(self, securities: list[Security], start: date, end: date) -> _EodPass:
        needed = set(self._calendar.sessions(start, end))

        def one(sec: Security) -> tuple[list[DailyBar], list[CorporateAction], str | None]:
            have = self._wh.dates_with_eod(sec.security_id, start, end)
            if have == needed:
                log.debug("eod_skip", ticker=sec.ticker, reason="already_complete")
                return [], [], None
            try:
                raw, actions = self._fetch_session(sec.ticker, start, end)
            except Exception:
                log.exception("eod_fail", ticker=sec.ticker)
                return [], [], sec.ticker
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
            corp: list[CorporateAction] = []
            for a in actions:
                if a.date < start or a.date > end:
                    continue
                corp.append(
                    CorporateAction(
                        security_id=sec.security_id,
                        date=a.date,
                        action=a.action,
                        value=a.value,
                        numerator=a.numerator,
                        denominator=a.denominator,
                        source=a.source,
                    )
                )
            log.debug("eod_ok", ticker=sec.ticker, n=len(bars), actions=len(corp), skipped=len(have))
            got = have | {b.date for b in bars}
            incomplete = needed - got
            if incomplete:
                log.warning(
                    "eod_incomplete",
                    ticker=sec.ticker,
                    missing=[str(d) for d in sorted(incomplete)],
                )
                return bars, corp, sec.ticker
            return bars, corp, None

        out = _EodPass()
        with ThreadPoolExecutor(max_workers=self._concurrency) as pool:
            futs = {pool.submit(one, s): s.ticker for s in securities}
            for fut in as_completed(futs):
                ticker = futs[fut]
                try:
                    bars, corp, fail = fut.result()
                except Exception:
                    log.exception("eod_worker_fail", ticker=ticker)
                    out.fail.append(ticker)
                    continue
                if fail:
                    out.fail.append(fail)
                else:
                    out.ok.append(ticker)
                if bars:
                    out.rows += self._wh.write_daily_bars(bars)
                if corp:
                    out.actions += self._wh.write_corporate_actions(corp)
        log.info("eod_done", rows=out.rows, actions=out.actions, ok=len(out.ok), fails=len(out.fail))
        return out

    def _ingest_minute_open(self, securities: list[Security], start: date, end: date) -> _MinutePass:
        needed = set(self._calendar.sessions(start, end))

        def one(sec: Security) -> tuple[list[MinuteOpenBar], str | None, str | None]:
            have = self._wh.dates_with_minute_open(sec.security_id, start, end, self._window)
            if have == needed:
                log.debug("minute_skip", ticker=sec.ticker, reason="already_complete")
                return [], None, None
            try:
                raw = self._minutes.fetch_open_windows(sec.ticker, start, end, self._window)
            except Exception:
                log.exception("minute_fail", ticker=sec.ticker)
                return [], sec.ticker, None
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
            got = have | {b.date for b in bars}
            if needed - got:
                log.warning(
                    "minute_empty",
                    ticker=sec.ticker,
                    missing=[str(d) for d in sorted(needed - got)],
                )
                return bars, None, sec.ticker
            log.debug("minute_ok", ticker=sec.ticker, n=len(bars))
            return bars, None, None

        out = _MinutePass()
        with ThreadPoolExecutor(max_workers=self._concurrency) as pool:
            futs = {pool.submit(one, s): s.ticker for s in securities}
            for fut in as_completed(futs):
                ticker = futs[fut]
                try:
                    bars, fail, empty = fut.result()
                except Exception:
                    log.exception("minute_worker_fail", ticker=ticker)
                    out.fail.append(ticker)
                    continue
                if fail:
                    out.fail.append(fail)
                    continue
                if bars:
                    out.rows += self._wh.write_minute_open(bars)
                if empty:
                    out.empty.append(empty)
                else:
                    out.ok.append(ticker)
        log.info(
            "minute_open_done",
            rows=out.rows,
            ok=len(out.ok),
            empty=len(out.empty),
            fails=len(out.fail),
        )
        return out
