# Daily update

Un job. Reloj = sesiones en las que **QQQ** tiene barra (`interval=1d`). No se usa `GSPC`/`^GSPC` como gate.

Corrida: dos cron, o `POST /v1/admin/daily?phase=minutes|eod|all` (y MCP `run_daily_update`).

- **02:00 America/Asuncion** — `phase=minutes`: Yahoo 1m (first 5m RTH), ~2500 requests/hora. No marca `success` en el reloj.
- **06:00 America/Asuncion** — `phase=eod`: EOD + splits/divs desde Defeatbeta (Hugging Face). Si el parquet del día anterior no está, espera 30 min y reintenta, 6 veces. Si a las 09:00 Asuncion sigue vacío, corta y emite `daily.eod_not_ready` (no tumba Yahoo el universo). Huecos de ticker → Yahoo. Después recalcula derived y marca `success`.

## Catch-up

Sea `last_ok` el máximo `as_of` con `status=success` en `ingest_runs`.
Sea `expected` la última sesión de QQQ **estrictamente anterior** a la fecha de hoy en America/New_York. A las 02:00 en Paraguay ya cerró el cash session de ayer US; el EOD espera a que Defeatbeta publique ese día (suele ser ~05:00 UTC).

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
3. `eod` — Defeatbeta `stock_prices` + splits/divs (bulk). Tickers faltantes: Yahoo 1d. No corre si Defeatbeta no tiene el `as_of` (reintento 6×30 min, corte 09:00 Asuncion).
4. `minute_open` — Yahoo 1m, primeros 5 min RTH, mismo orden, **tope ~2500 GET/hora** (query1 → query2, retry de vacíos/fallos). Cron aparte a las 02:00.
5. `derived` — ATR, avg vol, relvol at, price. Solo en `phase=eod`/`all`. Sin EOD de QQQ la sesión queda `error`.
6. `index` — commit `ingest_runs` success.

Macro FRED (`daily_market`) queda cableado como paso opcional; el screener de esta etapa no lo necesita.

## Relvol 5m

Hace falta 1m. No hay L1. “Rel vol at” = volumen de la ventana de apertura / media de esa misma ventana en N sesiones. Default ventana 5 min, N=14.
