# Deploy (Coolify + GitHub)

Push a **main** dispara el deploy. El trabajo diario se hace en `dev`; merge a `main` = producción.

```
git push origin dev          # trabajo
# PR o merge dev → main
git push origin main         # Coolify rebuild
```

Al arrancar el contenedor: `migrate` (bucket MinIO + SQL idempotente) y después la API.

## 1. Coolify: app desde GitHub (una vez)

1. GitHub App de Coolify (Keys & Tokens / Sources) con acceso a `oppenheimer-studio/paper-broker`.
2. Proyecto → **New Resource → GitHub** → ese repo.
3. Branch: **`main`**. Build pack: **Dockerfile**. Base: `/` (el Dockerfile está en la raíz de v2/repo).
4. **Auto Deploy** ON.
5. Red del mismo proyecto que MinIO y Supabase (para hostnames internos).
6. Persistent storage: bind del 2 TB, p.ej. `/mnt/2tb/paper-broker/lake` → `/data/lake` (no el volume default del SSD).
7. Env:

```
ADMIN_KEY=...
LAKE_PATH=/data/lake
LOG_JSON=true
INGEST_MAX_TICKERS=50
INGEST_CONCURRENCY=6

MINIO_ENDPOINT=http://<hostname-interno-minio>:9000
MINIO_ACCESS_KEY=...
MINIO_SECRET_KEY=...
MINIO_BUCKET=paper-broker
MINIO_SECURE=false

# Postgres de *tu* Supabase Coolify (usuario postgres, host interno supabase-db)
DATABASE_URL=postgresql://postgres:<PASSWORD>@<hostname-interno-supabase-db>:5432/postgres
```

8. Dominio / proxy a puerto **8080**. MCP es **8081** (exponer si los agentes están fuera).
9. Cron Coolify, post-cierre ET:

```
curl -sS -X POST "https://<tu-dominio>/v1/admin/daily" \
  -H "Authorization: Bearer $ADMIN_KEY"
```

MinIO y Supabase **no** se redeployan en cada push (son stateful). Solo la app. Esquemas nuevos = archivos en `db/migrations/` → van en el mismo deploy.

## 2. GitHub Actions (opcional)

Si no usás GitHub App de Coolify: webhook en Configuration → Webhooks. Secrets del repo:

- `COOLIFY_WEBHOOK`
- `COOLIFY_TOKEN`

El workflow `.github/workflows/deploy.yml` corre en push a `main` y pega el webhook.

## 3. Qué corre en cada deploy

1. Build de `Dockerfile`.
2. Start: `python -m paper_broker.migrate`
   - Crea el bucket MinIO si no existe.
   - Aplica `db/migrations/*.sql` no aplicados (`001` obligatorio, `002` wrappers opcional).
3. `python -m paper_broker` (API + MCP).

Si Wrappers no está en la imagen de Postgres, `002` se loguea y no tumba el contenedor.

## 4. Primera vez

`INGEST_MAX_TICKERS=50`. `POST /v1/admin/daily?wait=true` o esperar el cron. Luego `POST /v1/screener` `{"preset":"open_relvol"}`.
