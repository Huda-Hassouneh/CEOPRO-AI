"""
CEOPRO AI - Schema Migration Runner (docker-compose.yml's `migrate` service
already referenced this exact path - python scripts/apply_migrations.py -
before this file existed, so the service failed on every run).

Applies Final_schema.sql exactly once (detected via the `companies` marker
table, since the file isn't fully idempotent itself - CREATE POLICY and
CREATE TRIGGER don't support IF NOT EXISTS in this Postgres version, even
though every CREATE TABLE/INDEX in it does), then applies every file in
migrations/ in filename order, tracked in a schema_migrations table so
re-running this script is always a safe no-op for anything already applied.

Adapted from src/infrastructure/database/run_migrations.py (built against
the older init_schema.sql, before the schema fork was resolved in favor of
Final_schema.sql) - same design, repointed, and now the actual file
docker-compose.yml's `migrate` service expects.

Usage: DATABASE_URL=postgresql://... [APP_DB_PASSWORD=...] python scripts/apply_migrations.py
Must be run as a superuser/schema-owning role (e.g. ceopro_admin), never the
restricted ceopro_app role - migrations/20260827000200_add_app_role.sql
itself requires superuser privileges (CREATE ROLE, GRANT).
"""

import logging
import os
import sys
from pathlib import Path

import psycopg2

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("CEOPRO_MIGRATION_RUNNER")

REPO_ROOT = Path(__file__).parent.parent
SCHEMA_DIR = REPO_ROOT / "src" / "infrastructure" / "database"
FINAL_SCHEMA_FILE = SCHEMA_DIR / "Final_schema.sql"
MIGRATIONS_DIR = SCHEMA_DIR / "migrations"

# A table only Final_schema.sql creates - its presence means the base schema
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


def _sync_app_role_password(conn) -> None:
    """
    Sets/updates ceopro_app's password from APP_DB_PASSWORD via a
    parameterized query - never embedded in a .sql migration file, since
    those get committed to git. No-op (with a warning) if the role doesn't
    exist yet (its creation migration hasn't run) or the env var isn't set
    (e.g. local dev without the app role wired up yet).
    """
    password = os.getenv("APP_DB_PASSWORD")
    if not password:
        logger.warning("APP_DB_PASSWORD not set - skipping ceopro_app password sync.")
        return
    if not _role_exists(conn, "ceopro_app"):
        logger.warning("ceopro_app role does not exist yet - skipping password sync.")
        return
    with conn.cursor() as cursor:
        cursor.execute("ALTER ROLE ceopro_app WITH PASSWORD %s;", (password,))
    conn.commit()
    logger.info("ceopro_app password synced from APP_DB_PASSWORD.")


def _role_exists(conn, role_name: str) -> bool:
    with conn.cursor() as cursor:
        cursor.execute("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = %s);", (role_name,))
        return cursor.fetchone()[0]


def run(conn=None) -> list:
    """Returns the list of migration filenames actually applied this run (empty if everything was already applied)."""
    owns_connection = conn is None
    conn = conn or psycopg2.connect(_database_url())
    applied_this_run = []

    try:
        if _table_exists(conn, BASE_SCHEMA_MARKER_TABLE):
            logger.info(f"Base schema already present (table '{BASE_SCHEMA_MARKER_TABLE}' exists) - skipping Final_schema.sql.")
        else:
            logger.info("Applying Final_schema.sql...")
            _apply_sql_file(conn, FINAL_SCHEMA_FILE)
            conn.commit()
            logger.info("Final_schema.sql applied.")

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

        _sync_app_role_password(conn)

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
