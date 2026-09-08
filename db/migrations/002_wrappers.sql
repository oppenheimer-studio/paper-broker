-- Optional: DuckDB Wrappers onto the 2TB MinIO. Skip if the image has no wrappers.

CREATE EXTENSION IF NOT EXISTS wrappers WITH SCHEMA extensions;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_foreign_data_wrapper WHERE fdwname = 'duckdb_wrapper') THEN
        CREATE FOREIGN DATA WRAPPER duckdb_wrapper
            HANDLER duckdb_fdw_handler
            VALIDATOR duckdb_fdw_validator;
    END IF;
END
$$;

CREATE SCHEMA IF NOT EXISTS market;
