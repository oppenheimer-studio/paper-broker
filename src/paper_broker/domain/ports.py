from __future__ import annotations

from datetime import date, datetime
from typing import Any, Protocol

from paper_broker.domain.models import (
    Clock,
    CorporateAction,
    DailyBar,
    IngestRun,
    IngestStatus,
    MinuteOpenBar,
    QueryRequest,
    RawDailyBar,
    RawMinuteOpen,
    ScreenerRequest,
    ScreenerRow,
    Security,
    SecurityDraft,
    SystemEvent,
)


class UniverseFeed(Protocol):
    def fetch_us_stocks(self) -> list[SecurityDraft]: ...


class PriceFeed(Protocol):
    def fetch_eod(self, ticker: str, start: date, end: date) -> list[RawDailyBar]: ...

    def fetch_shares(self, ticker: str) -> int | None: ...


class MinuteFeed(Protocol):
    def fetch_open_windows(
        self, ticker: str, start: date, end: date, window_minutes: int
    ) -> list[RawMinuteOpen]: ...


class MarketCalendar(Protocol):
    def expected_as_of(self, now: datetime) -> date | None: ...

    def sessions(self, start: date, end: date) -> list[date]: ...


class Warehouse(Protocol):
    def upsert_securities(self, drafts: list[SecurityDraft]) -> list[Security]: ...

    def list_securities(self, market: str | None = "US") -> list[Security]: ...

    def security_by_ticker(self, ticker: str) -> Security | None: ...

    def rank_security_ids(self) -> list[int]: ...

    def dates_with_eod(self, security_id: int, start: date, end: date) -> set[date]: ...

    def dates_with_minute_open(
        self, security_id: int, start: date, end: date, window_minutes: int
    ) -> set[date]: ...

    def write_daily_bars(self, bars: list[DailyBar]) -> int: ...

    def write_minute_open(self, bars: list[MinuteOpenBar]) -> int: ...

    def write_corporate_actions(self, rows: list[CorporateAction]) -> int: ...

    def rewrite_derived(
        self, as_of: date, avg_n: int, atr_n: int, relvol_n: int, window_minutes: int
    ) -> int: ...

    def last_success_as_of(self) -> date | None: ...

    def start_run(self, as_of: date, notes: str = "") -> IngestRun: ...

    def finish_run(self, run_id: str, status: IngestStatus, notes: str, rows_upserted: int) -> None: ...

    def clock(self, expected: date | None, pending: list[date], ingest_running: bool) -> Clock: ...

    def append_event(
        self,
        *,
        level: str,
        source: str,
        code: str,
        title: str,
        detail: str = "",
        data: dict[str, Any] | None = None,
    ) -> SystemEvent: ...

    def list_events(self, limit: int = 50) -> list[SystemEvent]: ...

    def query(self, req: QueryRequest) -> list[dict[str, Any]]: ...

    def run_screener(self, req: ScreenerRequest, as_of: date) -> list[ScreenerRow]: ...

    def bars(self, ticker: str, start: date | None, end: date | None, limit: int) -> list[dict[str, Any]]: ...
