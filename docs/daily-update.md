# Daily update

Un job. Reloj = sesiones en las que **QQQ** tiene barra (`interval=1d`). No se usa `GSPC`/`^GSPC` como gate.

Corrida: cron nocturno o `POST /v1/admin/daily` (y MCP `run_daily_update`).

## Catch-up

Sea `last_ok` el máximo `as_of` con `status=success` en `ingest_runs`.
Sea `expected` el último día de sesión de QQQ ≤ ahora ET.

Se procesan **todas** las sesiones `(last_ok, expected]` en orden. Si ayer falló y hoy corrés el endpoint, corre ayer y hoy.

Si `last_ok is null` (primera vez): desde `expected - seed_sessions` (default 14, para el lookback del screener) hasta `expected`. Yahoo 1m no backfillea más de ~7d: el relvol 14d queda parcial hasta acumular.

## Idempotencia

Misma sesión, segunda corrida:

1. Universo: upsert por ticker. No se dropea la tabla a ciegas.
2. EOD: tickers que **ya tienen** fila `daily_data` ese `date` se skippean. Solo se pide lo que falta.
3. `minute_open`: igual, por `(security_id, date, window_minutes)`.
4. Derived: se **recalcula entero** el `date=` (barato, local) y se pisa la partición. No toca otros días.
5. `ingest_runs`: un row por intento. Success de hoy no borra el success de ayer. Re-run success: se inserta otro intento `success` o se actualiza el de hoy; el estado observable es `max(as_of) where success`.

Nunca `DELETE` del lago salvo reemplazar **el archivo de esa sesión** (`daily_data/YYYY-MM-DD.parquet`, etc.).

## Orden por market cap

Dentro de cada sesión, los fetches externos se encolan **market cap desc** (último mcap conocido; si no hay, `dollar_volume` del último EOD; si no, el ticker se va al final). Si Yahoo corta o el proceso muere, AAPL/MSFT ya están.

## Pasos por sesión (log por paso)

1. `calendar` — confirmar que `session` está en QQQ.
2. `universe` — Nasdaq listed + otherlisted, filtro US stock.
3. `eod` — Yahoo 1d, faltantes primero, orden mcap.
4. `minute_open` — Yahoo 1m, primeros 5 min RTH, mismo orden.
5. `derived` — ATR, avg vol, relvol at, price.
6. `index` — commit `ingest_runs` success.

Macro FRED (`daily_market`) queda cableado como paso opcional; el screener de esta etapa no lo necesita.

## Relvol 5m

Hace falta 1m. No hay L1. “Rel vol at” = volumen de la ventana de apertura / media de esa misma ventana en N sesiones. Default ventana 5 min, N=14.
