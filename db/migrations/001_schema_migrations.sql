CREATE SCHEMA IF NOT EXISTS paper_broker;

CREATE TABLE IF NOT EXISTS paper_broker.schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
