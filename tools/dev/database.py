"""Local database commands; the only migration authority is scripts.apply_migrations."""
import contextlib
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlsplit, urlunsplit
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(Path(__file__).parent))
from dev import config, environment, DevError, STATE


def connect(c, *, app=False, database=None):
    import psycopg2
    env = environment(c, admin=not app)
    dsn = env["DATABASE_URL"]
    if database:
        dsn = urlunsplit(urlsplit(dsn)._replace(path="/" + database))
    return psycopg2.connect(dsn, connect_timeout=5)


def check(c):
    from scripts.apply_migrations import MIGRATIONS_DIR
    expected = {p.name for p in MIGRATIONS_DIR.glob("*.sql")}
    with contextlib.closing(connect(c)) as conn, conn.cursor() as cur:
        cur.execute("SELECT current_database()")
        assert cur.fetchone()[0] == "keel_dev_" + c["id"], "Database identity mismatch"
        cur.execute("SELECT extname FROM pg_extension WHERE extname='vector'")
        assert cur.fetchone(), "pgvector extension is missing"
        cur.execute("SELECT filename FROM schema_migrations")
        present = {r[0] for r in cur.fetchall()}
        missing = expected - present
        if missing:
            raise DevError(f"{len(missing)} migrations missing. Run migrate; do not edit migration history.")
        cur.execute("SELECT rolsuper,rolbypassrls,rolcreatedb,rolcreaterole FROM pg_roles WHERE rolname='ceopro_app'")
        assert cur.fetchone() == (False, False, False, False), "Restricted application role is unsafe"
        cur.execute("""SELECT relname FROM pg_class WHERE relnamespace='public'::regnamespace
                       AND relkind='r' AND relrowsecurity AND NOT relforcerowsecurity""")
        unsafe = [r[0] for r in cur.fetchall()]
        # Existing owner-run trigger/claim functions intentionally retain owner bypass.
        # See 20261028000100_entitlement_version_tracking.sql (explicit NO FORCE),
        # and 20261030000000_add_image_generation_jobs.sql (SECURITY DEFINER claims).
        original_nonforce = {"entitlement_version_state", "entitlement_catalog_version", "image_generation_jobs"}
        assert set(unsafe) == original_nonforce, "RLS/FORCE drift from declared schema: " + ", ".join(unsafe)
        cur.execute("SELECT tablename FROM pg_policies WHERE schemaname='public' AND tablename=ANY(%s)", (list(original_nonforce),))
        assert {r[0] for r in cur.fetchall()} == original_nonforce, "Original non-FORCE tables lost policies"
        cur.execute("SELECT relname FROM pg_class WHERE relnamespace='public'::regnamespace AND pg_get_userbyid(relowner)='ceopro_app' AND relname=ANY(%s)", (list(original_nonforce),))
        assert not cur.fetchall(), "Runtime role must not own owner-bypass tables"
        cur.execute("SELECT count(*) FROM pg_class WHERE relnamespace='public'::regnamespace AND relrowsecurity AND relforcerowsecurity")
        count = cur.fetchone()[0]
        assert count > 0, "No FORCE RLS tables"
    with contextlib.closing(connect(c, app=True)) as conn, conn.cursor() as cur:
        cur.execute("SELECT current_user")
        assert cur.fetchone() == ("ceopro_app",)
    print(f"OK database identity, pgvector, {len(expected)} migrations, restricted password login, {count} FORCE RLS tables")


def test(c):
    """New test DB in this checkout's owned cluster; never run tests on developer data."""
    from psycopg2 import sql
    from scripts import apply_migrations
    name = "keel_billing_test_dev_" + uuid.uuid4().hex[:12]
    ledger = STATE / "test-databases.json"
    prior = json.loads(ledger.read_text()) if ledger.exists() else []
    with contextlib.closing(connect(c)) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    prior.append({"name": name, "purpose": "disposable migration/RLS verification"})
    ledger.write_text(json.dumps(prior, indent=2) + "\n", encoding="utf-8")
    with contextlib.closing(connect(c, database=name)) as conn:
        first = apply_migrations.run(conn)
        assert len(first) == len(list(apply_migrations.MIGRATIONS_DIR.glob("*.sql")))
        assert apply_migrations.run(conn) == [], "Repeat migration changed schema"
    env = environment(c, admin=True)
    env["AI_TEST_DATABASE_URL"] = urlunsplit(urlsplit(env["DATABASE_URL"])._replace(path="/" + name))
    result = subprocess.run([sys.executable, "-m", "pytest", "-q",
                             "src/ai/tests/test_rls_integration_db.py",
                             "--junitxml=" + str(STATE / "rls-tests.xml")],
                            cwd=ROOT / "backend", env=env)
    if result.returncode:
        raise DevError("Native RLS tests failed; disposable test database retained. Inspect .dev/rls-tests.xml.")
    print("Fresh/repeat migrations and existing native RLS tests passed. Test database retained; names in .dev/test-databases.json.")


def main():
    c = config()
    action = sys.argv[1]
    if action == "seed":
        from fixtures import generate
        target, created = generate(ROOT, STATE / "fixtures" / "quickstart")
        print(f"Synthetic import file {'created' if created else 'preserved'}: {target}")
        print("No database records or paid rights created. Sign up, verify OTP in Mailpit, then use import preview/review.")
    elif action == "migrate":
        from scripts.apply_migrations import run
        applied = run()
        print(f"OK {len(applied)} migrations applied (existing history retained).")
    elif action == "status":
        from scripts.apply_migrations import MIGRATIONS_DIR
        expected = {p.name for p in MIGRATIONS_DIR.glob("*.sql")}
        with contextlib.closing(connect(c)) as conn, conn.cursor() as cur:
            cur.execute("SELECT to_regclass('public.schema_migrations')")
            if cur.fetchone()[0] is None:
                present = set()
            else:
                cur.execute("SELECT filename FROM schema_migrations")
                present = {r[0] for r in cur.fetchall()}
        print(f"Applied {len(present & expected)}/{len(expected)}; pending {len(expected-present)}")
        for filename in sorted(expected - present):
            print("PENDING " + filename)
    elif action == "check":
        check(c)
    elif action == "test":
        test(c)


if __name__ == "__main__":
    try:
        main()
    except (DevError, AssertionError) as exc:
        print(f"Database verification failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
    except Exception as exc:
        # Provider/DB exceptions can carry DSNs; report class only.
        print(f"Database command failed ({type(exc).__name__}). Check Docker/status and .dev configuration; no credentials printed.", file=sys.stderr)
        raise SystemExit(1)
