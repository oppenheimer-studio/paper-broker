# Warehouse

Contrato de tablas (mismos granos que el diseño original). Join: `security_id`. Nunca ticker como PK.

Layout en disco (hive):

```
$LAKE_PATH/
  securities.parquet
  daily_data/YYYY-MM-DD.parquet
  minute_open/YYYY-MM-DD.parquet
  corporate_actions/YYYY-MM-DD.parquet
  daily_market/YYYY-MM-DD.parquet
  derived_daily_data/YYYY-MM-DD.parquet
  meta/ingest_runs.parquet
```

Un archivo por sesión. Reescribir ese archivo es el upsert del día: no se duplican filas, no se tocan otras fechas.

## Relojes

| Reloj | Tabla | Una fila es |
|---|---|---|
| Identidad | `securities` | esa empresa |
| Sesión × ticker | `daily_data` | OHLCV de esa sesión |
| Apertura × ticker | `minute_open` | volumen (y ohlc) de los primeros N minutos RTH |
| Sesión × ticker | `corporate_actions` | split o dividendo Yahoo de esa fecha |
| Sesión × mercado | `daily_market` | vix, us10y, oil, gold, … |
| Derived sesión | `derived_daily_data` | ATR, avg vol, relvol at, mcap, … |
| Meta | `ingest_runs` | un intento de daily para un `as_of` |

`minute_open` es bruto (sale de 1m Yahoo). No es el close oficial: el close vive en `daily_data`.

Yahoo 1m solo entrega ~7 días. El relvol 14d se va llenando noche a noche; si hay menos de 14 sesiones se usa las que hay (`rel_vol_at` y `rel_vol_at_sessions`).

## `securities`

`security_id`, `ticker`, `name`, `exchange`, `asset_type`, `listing_status`, `market` (`US`), `sector`, `industry`.

Universo etapa 1: common stock / ADR US. Fuera: warrant, unit, right, test issue, ETF como tradable. `QQQ` se guarda como benchmark (`asset_type=etf`, `listing_status=benchmark`) para el calendario.

## `daily_data`

`security_id`, `date`, `open`, `high`, `low`, `close`, `adj_close`, `volume`, `source`.

`adj_close`: el que trae Yahoo. No se pisa con `close`.

## `minute_open`

`security_id`, `date`, `window_minutes` (default 5), `open`, `high`, `low`, `close`, `volume`, `source`.

`volume` = suma de las velas 1m en `[09:30, 09:30+window)` America/New_York.

## `corporate_actions`

`security_id`, `date`, `action` (`split`|`dividend`), `value` (monto o ratio), `numerator`, `denominator`, `source`. Sale del chart Yahoo 1d (`events=div|split`), no de un request extra.

## `derived_daily_data`

Solo cuentas locales (nada de API):

- `price` = `daily_data.close`
- `avg_volume_n` con `n` configurable en el screener; el snapshot guarda `avg_volume_14` por el caso default
- `atr_n` (Wilder); snapshot `atr_14`
- `first5m_volume` (copia del bruto para no join-ear en el screener)
- `rel_vol_at_5m_14` = first5m_today / avg(first5m, 14 sesiones)
- `dollar_volume`, `market_cap` si hay shares (Yahoo stats; si no, null)
- `avg_volume_lookback`, `atr_lookback`, `rel_vol_at_sessions` usados al materializar

El screener puede **recalcular** ATR/avg vol/relvol con otro lookback sobre el bruto; el snapshot es el default 14.

## Invariante

Fuente externa → bruto. Derived no llama Yahoo. FMP no entra.
