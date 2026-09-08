# Frontend (screener)

App Vite + React en `web/`. En producción Coolify la sirve **el mismo** proceso HTTP (`/`), así el browser pega `/v1` same-origin.

```bash
# API + UI local
python -m paper_broker          # sirve web/dist si corriste npm run build
cd web && npm run dev           # :5173, proxea /v1 a paper-broker.oppenheimer.studio
```

Abrir `http://127.0.0.1:5173` (dev) o el dominio Coolify (prod). `?demo=1` muestra filas de ejemplo.

Campana **System notifications**: eventos del daily (fallbacks Nasdaq, sesiones, migrate).

## Qué cubre

- Scans built-in: Open RelVol, Liquid US, High RelVol, Wide range
- Scans guardados en el browser (`localStorage`)
- Filtros con lookback (sesiones) y window (minutos del open)
- Columnas on/off, sort, búsqueda, export CSV
- Panel del ticker + sparkline EOD (`GET /v1/bars/{ticker}`)
- Reloj `as_of` / último daily ok

Campos filtrables = los del backend (`price`, `avg_volume`, `atr`, `rel_vol_at`, `market`, `dollar_volume`, `market_cap`). ATR % se calcula en el cliente.
