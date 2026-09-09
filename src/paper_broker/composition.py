from __future__ import annotations

from dataclasses import dataclass

from paper_broker.adapters.defeatbeta import DefeatbetaFeed
from paper_broker.adapters.duckdb_warehouse import DuckDbWarehouse
from paper_broker.adapters.minio_sync import MinioSync
from paper_broker.adapters.nasdaq import NasdaqUniverse
from paper_broker.adapters.qqq_calendar import QqqCalendar
from paper_broker.adapters.yahoo import YahooFeed
from paper_broker.application.daily_update import DailyUpdateService
from paper_broker.application.queries import QueryService
from paper_broker.application.screener import ScreenerService
from paper_broker.config import Settings


@dataclass
class Container:
    settings: Settings
    warehouse: DuckDbWarehouse
    yahoo: YahooFeed
    defeatbeta: DefeatbetaFeed | None
    daily: DailyUpdateService
    screener: ScreenerService
    queries: QueryService


def build(settings: Settings | None = None) -> Container:
    settings = settings or Settings()
    settings.lake_path.mkdir(parents=True, exist_ok=True)
    warehouse = DuckDbWarehouse(settings.lake_path)
    yahoo = YahooFeed(
        settings.yahoo_user_agent,
        settings.http_timeout_s,
        max_requests_per_hour=settings.yahoo_max_requests_per_hour,
    )
    defeatbeta = None
    if settings.defeatbeta_enabled:
        defeatbeta = DefeatbetaFeed(
            settings.lake_path / "defeatbeta",
            timeout=settings.http_timeout_s,
            base_url=settings.defeatbeta_base_url,
        )
    universe = NasdaqUniverse(timeout=settings.http_timeout_s, warehouse=warehouse)
    calendar = QqqCalendar(yahoo, warehouse=warehouse)
    minio = None
    if settings.minio_endpoint and settings.minio_access_key and settings.minio_secret_key:
        minio = MinioSync(
            settings.minio_endpoint,
            settings.minio_access_key,
            settings.minio_secret_key,
            settings.minio_bucket,
            secure=settings.minio_secure,
        )
    daily = DailyUpdateService(
        warehouse,
        universe,
        yahoo,
        yahoo,
        calendar,
        seed_sessions=settings.seed_sessions,
        max_tickers=settings.ingest_max_tickers,
        concurrency=settings.ingest_concurrency,
        open_window_minutes=settings.open_window_minutes,
        minio_sync=minio,
        lake_path=settings.lake_path,
        eod_bulk=defeatbeta,
        eod_ready_attempts=settings.eod_ready_attempts,
        eod_ready_wait_s=settings.eod_ready_wait_s,
        eod_give_up_hour=settings.eod_give_up_hour,
    )
    return Container(
        settings=settings,
        warehouse=warehouse,
        yahoo=yahoo,
        defeatbeta=defeatbeta,
        daily=daily,
        screener=ScreenerService(warehouse),
        queries=QueryService(warehouse),
    )
