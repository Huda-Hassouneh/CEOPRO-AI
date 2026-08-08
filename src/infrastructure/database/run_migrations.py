"""
CEOPRO AI - Schema Migration Runner (PENDING_ACTIONS.md #22).

Nothing in the repo applies init_schema.sql or migrations/*.sql to a real
database automatically - every "landed but not deployable" finding this
track has made (pgvector, RLS, market-intelligence tables) traces back to
that gap. This is the tool that closes it; wiring it into docker-compose.yml
or CI is a separate deployment decision, not made here.

Applies init_schema.sql exactly once (it isn't idempotent - most CREATE
TABLE statements have no IF NOT EXISTS guard, so re-running it against an
already-initialized database would error), detected via the presence of the
`companies` table. Then applies every file in migrations/ in filename order
(which sorts chronologically, since every migration is named
YYYYMMDDHHMMSS_description.sql), tracking what's already applied in a
schema_migrations table so re-running this script is always a safe no-op
for anything already applied.

Usage: DATABASE_URL=postgresql://... python -m src.infrastructure.database.run_migrations
Must be run as a superuser/schema-owning role (e.g. ceopro_admin), never the
restricted ceopro_app role - migrations/20260808020000_add_app_role_and_force_rls.sql
itself requires superuser privileges to run (CREATE ROLE, GRANT).
"""

import logging
import os
import sys
from pathlib import Path

import psycopg2

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("CEOPRO_MIGRATION_RUNNER")

SCHEMA_DIR = Path(__file__).parent
INIT_SCHEMA_FILE = SCHEMA_DIR / "init_schema.sql"
MIGRATIONS_DIR = SCHEMA_DIR / "migrations"

# A table only init_schema.sql creates - its presence means the base schema
# already ran.
BASE_SCHEMA_MARKER_TABLE = "companies"


def _database_url() -> str:
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL environment variable is not set.")
    return db_url


def _table_exists(conn, table_name: str) -> bool:
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = %s);",
            (table_name,),
        )
        return cursor.fetchone()[0]


def _ensure_migrations_table(conn) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                filename VARCHAR(255) PRIMARY KEY,
                applied_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
    conn.commit()


def _already_applied(conn) -> set:
    with conn.cursor() as cursor:
        cursor.execute("SELECT filename FROM schema_migrations;")
        return {row[0] for row in cursor.fetchall()}


def _apply_sql_file(conn, path: Path) -> None:
    sql = path.read_text(encoding="utf-8")
    with conn.cursor() as cursor:
        cursor.execute(sql)


def run(conn=None) -> list:
    """Returns the list of migration filenames actually applied this run (empty if everything was already applied)."""
    owns_connection = conn is None
    conn = conn or psycopg2.connect(_database_url())
    applied_this_run = []

    try:
        if _table_exists(conn, BASE_SCHEMA_MARKER_TABLE):
            logger.info(f"Base schema already present (table '{BASE_SCHEMA_MARKER_TABLE}' exists) - skipping init_schema.sql.")
        else:
            logger.info("Applying init_schema.sql...")
            _apply_sql_file(conn, INIT_SCHEMA_FILE)
            conn.commit()
            logger.info("init_schema.sql applied.")

        _ensure_migrations_table(conn)
        already_applied = _already_applied(conn)

        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if path.name in already_applied:
                logger.info(f"Skipping already-applied migration: {path.name}")
                continue

            logger.info(f"Applying migration: {path.name}")
            try:
                _apply_sql_file(conn, path)
                with conn.cursor() as cursor:
                    cursor.execute("INSERT INTO schema_migrations (filename) VALUES (%s);", (path.name,))
                conn.commit()
                applied_this_run.append(path.name)
                logger.info(f"Applied: {path.name}")
            except Exception as err:
                conn.rollback()
                logger.error(f"Failed to apply {path.name}: {err}")
                raise

        conn.commit()  # end any read-only transaction left open by the checks above, so a reused conn is idle on return
        logger.info(f"Migration run complete. Applied {len(applied_this_run)} new migration(s).")
        return applied_this_run
    finally:
        if owns_connection:
            conn.close()


if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        logger.critical(f"Migration run failed: {e}")
        sys.exit(1)
