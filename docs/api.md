# API y MCP

Mismos casos de uso. HTTP para scripts/Coolify; MCP para agentes.

Auth admin: header `Authorization: Bearer $ADMIN_KEY` en `POST /v1/admin/daily` y tool `run_daily_update`. Lecturas de mercado sin key en etapa 1 (red interna).

## HTTP

| Método | Path | Qué |
|---|---|---|
| GET | `/health` | proceso vivo |
| GET | `/v1/clock` | `as_of`, `last_success`, `expected`, `pending_sessions` |
| POST | `/v1/admin/daily` | catch-up desde último success |
| POST | `/v1/screener` | filtros (lookbacks editables) |
| GET | `/v1/securities` | búsqueda `q`, `limit` |
| GET | `/v1/bars/{ticker}` | EOD `from`, `to` |
| POST | `/v1/query` | agregaciones sobre tablas whitelist |

### `POST /v1/query`

Estilo PostgREST acotado (sin SQL libre):

```json
{
  "table": "daily_data",
  "select": ["ticker", { "agg": "avg", "field": "volume", "as": "avg_vol" }],
  "where": [{ "field": "date", "op": "gte", "value": "2026-01-01" }],
  "group_by": ["ticker"],
  "order_by": [{ "field": "avg_vol", "dir": "desc" }],
  "limit": 50
}
```

Tablas: `securities`, `daily_data`, `minute_open`, `derived_daily_data`, `daily_market`, `ingest_runs`.
Ops: `eq`, `neq`, `gt`, `gte`, `lt`, `lte`, `in`. Aggs: `avg`, `sum`, `min`, `max`, `count`.

### `POST /v1/screener`

Ver [screener.md](screener.md). Default as_of = clock.

## MCP

Tools: `get_clock`, `run_screener`, `get_bars`, `search_securities`, `query_market`, `run_daily_update`.

Endpoint: `http://<host>:8081/mcp`.
