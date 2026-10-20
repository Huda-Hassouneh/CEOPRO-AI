"""Test-only entrypoint for main's existing billing implementation.

No parallel subscription implementation or migrations live here. Catalog
verification delegates to main's existing sync command, in Stripe TEST mode
only, with dry-run as the default. Database tests require a dedicated local
disposable test cluster.
Run from backend: python -m scripts.billing_verification test [--database]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from contextlib import closing
from pathlib import Path
from urllib.parse import unquote, urlsplit

BACKEND = Path(__file__).resolve().parents[1]
REQUIRED_TABLES = (
    "companies",
    "users",
    "tenant_users",
    "usage_plans",
    "billing_plan_prices",
    "billing_customers",
    "billing_subscriptions",
    "billing_payments",
    "billing_webhook_events",
    "billing_trials",
    "tenant_plan_assignments",
)


class VerificationRefused(ValueError):
    pass


def validate_test_environment(
    environ: dict[str, str], *, database: bool = False
) -> str | None:
    """Validate before importing the application or opening any connection."""
    key = environ.get("STRIPE_SECRET_KEY", "").strip()
    if key and not key.startswith(("sk_test_", "rk_test_")):
        raise VerificationRefused(
            "Only Stripe TEST-mode keys are permitted; clear the key for offline tests."
        )
    if not database:
        return None
    raw = environ.get("BILLING_TEST_DATABASE_URL", "").strip()
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError:
        raise VerificationRefused("Invalid BILLING_TEST_DATABASE_URL.") from None
    name = unquote(parsed.path.lstrip("/"))
    if (
        parsed.scheme not in ("postgresql", "postgres")
        or parsed.hostname not in ("127.0.0.1", "localhost", "::1")
        or not re.fullmatch(r"keel_billing_test(?:_[a-z0-9]+)?", name)
        or not parsed.username
        or not port
        or parsed.query
        or parsed.fragment
    ):
        raise VerificationRefused(
            "Database tests require an explicit localhost PostgreSQL URL with a port and "
            "database named keel_billing_test (or keel_billing_test_<suffix>), without URL options. "
            "DATABASE_URL is never used as a fallback."
        )
    return raw


def preflight(environ: dict[str, str]) -> dict:
    """Inspect only: no catalog sync, DDL, seeding or Stripe network calls."""
    url = validate_test_environment(environ, database=True)
    import psycopg2

    try:
        with closing(
            psycopg2.connect(
                url, connect_timeout=5, gssencmode="disable", sslmode="disable"
            )
        ) as conn:
            conn.set_session(readonly=True)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT current_database(), current_setting('server_version')"
                )
                name, version = cur.fetchone()
                if not re.fullmatch(r"keel_billing_test(?:_[a-z0-9]+)?", name):
                    raise VerificationRefused(
                        "Connected database is not the requested dedicated test database."
                    )
                missing = []
                for table in REQUIRED_TABLES:
                    cur.execute("SELECT to_regclass(%s)", ("public." + table,))
                    if cur.fetchone()[0] is None:
                        missing.append(table)
                cur.execute(
                    "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname='ceopro_app'"
                )
                role = cur.fetchone()
                if missing or not role or any(role):
                    return {
                        "status": "BLOCKED",
                        "databaseWrites": False,
                        "stripeCalls": False,
                        "missingTables": missing,
                        "restrictedApplicationRole": bool(role and not any(role)),
                    }
                cur.execute(
                    "SELECT count(*) FROM billing_plan_prices WHERE retired_at IS NULL AND stripe_price_id IS NOT NULL"
                )
                linked = cur.fetchone()[0]
                return {
                    "status": "PASS",
                    "databaseWrites": False,
                    "stripeCalls": False,
                    "postgresVersion": version,
                    "restrictedApplicationRole": True,
                    "linkedCurrentPrices": linked,
                    "note": "A schema preflight, not proof that Stripe prices or checkout are reachable.",
                }
    except VerificationRefused:
        raise
    except psycopg2.Error:
        raise VerificationRefused(
            "Test database preflight failed; check the dedicated cluster, credentials and migrations locally."
        ) from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser(
        "preflight", help="Read-only dedicated-test-database schema/role inspection"
    )
    test = sub.add_parser(
        "test",
        help="Offline Stripe adapter tests; optionally PostgreSQL persistence tests",
    )
    test.add_argument(
        "--database",
        action="store_true",
        help="Allow fixture writes to a dedicated test database",
    )
    catalog = sub.add_parser(
        "catalog-test",
        help="Reuse main's Stripe TEST catalog sync (dry-run by default)",
    )
    catalog.add_argument(
        "--apply",
        action="store_true",
        help="Explicitly link/create TEST-mode prices in the dedicated test database",
    )
    args = parser.parse_args(argv)
    try:
        if args.command == "catalog-test":
            url = validate_test_environment(dict(os.environ), database=True)
            if not os.environ.get("STRIPE_SECRET_KEY", "").strip():
                raise VerificationRefused(
                    "STRIPE_SECRET_KEY must be a configured TEST-mode key for catalog verification."
                )
            env = dict(os.environ)
            env["DATABASE_URL"] = url
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            env.pop("CONFIRM_LIVE_STRIPE", None)
            command = [sys.executable, "-m", "scripts.stripe_sync_catalog"]
            if not args.apply:
                command.append("--dry-run")
            return subprocess.run(command, cwd=BACKEND, env=env, check=False).returncode
        if args.command == "preflight":
            result = preflight(dict(os.environ))
            print(json.dumps(result, indent=2))
            return 0 if result["status"] == "PASS" else 2
        url = validate_test_environment(dict(os.environ), database=args.database)
        env = dict(os.environ)
        env["BILLING_DATABASE_TESTS"] = "1" if args.database else "0"
        if url:
            env["DATABASE_URL"] = url
            env["AI_TEST_DATABASE_URL"] = url
        else:
            # Offline tests must not accidentally use the developer's DB.
            env.pop("DATABASE_URL", None)
            env.pop("AI_TEST_DATABASE_URL", None)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        with tempfile.TemporaryDirectory(prefix="keel-billing-pytest-") as cache:
            return subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    *(
                        ["tests/billing"]
                        if args.database
                        else [
                            "tests/billing/test_safety.py",
                            "tests/billing/test_contract.py",
                        ]
                    ),
                    "-q",
                    "-ra",
                    "-o",
                    f"cache_dir={cache}",
                ],
                cwd=BACKEND,
                env=env,
                check=False,
            ).returncode
    except VerificationRefused as error:
        print(f"REFUSED: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
