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
    yahoo_user_agent: str = (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    )
    minio_endpoint: str | None = None
    minio_access_key: str | None = None
    minio_secret_key: str | None = None
    minio_bucket: str = "paper-broker"
    minio_secure: bool = False
    database_url: str | None = None
    cors_origins: str = (
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://paper-broker.oppenheimer.studio,https://paper-broker.oppenheimer.studio"
    )
    mcp_allowed_hosts: str = (
        "127.0.0.1:*,localhost:*,[::1]:*,"
        "paper-broker-mcp.oppenheimer.studio,paper-broker-mcp.oppenheimer.studio:*"
    )
    mcp_allowed_origins: str = (
        "http://127.0.0.1:*,http://localhost:*,"
        "http://paper-broker-mcp.oppenheimer.studio,https://paper-broker-mcp.oppenheimer.studio"
    )
    web_dist: Path = Path("./web/dist")
