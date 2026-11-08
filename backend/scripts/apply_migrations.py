"""
KEEL - Schema Migration Runner (docker-compose.yml's `migrate` service
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

REPO_ROOT = Path(__file__).resolve().parent.parent
# Direct script invocation (the minimal migration container) needs no API dependencies.
sys.path.insert(0, str(REPO_ROOT))
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


def _sync_billing_setup_password(conn) -> None:
    """Provision explicit restricted credentials; never persist them in SQL history."""
    from psycopg2 import sql
    for role, variable in (("ceopro_billing_setup", "BILLING_SETUP_DB_PASSWORD"),
                           ("ceopro_billing_webhook", "BILLING_WEBHOOK_DB_PASSWORD"),
                           ("ceopro_credit_accounting", "CREDIT_ACCOUNTING_DB_PASSWORD"),
                           ("ceopro_image_worker", "IMAGE_WORKER_DB_PASSWORD")):
        password = os.getenv(variable)
        if not password:
            continue
        with conn.cursor() as cur:
            cur.execute("SELECT rolsuper,rolbypassrls,rolcreatedb,rolcreaterole,rolinherit,rolreplication "
                        "FROM pg_roles WHERE rolname=%s", (role,))
            if cur.fetchone() != (False, False, False, False, False, False):
                raise RuntimeError("Restricted billing identity missing or unexpectedly privileged; password not changed.")
            cur.execute(sql.SQL("ALTER ROLE {} WITH PASSWORD %s").format(sql.Identifier(role)), (password,))
        conn.commit()
        logger.info("Restricted billing credential synchronized: %s", role)


def _allow_owner_role_management(conn) -> None:
    """
    Managed Postgres (Neon, and similar hosts) gives the database owner
    CREATEROLE but never real SUPERUSER. From Postgres 16 a CREATEROLE role
    is no longer automatically a member of the roles it creates, so the
    migrations that hand SECURITY DEFINER functions to a restricted owner
    role (ALTER FUNCTION ... OWNER TO, later CREATE OR REPLACE of those
    functions) fail with "must be able to SET ROLE". createrole_self_grant
    restores the pre-16 membership for this session only. A superuser
    connection, or a server older than 16, needs and gets no change.
    """
    with conn.cursor() as cursor:
        cursor.execute("SELECT current_setting('is_superuser') = 'on', current_setting('server_version_num')::int")
        is_superuser, server_version = cursor.fetchone()
        if not is_superuser and server_version >= 160000:
            cursor.execute("SET createrole_self_grant = 'set, inherit'")
            logger.info("Non-superuser migration role on Postgres 16+: createrole_self_grant enabled for this session.")
    conn.commit()


# KEEL's restricted roles (ceopro_app, the billing roles, keel_notification_fn_owner, ...). The migration owner
# needs to act as them only while migrations run (ALTER FUNCTION ... OWNER TO, CREATE OR REPLACE of their
# functions); afterwards it must not stay a member of them (least privilege).
_RESTRICTED_ROLE_PATTERN = r"^(ceopro|keel)_"


def _non_superuser_16_plus(conn) -> bool:
    with conn.cursor() as cursor:
        cursor.execute("SELECT current_setting('is_superuser') = 'on', current_setting('server_version_num')::int")
        is_superuser, server_version = cursor.fetchone()
    return not is_superuser and server_version >= 160000


def _borrow_restricted_roles(conn) -> None:
    """For this run only, give the non-superuser migration owner SET/INHERIT on the restricted roles it
    administers (it created them, so it holds the ADMIN option). Roles created during the run get the same
    through createrole_self_grant. _return_restricted_roles takes all of it back at the end."""
    if not _non_superuser_16_plus(conn):
        return
    from psycopg2 import sql
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT r.rolname FROM pg_roles r WHERE r.rolname ~ %s AND r.rolname <> current_user "
            "AND pg_has_role(current_user, r.oid, 'USAGE WITH ADMIN OPTION') ORDER BY 1;",
            (_RESTRICTED_ROLE_PATTERN,),
        )
        roles = [row[0] for row in cursor.fetchall()]
        for role in roles:
            cursor.execute(sql.SQL("GRANT {} TO CURRENT_USER WITH INHERIT TRUE, SET TRUE").format(sql.Identifier(role)))
    conn.commit()
    if roles:
        logger.info("Migration owner acting for %d restricted role(s) during this run.", len(roles))


def _return_restricted_roles(conn) -> None:
    """Revoke every SET/INHERIT membership the migration owner granted itself in a restricted role, whether
    by _borrow_restricted_roles or createrole_self_grant. The creator's ADMIN option stays (it is what lets
    the runner set the restricted roles' passwords); it carries neither SET nor INHERIT."""
    if not _non_superuser_16_plus(conn):
        return
    from psycopg2 import sql
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT r.rolname FROM pg_auth_members a JOIN pg_roles r ON r.oid = a.roleid "
            "WHERE a.member = (SELECT oid FROM pg_roles WHERE rolname = current_user) "
            "AND a.grantor = (SELECT oid FROM pg_roles WHERE rolname = current_user) "
            "AND (a.set_option OR a.inherit_option) AND r.rolname ~ %s ORDER BY 1;",
            (_RESTRICTED_ROLE_PATTERN,),
        )
        roles = [row[0] for row in cursor.fetchall()]
        for role in roles:
            cursor.execute(sql.SQL("REVOKE {} FROM CURRENT_USER GRANTED BY CURRENT_USER").format(sql.Identifier(role)))
    conn.commit()
    if roles:
        logger.info("Migration owner released %d restricted role(s).", len(roles))


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
        from src.ai.billing.standard_plan_catalog import load_catalog
        load_catalog()  # Fail before any schema/data write for malformed source.
        _allow_owner_role_management(conn)
        _borrow_restricted_roles(conn)
        fresh_plan_catalog = not _table_exists(conn, "usage_plans")
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

        # Validate/install the JSON only at setup, never API startup or requests.
        # Partial-history migration tests may not have the catalog table yet.
        with conn.cursor() as cursor:
            cursor.execute("SELECT to_regclass('public.billing_standard_catalog_versions') IS NOT NULL")
            has_standard_catalog = cursor.fetchone()[0]
        if has_standard_catalog:
            from src.ai.billing.standard_plan_catalog import install_catalog
            install_catalog(conn, fresh=fresh_plan_catalog)

        # Setup authority only. Repeated setup creates no versions or owner edits.
        # Earlier-schema installation tests intentionally may not have this function.
        with conn.cursor() as cursor:
            cursor.execute("SELECT to_regprocedure('public.billing_catalog_reconcile()') IS NOT NULL")
            if cursor.fetchone()[0]:
                cursor.execute('SELECT public.billing_catalog_reconcile()')

        _sync_app_role_password(conn)
        _sync_billing_setup_password(conn)

        conn.commit()  # end any read-only transaction left open by the checks above, so a reused conn is idle on return
        logger.info(f"Migration run complete. Applied {len(applied_this_run)} new migration(s).")
        return applied_this_run
    finally:
        # Success or failure, the owner never keeps acting for the restricted roles.
        try:
            conn.rollback()
            _return_restricted_roles(conn)
        except Exception as err:  # noqa: BLE001 - reported; the original outcome stands
            logger.error("Could not release restricted roles after the migration run: %s", type(err).__name__)
        if owns_connection:
            conn.close()


if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        logger.critical(f"Migration run failed: {e}")
        sys.exit(1)
