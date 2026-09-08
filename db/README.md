# Postgres (Supabase)

SQL en `migrations/`, aplicado **al arrancar** el contenedor paper-broker (`python -m paper_broker.migrate`). Idempotente: tabla `paper_broker.schema_migrations`.

| Archivo | Obligatorio | Qué |
|---|---|---|
| `001_schema_migrations.sql` | sí | schema + tracking |
| `002_wrappers.sql` | no | `wrappers` + schema `market` para FDW al MinIO de 2 TB |

Si `DATABASE_URL` no está, se salta Postgres. Si `002` falla (extensión ausente), se loguea y el API igual arranca.

El tape **no** vive en Postgres: parquet en MinIO / `LAKE_PATH`. Postgres acá es catálogo + Wrappers +, después, cuentas paper.
