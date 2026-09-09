# Arquitectura (etapa 1)

Hexágono chico: el dominio no importa DuckDB, Yahoo ni FastAPI. Tres casos de uso. Adaptadores al borde.

```
                    ┌──────────── HTTP / MCP ────────────┐
                    │  FastAPI  │  MCP streamable HTTP   │
                    └─────────────────┬──────────────────┘
                                      │
                    ┌─────────────────▼──────────────────┐
                    │ application                        │
                    │  DailyUpdate  Screener  MarketQuery│
                    └─────────────────┬──────────────────┘
                                      │ ports
           ┌──────────────┬───────────┼───────────┬──────────────┐
           ▼              ▼           ▼           ▼              ▼
      UniverseFeed   PriceFeed   MinuteFeed   BulkEodFeed    Warehouse      Calendar
      (Nasdaq)       (Yahoo     (Yahoo 1m    (Defeatbeta    (DuckDB+     (QQQ dates)
                      fallback)   ~2500/h)    parquet HF)    parquet)
```

## Qué es un cluster, no dos productos

- **Parquet** no es otra base: es el formato de las tablas de mercado.
- **DuckDB** es el motor de lectura/agregación y el writer del lago.
- **Supabase Postgres** (cuando Wrappers funcione): FDW **solo SELECT** sobre el mismo parquet en MinIO. Órdenes/cuentas (etapa 2) viven nativas en Postgres. El wrapper no escribe el lago ([docs](https://supabase.com/docs/guides/database/extensions/wrappers/duckdb)).

Etapa 1 no usa Postgres para el tape. `ingest_runs` vive en el lago (`meta/ingest_runs.parquet`) para que el catch-up funcione sin Supabase.

## Capas

| Capa | Path | Regla |
|---|---|---|
| domain | `src/paper_broker/domain` | Modelos, filtros, ATR/relvol. Cero I/O. |
| application | `src/paper_broker/application` | Orquesta puertos. Logging de progreso. |
| adapters | `src/paper_broker/adapters` | Yahoo, Nasdaq, DuckDB, HTTP, MCP. |
| composition | `src/paper_broker/main.py` | Cableado + config. |

Un solo proceso: API + MCP. Cron minutes `POST /v1/admin/daily?phase=minutes`; cron EOD `phase=eod`.

## Logging

`structlog` JSON (o consola en dev). En el daily cada paso lleva `as_of`, `run_id`, `ticker` si aplica, `ok`/`skip`/`error`. No silenciar 404: se cuenta y se sigue (orden por market cap: las grandes primero).

## Lo que esta etapa no tiene

Auth de usuarios, N cuentas paper, settle de órdenes, news, 10-Q masivo, FMP. El frontend arranca como screener (`web/`).
