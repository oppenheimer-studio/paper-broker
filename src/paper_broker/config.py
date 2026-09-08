from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    lake_path: Path = Path("./data/lake")
    admin_key: str = "changeme"
    host: str = "0.0.0.0"
    port: int = 8080
    mcp_port: int = 8081
    log_level: str = "info"
    log_json: bool = False
    ingest_max_tickers: int = 0
    ingest_concurrency: int = 6
    seed_sessions: int = 14
    open_window_minutes: int = 5
    http_timeout_s: float = 30
    yahoo_user_agent: str = "paper-broker/0.1"
    minio_endpoint: str | None = None
    minio_access_key: str | None = None
    minio_secret_key: str | None = None
    minio_bucket: str = "paper-broker"
    minio_secure: bool = False
    database_url: str | None = None
