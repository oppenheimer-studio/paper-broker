from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class AssetType(StrEnum):
    STOCK = "stock"
    ADR = "adr"
    ETF = "etf"


class IngestStatus(StrEnum):
    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"


class Security(BaseModel):
    security_id: int
    ticker: str
    name: str
    exchange: str
    asset_type: AssetType
    listing_status: str
    market: str = "US"
    sector: str | None = None
    industry: str | None = None


class SecurityDraft(BaseModel):
    ticker: str
    name: str
    exchange: str
    asset_type: AssetType = AssetType.STOCK
    listing_status: str = "active"
    market: str = "US"


class DailyBar(BaseModel):
    security_id: int
    date: date
    open: float
    high: float
    low: float
    close: float
    adj_close: float
    volume: float
    source: str = "yahoo"


class RawDailyBar(BaseModel):
    ticker: str
    date: date
    open: float
    high: float
    low: float
    close: float
    adj_close: float
    volume: float
    source: str = "yahoo"


class MinuteOpenBar(BaseModel):
    security_id: int
    date: date
    window_minutes: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    source: str = "yahoo"


class RawMinuteOpen(BaseModel):
    ticker: str
    date: date
    window_minutes: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    source: str = "yahoo"


class RawCorporateAction(BaseModel):
    ticker: str
    date: date
    action: str
    value: float | None = None
    numerator: float | None = None
    denominator: float | None = None
    source: str = "yahoo"


class CorporateAction(BaseModel):
    security_id: int
    date: date
    action: str
    value: float | None = None
    numerator: float | None = None
    denominator: float | None = None
    source: str = "yahoo"


class IngestRun(BaseModel):
    run_id: str
    as_of: date
    status: IngestStatus
    started_at: datetime
    finished_at: datetime | None = None
    notes: str = ""
    rows_upserted: int = 0


class Clock(BaseModel):
    as_of: date | None
    last_success: date | None
    expected: date | None
    pending_sessions: list[date]
    ingest_running: bool = False


class SystemEvent(BaseModel):
    id: str
    ts: datetime
    level: str
    source: str
    code: str
    title: str
    detail: str = ""
    data: str = "{}"


class FilterOp(StrEnum):
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    EQ = "eq"


class ScreenerFilter(BaseModel):
    field: str
    op: FilterOp
    value: Any
    lookback: int | None = None
    window_minutes: int | None = None


class ScreenerRequest(BaseModel):
    as_of: date | None = None
    preset: str | None = None
    filters: list[ScreenerFilter] = Field(default_factory=list)
    limit: int = Field(default=100, ge=1, le=2000)
    sort: str | None = "market_cap"
    sort_dir: str = "desc"


class ScreenerRow(BaseModel):
    security_id: int
    ticker: str
    name: str
    exchange: str
    market: str
    as_of: date | None = None
    price: float | None
    avg_volume: float | None
    atr: float | None
    rel_vol_at: float | None
    rel_vol_at_sessions: int | None
    dollar_volume: float | None
    market_cap: float | None
    first5m_volume: float | None


class QueryWhere(BaseModel):
    field: str
    op: str
    value: Any


class QueryOrder(BaseModel):
    field: str
    dir: str = "asc"


class QueryRequest(BaseModel):
    table: str
    select: list[str | dict[str, Any]]
    where: list[QueryWhere] = Field(default_factory=list)
    group_by: list[str] = Field(default_factory=list)
    order_by: list[QueryOrder] = Field(default_factory=list)
    limit: int = Field(default=100, ge=1, le=5000)
