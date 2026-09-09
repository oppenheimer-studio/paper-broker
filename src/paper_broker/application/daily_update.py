from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from threading import Lock
from typing import Any, Callable
from zoneinfo import ZoneInfo

from paper_broker.application.catchup import pending_sessions
from paper_broker.domain.models import (
    CorporateAction,
    DailyBar,
    IngestStatus,
    MinuteOpenBar,
    Security,
)
from paper_broker.domain.ports import (
    BulkEodFeed,
    MarketCalendar,
    MinuteFeed,
    PriceFeed,
    UniverseFeed,
    Warehouse,
)
from paper_broker.logging import get_logger

log = get_logger("daily_update")
ASUNCION = ZoneInfo("America/Asuncion")
ET = ZoneInfo("America/New_York")
PHASES = {"all", "eod", "minutes"}


@dataclass
class _EodPass:
    rows: int = 0
    actions: int = 0
    ok: list[str] = field(default_factory=list)
    fail: list[str] = field(default_factory=list)
    source: str = "yahoo"


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
        eod_bulk: BulkEodFeed | None = None,
        eod_ready_attempts: int = 6,
        eod_ready_wait_s: float = 1800,
        eod_give_up_hour: int = 9,
        sleeper: Callable[[float], None] = time.sleep,
        now_fn: Callable[[], datetime] | None = None,
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
        self._eod_bulk = eod_bulk
        self._eod_ready_attempts = max(1, eod_ready_attempts)
        self._eod_ready_wait_s = max(0.0, eod_ready_wait_s)
        self._eod_give_up_hour = eod_give_up_hour
        self._sleeper = sleeper
        self._now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        self._lock = Lock()
        self._eod_busy = False
        self._minutes_busy = False
        self._eod_writing = False
        self._minutes_ingesting = False
        self.running = False
        self.last_report: dict | None = None

    def clock(self):
        now = self._now_fn()
        expected = self._calendar.expected_as_of(now)
        last = self._wh.last_success_as_of()
        cal_end = expected or now.date()
        cal = self._calendar.sessions(cal_end - timedelta(days=120), cal_end)
        pending = pending_sessions(
            last_success=last, expected=expected, calendar=cal, seed_sessions=self._seed
        )
        return self._wh.clock(expected, pending, self.running)

    def status(self) -> dict:
        return {
            "running": self.running,
            "eod_busy": self._eod_busy,
            "minutes_busy": self._minutes_busy,
            "report": self.last_report,
            "clock": self.clock().model_dump(),
        }

    def can_start(self, phase: str) -> bool:
        phase = (phase or "all").lower()
        if phase == "minutes":
            return not self._minutes_busy
        if phase == "eod":
            return not self._eod_busy
        return not self._eod_busy and not self._minutes_busy

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

    def run(self, phase: str = "all") -> dict:
        phase = (phase or "all").lower()
        if phase not in PHASES:
            return {"status": "error", "error": f"unknown phase {phase}"}
        started_eod = False
        started_minutes = False
        with self._lock:
            if not self.can_start(phase):
                log.warning("daily_already_running", phase=phase)
                return {"status": "already_running", "phase": phase, "report": self.last_report}
            if phase in {"all", "eod"}:
                self._eod_busy = True
                started_eod = True
            if phase in {"all", "minutes"}:
                self._minutes_busy = True
                started_minutes = True
            self.running = True
        try:
            report = self._run(phase)
            self.last_report = report
            status = report.get("status")
            if status == "already_running":
                return report
            level = "info" if status == "ok" else "warning" if status == "partial" else "error"
            finished_code = {
                "eod": "daily.eod_finished",
                "minutes": "daily.minutes_finished",
            }.get(phase, "daily.finished")
            self._emit(
                level,
                finished_code,
                f"{phase} update finished",
                detail=str(report.get("note") or report.get("error") or status),
                data=report,
            )
            return report
        except Exception as exc:
            log.exception("daily_failed", phase=phase)
            report = {"status": "error", "phase": phase, "error": str(exc)}
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
            with self._lock:
                if started_eod:
                    self._eod_busy = False
                    self._eod_writing = False
                if started_minutes:
                    self._minutes_busy = False
                    self._minutes_ingesting = False
                self.running = self._eod_busy or self._minutes_busy

    def _run(self, phase: str) -> dict:
        do_eod = phase in {"all", "eod"}
        do_minutes = phase in {"all", "minutes"}
        if hasattr(self._calendar, "invalidate"):
            self._calendar.invalidate()
        now = self._now_fn()
        expected = self._calendar.expected_as_of(now)
        last = self._wh.last_success_as_of()
        if expected is None:
            log.error("no_expected_as_of")
            return {"status": "error", "phase": phase, "error": "no QQQ calendar"}
        cal = self._calendar.sessions(expected - timedelta(days=120), expected)
        pending = pending_sessions(
            last_success=last, expected=expected, calendar=cal, seed_sessions=self._seed
        )
        self._emit(
            "info",
            "daily.started",
            f"{phase} update started",
            detail=f"{len(pending)} pending session(s)",
            data={
                "phase": phase,
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
            phase=phase,
            last_success=str(last) if last else None,
            expected=str(expected),
            pending=[str(d) for d in pending],
            now_utc=now.isoformat(),
            now_et=now.astimezone(ET).isoformat(),
            now_asuncion=now.astimezone(ASUNCION).isoformat(),
        )
        if not pending:
            return {"status": "ok", "phase": phase, "pending": [], "note": "nothing to do"}

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
            phase=phase,
            universe_n=len(securities),
            ingest_n=len(chosen),
            cap=self._max_tickers,
            source=source,
        )

        start, end = pending[0], pending[-1]
        eod = _EodPass()
        minutes = _MinutePass()

        if do_eod:
            blocked = self._wait_eod_ready(pending)
            if blocked is not None:
                blocked.update(
                    {
                        "phase": phase,
                        "pending": [str(d) for d in pending],
                        "tickers": len(chosen),
                        "universe_n": len(securities),
                        "ingest_n": len(chosen),
                    }
                )
                return blocked
            if phase == "eod":
                self._begin_peer_write("eod")
            else:
                self._eod_writing = True
            try:
                eod = self._ingest_eod(chosen, start, end)
                if eod.fail:
                    retry_eod = [s for s in chosen if s.ticker in set(eod.fail)]
                    log.info("eod_retry", n=len(retry_eod))
                    extra = self._ingest_eod(retry_eod, start, end, yahoo_only=True)
                    eod = _EodPass(
                        rows=eod.rows + extra.rows,
                        actions=eod.actions + extra.actions,
                        ok=sorted(set(eod.ok + extra.ok)),
                        fail=extra.fail,
                        source=eod.source if not extra.ok else "mixed",
                    )
            finally:
                self._eod_writing = False

        if do_minutes:
            if phase == "minutes":
                self._begin_peer_write("minutes")
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

        if (do_eod and eod.fail) or (do_minutes and (minutes.fail or minutes.empty)):
            self._emit(
                "warning",
                "daily.ticker_errors",
                "Some tickers failed during ingest",
                detail=(
                    f"phase={phase} universe={len(chosen)} eod_ok={len(eod.ok)} eod_fail={len(eod.fail)} "
                    f"minute_ok={len(minutes.ok)} minute_empty={len(minutes.empty)} "
                    f"minute_fail={len(minutes.fail)}"
                ),
                data={
                    "phase": phase,
                    "universe": len(chosen),
                    "eod_ok": len(eod.ok),
                    "eod_fail": eod.fail,
                    "minute_ok": len(minutes.ok),
                    "minute_empty": minutes.empty,
                    "minute_fail": minutes.fail,
                },
            )

        session_reports: list[dict] = []
        if do_eod:
            session_reports = self._finalize_sessions(chosen, pending, eod, minutes)
            self._sync_minio()
            ok = [s for s in session_reports if s["status"] == "success"]
            if not session_reports:
                status = "error"
            elif len(ok) == len(session_reports):
                status = "ok"
            elif ok:
                status = "partial"
            else:
                status = "error"
        else:
            self._sync_minio()
            if minutes.fail and not minutes.ok:
                status = "error"
            elif minutes.fail or minutes.empty:
                status = "partial"
            else:
                status = "ok"

        return {
            "status": status,
            "phase": phase,
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
            "eod_source": eod.source,
            "eod_ok": len(eod.ok),
            "eod_fail": eod.fail,
            "minute_ok": len(minutes.ok),
            "minute_empty": minutes.empty,
            "minute_fail": minutes.fail,
            "sessions": session_reports,
        }

    def _wait_eod_ready(self, pending: list[date]) -> dict | None:
        if self._eod_bulk is None:
            return None
        for attempt in range(1, self._eod_ready_attempts + 1):
            now = self._now_fn()
            local = now.astimezone(ASUNCION)
            ready = False
            try:
                ready = bool(self._eod_bulk.sessions_ready(pending))
            except Exception:
                log.exception("defeatbeta_ready_check_failed", attempt=attempt)
            if ready:
                log.info("defeatbeta_ready", attempt=attempt, pending=[str(d) for d in pending])
                return None
            past_deadline = (local.hour, local.minute, local.second) >= (self._eod_give_up_hour, 0, 0)
            last = attempt >= self._eod_ready_attempts
            log.warning(
                "defeatbeta_not_ready",
                attempt=attempt,
                attempts=self._eod_ready_attempts,
                now_asuncion=local.isoformat(),
                give_up_hour=self._eod_give_up_hour,
                pending=[str(d) for d in pending],
            )
            if past_deadline or last:
                detail = (
                    f"DefeatbetaFeed not ready for {[str(d) for d in pending]} "
                    f"after {attempt} attempt(s); gave up at {local.strftime('%H:%M')} America/Asuncion"
                )
                self._emit(
                    "error",
                    "daily.eod_not_ready",
                    "Daily EOD sync skipped",
                    detail=detail,
                    data={
                        "pending": [str(d) for d in pending],
                        "attempts": attempt,
                        "now_asuncion": local.isoformat(),
                        "give_up_hour": self._eod_give_up_hour,
                    },
                )
                return {
                    "status": "error",
                    "error": "defeatbeta_not_ready",
                    "note": detail,
                    "attempts": attempt,
                }
            self._emit(
                "info",
                "daily.eod_waiting",
                "Waiting for DefeatbetaFeed",
                detail=f"attempt {attempt}/{self._eod_ready_attempts}; retry in {int(self._eod_ready_wait_s)}s",
                data={"attempt": attempt, "wait_s": self._eod_ready_wait_s},
            )
            self._sleeper(self._eod_ready_wait_s)
        return {
            "status": "error",
            "error": "defeatbeta_not_ready",
            "note": "DefeatbetaFeed not ready",
        }

    def _begin_peer_write(self, who: str) -> None:
        while True:
            with self._lock:
                if who == "eod" and not self._minutes_ingesting:
                    self._eod_writing = True
                    return
                if who == "minutes" and not self._eod_writing:
                    self._minutes_ingesting = True
                    return
            log.info("wait_peer_write", who=who)
            self._sleeper(5)

    def _finalize_sessions(
        self,
        chosen: list[Security],
        pending: list[date],
        eod: _EodPass,
        minutes: _MinutePass,
    ) -> list[dict]:
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
                    f"derived={derived_n} source={eod.source}"
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
        return session_reports

    def _sync_minio(self) -> None:
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

    def _ingest_eod(
        self,
        securities: list[Security],
        start: date,
        end: date,
        *,
        yahoo_only: bool = False,
    ) -> _EodPass:
        needed = set(self._calendar.sessions(start, end))
        out = _EodPass(source="yahoo")
        remaining = list(securities)

        if self._eod_bulk and not yahoo_only:
            try:
                raw_bars, raw_actions = self._eod_bulk.fetch_range(start, end)
            except Exception:
                log.exception("defeatbeta_fetch_failed")
                out.fail = [s.ticker for s in securities]
                return out
            if raw_bars or raw_actions:
                out.source = "defeatbeta"
            grouped: dict[str, list] = {}
            for bar in raw_bars:
                grouped.setdefault(bar.ticker, []).append(bar)
            actions_by: dict[str, list] = {}
            for action in raw_actions:
                actions_by.setdefault(action.ticker, []).append(action)
            still: list[Security] = []
            for sec in remaining:
                have = self._wh.dates_with_eod(sec.security_id, start, end)
                if have == needed:
                    out.ok.append(sec.ticker)
                    continue
                raw = grouped.get(sec.ticker, [])
                bars, corp = self._to_stored(sec, raw, actions_by.get(sec.ticker, []), start, end, have)
                if bars:
                    out.rows += self._wh.write_daily_bars(bars)
                if corp:
                    out.actions += self._wh.write_corporate_actions(corp)
                got = have | {b.date for b in bars}
                if needed - got:
                    still.append(sec)
                else:
                    out.ok.append(sec.ticker)
            remaining = still
            if remaining:
                out.source = "mixed"
                log.info("eod_yahoo_fallback", n=len(remaining))

        def one(sec: Security) -> tuple[list[DailyBar], list[CorporateAction], str | None]:
            have = haves[sec.ticker]
            if have == needed:
                log.debug("eod_skip", ticker=sec.ticker, reason="already_complete")
                return [], [], None
            try:
                raw, actions = self._fetch_session(sec.ticker, start, end)
            except Exception:
                log.exception("eod_fail", ticker=sec.ticker)
                return [], [], sec.ticker
            bars, corp = self._to_stored(sec, raw, actions, start, end, have)
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

        haves = {s.ticker: self._wh.dates_with_eod(s.security_id, start, end) for s in remaining}

        with ThreadPoolExecutor(max_workers=self._concurrency) as pool:
            futs = {pool.submit(one, s): s.ticker for s in remaining}
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
        if not remaining and not out.fail:
            out.ok = sorted(set(out.ok) | {s.ticker for s in securities})
        log.info("eod_done", rows=out.rows, actions=out.actions, ok=len(out.ok), fails=len(out.fail), source=out.source)
        return out

    def _to_stored(
        self,
        sec: Security,
        raw,
        actions,
        start: date,
        end: date,
        have: set[date],
    ) -> tuple[list[DailyBar], list[CorporateAction]]:
        bars: list[DailyBar] = []
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
        return bars, corp

    def _ingest_minute_open(self, securities: list[Security], start: date, end: date) -> _MinutePass:
        needed = set(self._calendar.sessions(start, end))
        self._minutes_ingesting = True

        haves = {
            s.ticker: self._wh.dates_with_minute_open(s.security_id, start, end, self._window)
            for s in securities
        }

        def one(sec: Security) -> tuple[list[MinuteOpenBar], str | None, str | None]:
            have = haves[sec.ticker]
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
        try:
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
        finally:
            self._minutes_ingesting = False
        log.info(
            "minute_open_done",
            rows=out.rows,
            ok=len(out.ok),
            empty=len(out.empty),
            fails=len(out.fail),
        )
        return out
