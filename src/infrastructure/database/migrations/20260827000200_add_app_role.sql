-- CEOPRO AI - Non-superuser application role.
-- Final_schema.sql already applies FORCE ROW LEVEL SECURITY everywhere, but
-- that alone still isn't sufficient: Postgres superusers unconditionally
-- bypass RLS regardless of FORCE (confirmed empirically earlier this track
-- against the real docker-compose.yml POSTGRES_USER=ceopro_admin, which the
-- official image makes a genuine superuser). Every application service must
-- connect as this role instead, not as the migration-running superuser.
--
-- Ordered to run after every table-creating migration (highest timestamp in
-- this migrations/ directory as of writing) so the GRANT ... ON ALL TABLES
-- sweep below actually covers every table, not just the ones that existed
-- when this file happened to run. The role's password is NOT set here (no
-- secret belongs in a committed .sql file) - scripts/apply_migrations.py
-- sets it via a separate parameterized ALTER ROLE call, reading
-- APP_DB_PASSWORD from the environment.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ceopro_app') THEN
        CREATE ROLE ceopro_app WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
    END IF;
END $$;

-- CONNECT is granted to PUBLIC by default on a fresh database (nothing in
-- this repo revokes it), so no explicit GRANT CONNECT is needed here.
GRANT USAGE ON SCHEMA public TO ceopro_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO ceopro_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO ceopro_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ceopro_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO ceopro_app;
