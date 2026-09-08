# Screener

Filtros sobre el snapshot `derived_daily_data` (y recálculo si el lookback no es el del snapshot).

Cada filtro: `field`, `op`, `value`, y si aplica `lookback` (sesiones) o `window_minutes`.

Campos etapa 1:

| field | Default lookback | Fuente |
|---|---|---|
| `price` | — | close |
| `avg_volume` | 14 | SMA volume EOD |
| `atr` | 14 | Wilder ATR diario |
| `rel_vol_at` | 14, window 5m | first N min vol / media N sesiones |
| `market` | — | `US` |
| `dollar_volume` | — | close × volume |
| `market_cap` | — | si hay shares |

Ops: `gt`, `gte`, `lt`, `lte`, `eq`.

Lookbacks como TradingView: `{ "field": "avg_volume", "op": "gt", "value": 1000000, "lookback": 20 }` recalcula SMA-20 ese día.

## Caso de uso (preset `open_relvol`)

```json
{
  "preset": "open_relvol",
  "filters": [
    { "field": "rel_vol_at", "op": "gt", "value": 1.0, "lookback": 14, "window_minutes": 5 },
    { "field": "price", "op": "gt", "value": 5 },
    { "field": "avg_volume", "op": "gt", "value": 1000000, "lookback": 14 },
    { "field": "atr", "op": "gt", "value": 0.5, "lookback": 14 },
    { "field": "market", "op": "eq", "value": "US" }
  ]
}
```

Hasta que haya 14 sesiones de `minute_open`, `rel_vol_at` usa las sesiones disponibles (`rel_vol_at_sessions` en la fila). Con 1m Yahoo ~7d, los primeros días el denominador es corto; no se inventan barras.
