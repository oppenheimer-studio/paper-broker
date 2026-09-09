from __future__ import annotations

from pathlib import Path

from paper_broker.config import Settings
from paper_broker.logging import configure_logging, get_logger

log = get_logger("migrate")

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "db" / "migrations"


def _optional_file(path: Path) -> bool:
    return path.name.startswith("002")


def ensure_minio_bucket(settings: Settings) -> None:
    if not (settings.minio_endpoint and settings.minio_access_key and settings.minio_secret_key):
        log.info("minio_skip", reason="no credentials")
        return
    from paper_broker.adapters.minio_sync import MinioSync

    client = MinioSync(
        settings.minio_endpoint,
        settings.minio_access_key,
        settings.minio_secret_key,
        settings.minio_bucket,
        secure=settings.minio_secure,
    )
    client.ensure_bucket()


def apply_postgres(settings: Settings) -> None:
    if not settings.database_url:
        log.info("postgres_skip", reason="DATABASE_URL empty")
        return
    import psycopg

    files = sorted(MIGRATIONS.glob("*.sql"))
    if not files:
        log.warning("no_migration_files", path=str(MIGRATIONS))
        return
    try:
        con = psycopg.connect(
            settings.database_url,
            autocommit=True,
            cursor_factory=psycopg.ClientCursor,
        )
    except psycopg.Error as exc:
        log.exception("postgres_connect_failed")
        _notify_lake(
            settings,
            level="warning",
            code="migrate.postgres_unavailable",
            title="Postgres unavailable; skipped SQL migrations",
            detail=str(exc),
        )
        return
    with con:
        applied: set[str] = set()
        try:
            rows = con.execute("SELECT version FROM paper_broker.schema_migrations").fetchall()
            applied = {r[0] for r in rows}
        except psycopg.Error:
            log.info("schema_migrations_missing", hint="will apply 001")
        for path in files:
            version = path.stem
            if version in applied:
                log.info("migration_skip", version=version)
                continue
            sql = path.read_text(encoding="utf-8")
            log.info("migration_apply", version=version)
            try:
                con.execute(sql)
                con.execute(
                    """
                    INSERT INTO paper_broker.schema_migrations(version)
                    VALUES (%s)
                    ON CONFLICT (version) DO NOTHING
                    """,
                    (version,),
                )
                log.info("migration_ok", version=version)
            except Exception as exc:
                if _optional_file(path):
                    log.exception("migration_optional_failed", version=version)
                    _notify_lake(
                        settings,
                        level="warning",
                        code="migrate.optional_failed",
                        title=f"Optional migration {version} skipped",
                        detail=str(exc),
                    )
                    continue
                log.exception("migration_failed", version=version)
                raise


def _notify_lake(settings: Settings, *, level: str, code: str, title: str, detail: str) -> None:
    try:
        from paper_broker.adapters.duckdb_warehouse import DuckDbWarehouse

        wh = DuckDbWarehouse(settings.lake_path)
        try:
            wh.append_event(level=level, source="migrate", code=code, title=title, detail=detail)
        finally:
            wh.close()
    except Exception:
        log.exception("event_emit_failed", code=code)


def run(settings: Settings | None = None) -> None:
    settings = settings or Settings()
    configure_logging(json=settings.log_json, level=settings.log_level)
    ensure_minio_bucket(settings)
    apply_postgres(settings)
    log.info("migrate_done")


def main() -> None:
    run()


if __name__ == "__main__":
    main()
