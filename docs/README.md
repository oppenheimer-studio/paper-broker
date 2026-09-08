# Paper broker — etapa 1 (backend)

Producto nuevo. No es un refactor de `packages/broker` ni de `data/market.db`.

Esta etapa: warehouse, API de consulta, MCP, job diario catch-up/idempotente, y screener. **Sin frontend y sin paper trading / multicuentas.**

| Doc | Qué cubre |
|---|---|
| [architecture.md](architecture.md) | Hexágono, servicios, qué va en Postgres vs parquet |
| [warehouse.md](warehouse.md) | Tablas, granos, bruto vs derived |
| [daily-update.md](daily-update.md) | Reloj, catch-up, idempotencia, orden por market cap |
| [api.md](api.md) | HTTP + MCP |
| [screener.md](screener.md) | Filtros configurables y el caso relvol 5m |
| [ops.md](ops.md) | Coolify, cron, MinIO, primer deploy |

Host: Coolify. Lago: parquet (disco local y/o MinIO). Lectura analítica: DuckDB. Supabase Wrappers entra cuando el FDW contra MinIO esté probado; hasta entonces la API consulta DuckDB directo.

Deploy: [ops.md](ops.md).
