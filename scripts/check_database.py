"""
CEOPRO AI - read-only check of a database before pointing the AI service at
it (e.g. the hosted Render database and its AI-team user).

Reports, without changing anything (the whole session is read-only):
  - whether it connects, over SSL or not, as which user, server version;
  - that user's role attributes (superuser / BYPASSRLS would defeat RLS);
  - which migration system built the schema (Prisma `_prisma_migrations`,
    this repo's `schema_migrations`, or neither) and its latest entries;
  - every table Final_schema.sql defines, plus the objects the AI-only
    migrations add, and which of them are missing;
  - per table: SELECT/INSERT/UPDATE/DELETE privileges for this user, whether
    RLS is enabled/forced, and an estimated row count (from statistics, so
    RLS doesn't hide rows from the count).

The connection string is read from an environment variable and is never
printed - only its host and database name are.

Usage:
  APP_DATABASE_URL=... python scripts/check_database.py
  python scripts/check_database.py --env-var DATABASE_URL
Exit code: 0 connected and nothing required is missing, 1 something missing,
2 could not connect.
"""

import argparse
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import psycopg2

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "src" / "infrastructure" / "database"

# Objects added by migrations/ that the web backend's Prisma history did not
# carry (checked 2026-10-08). The AI service and market workers use each one.
AI_ONLY_COLUMNS = [
    ("companies", "city"), ("companies", "latitude"), ("companies", "longitude"),
    ("companies", "default_search_radius_km"), ("companies", "search_scope_level"),
    ("global_competitors", "city"), ("global_competitors", "latitude"), ("global_competitors", "longitude"),
    ("tenant_competitors", "competitor_scope"), ("tenant_competitors", "discovery_method"),
    ("tenant_competitors", "distance_km"),
    ("rag_documents_metadata", "content_hash"),
    ("market_observations", "creator_handle"), ("market_observations", "view_count"), ("market_observations", "content_date"),
    ("reviews", "parent_review_id"),
]
AI_ONLY_TABLES = ["scraping_cost_ledger"]
AI_ONLY_FUNCTIONS = ["list_tenants_with_active_connectors", "get_current_tenant"]
AI_ONLY_INDEXES = ["uq_rag_documents_tenant_bucket_path", "idx_reviews_parent", "idx_tenant_competitors_distance"]


def schema_tables() -> list:
    names = set()
    for path in [SCHEMA_DIR / "Final_schema.sql", *sorted((SCHEMA_DIR / "migrations").glob("*.sql"))]:
        text = path.read_text(encoding="utf-8")
        names.update(m.lower() for m in re.findall(r"CREATE TABLE(?: IF NOT EXISTS)?\s+(?:public\.)?\"?(\w+)", text, re.I))
    return sorted(names)


def one(cur, sql, args=()):
    cur.execute(sql, args)
    return cur.fetchone()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--env-var", default="APP_DATABASE_URL", help="environment variable holding the connection string")
    parser.add_argument("--expect-database", help="fail unless current_database() is this")
    parser.add_argument("--expect-user", help="fail unless current_user is this")
    parser.add_argument("--tenant-id", help="with --user-id: read every accessible table under this tenant context")
    parser.add_argument("--user-id", help="with --tenant-id: the tenant member the context is set for")
    args = parser.parse_args()
    url = os.getenv(args.env_var)
    if not url:
        print(f"{args.env_var} is not set.")
        return 2
    parsed = urlparse(url)
    print(f"Target: host={parsed.hostname} database={parsed.path.lstrip('/')} (credentials not shown)")
    try:
        conn = psycopg2.connect(url, connect_timeout=15, application_name="ceopro-ai-db-check")
    except psycopg2.Error as exc:
        # The message can echo the host but never the password.
        print(f"CONNECT FAILED: {type(exc).__name__}: {str(exc).strip().splitlines()[0]}")
        return 2

    conn.set_session(readonly=True, autocommit=False)
    missing, readable, unreadable = [], [], []
    with conn.cursor() as cur:
        version, user, db = one(cur, "SELECT current_setting('server_version'), current_user, current_database()")
        ssl = one(cur, "SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()")
        print(f"Connected: Postgres {version}, user={user}, database={db}, ssl={'yes' if ssl and ssl[0] else 'no'}")
        for label, expected, actual in (("database", args.expect_database, db), ("user", args.expect_user, user)):
            if expected and expected != actual:
                print(f"  MISMATCH: expected {label} {expected}, connected as {actual}")
                missing.append(f"expected {label}")
        superuser, bypassrls, createrole, createdb = one(
            cur, "SELECT rolsuper, rolbypassrls, rolcreaterole, rolcreatedb FROM pg_roles WHERE rolname = current_user")
        print(f"Role: superuser={superuser} bypassrls={bypassrls} createrole={createrole} createdb={createdb}")
        if superuser or bypassrls:
            print("  WARNING: this role ignores row-level security - tenant isolation would not apply.")
        cur.execute("SELECT b.rolname FROM pg_auth_members m JOIN pg_roles b ON b.oid = m.roleid "
                    "JOIN pg_roles u ON u.oid = m.member WHERE u.rolname = current_user ORDER BY 1")
        member_of = [r[0] for r in cur.fetchall()]
        print(f"Member of: {', '.join(member_of) or '(none)'}")

        prisma = one(cur, "SELECT to_regclass('public._prisma_migrations') IS NOT NULL")[0]
        ours = one(cur, "SELECT to_regclass('public.schema_migrations') IS NOT NULL")[0]
        print(f"Migration history: prisma={'yes' if prisma else 'no'} schema_migrations={'yes' if ours else 'no'}")
        for table, sql in (
            ("_prisma_migrations", "SELECT count(*), max(migration_name), "
                                   "count(*) FILTER (WHERE finished_at IS NULL OR rolled_back_at IS NOT NULL) FROM _prisma_migrations"),
            ("schema_migrations", "SELECT count(*), max(filename), 0 FROM schema_migrations"),
        ):
            if (table == "_prisma_migrations" and prisma) or (table == "schema_migrations" and ours):
                try:
                    count, latest, unfinished = one(cur, sql)
                    print(f"  {table}: {count} applied, latest {latest}, unfinished/rolled back {unfinished}")
                except psycopg2.Error as exc:
                    conn.rollback()
                    print(f"  {table}: not readable by {user} ({exc.pgcode})")

        print("\nTables (privileges for this user | RLS | ~rows):")
        for name in schema_tables() + [t for t in AI_ONLY_TABLES if t not in schema_tables()]:
            row = one(cur, """
                SELECT c.relrowsecurity, c.relforcerowsecurity, GREATEST(c.reltuples, 0)::bigint,
                       has_table_privilege(c.oid, 'SELECT'), has_table_privilege(c.oid, 'INSERT'),
                       has_table_privilege(c.oid, 'UPDATE'), has_table_privilege(c.oid, 'DELETE'),
                       pg_get_userbyid(c.relowner) = current_user
                FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public' AND c.relname = %s AND c.relkind IN ('r', 'p')""", (name,))
            if row is None:
                missing.append(f"table {name}")
                print(f"  MISSING  {name}")
                continue
            rls, forced, rows, s, i, u, d, owner = row
            privs = "".join(flag if ok else "-" for flag, ok in zip("SIUD", (s, i, u, d)))
            note = " (owned by this user: RLS skipped unless forced)" if owner and rls and not forced else ""
            print(f"  ok       {name:<38} {privs} | rls={'forced' if forced else 'on' if rls else 'off'} | ~{rows}{note}")
            if s:
                readable.append(name)
            else:
                unreadable.append(name)
        if unreadable:
            print(f"\n{len(unreadable)} table(s) this user cannot read - any code path that reads one fails with "
                  f"'permission denied' (see DATABASE_SETUP.md for which features need which): {', '.join(unreadable)}")

        cur.execute("""
            SELECT c.relname, has_sequence_privilege(c.oid, 'USAGE')
            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relkind = 'S' ORDER BY 1""")
        sequences = cur.fetchall()
        if sequences:
            print("\nSequences (INSERT into a serial column needs USAGE):")
            for name, usage in sequences:
                print(f"  {'ok     ' if usage else 'no use '}  {name}")

        print("\nAI-only migration objects:")
        for table, column in AI_ONLY_COLUMNS:
            present = one(cur, "SELECT EXISTS (SELECT 1 FROM pg_attribute WHERE attrelid = to_regclass('public.' || %s) "
                               "AND attname = %s AND NOT attisdropped)", (table, column))[0]
            print(f"  {'ok     ' if present else 'MISSING'}  column {table}.{column}")
            if not present:
                missing.append(f"column {table}.{column}")
        for fn in AI_ONLY_FUNCTIONS:
            present = one(cur, "SELECT EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
                               "WHERE n.nspname = 'public' AND p.proname = %s)", (fn,))[0]
            print(f"  {'ok     ' if present else 'MISSING'}  function {fn}()")
            if not present:
                missing.append(f"function {fn}")
        for idx in AI_ONLY_INDEXES:
            present = one(cur, "SELECT to_regclass('public.' || %s) IS NOT NULL", (idx,))[0]
            print(f"  {'ok     ' if present else 'missing'}  index {idx}")  # an index missing is slower, not broken

        if args.tenant_id and args.user_id:
            conn.rollback()
            print(f"\nRow counts under tenant context (RLS applied, read-only):")
            for name in readable:
                cur.execute("SELECT set_config('app.current_tenant_id', %s, true), set_config('app.current_user_id', %s, true)",
                            (args.tenant_id, args.user_id))
                try:
                    count = one(cur, f'SELECT count(*) FROM public."{name}"')[0]
                    print(f"  ok       {name:<38} {count}")
                except psycopg2.Error as exc:
                    print(f"  ERROR    {name:<38} {exc.pgcode}: {str(exc).strip().splitlines()[0]}")
                    missing.append(f"read {name} under tenant context")
                conn.rollback()

    conn.rollback()
    conn.close()
    print(f"\n{len(missing)} required object(s) missing." if missing else "\nEverything the AI service needs is present.")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
