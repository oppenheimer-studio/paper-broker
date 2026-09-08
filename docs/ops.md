# Ops (Coolify)

Imagen: `paper-broker/Dockerfile`. Compose de referencia: `docker-compose.yml`.

Variables mínimas: `ADMIN_KEY`, `LAKE_PATH=/data/lake`. Primera vez: `INGEST_MAX_TICKERS=50` (mcap/dollar volume). Luego 0 = universo US.

MinIO (opcional): `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, `MINIO_BUCKET`. El job sube el lago al terminar cada corrida exitosa. Wrappers de Supabase se enchufan a ese bucket después; la API etapa 1 lee DuckDB local.

Cron Coolify (post-cierre ET, p.ej. 21:30 ART):

```
curl -sS -X POST "$PAPER_BROKER_URL/v1/admin/daily" \
  -H "Authorization: Bearer $ADMIN_KEY"
```

Sin `wait=true`: 202 y corre en background. Estado: `GET /v1/admin/daily`.

Catch-up: si ayer falló, un POST hoy procesa ayer y hoy. El mismo día, segunda corrida solo completa tickers/particiones que falten.

Preset de prueba:

```
curl -sS -X POST "$PAPER_BROKER_URL/v1/screener" \
  -H "Content-Type: application/json" \
  -d '{"preset":"open_relvol"}'
```
