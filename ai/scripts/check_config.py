"""
Checks this environment's settings against backend/KEYS_AND_ACCOUNTS_NEEDED.md:
required settings, address and CORS shape, email, storage, the credential
vault key, half-configured integrations and, with --db, paid integrations
that have no confirmed price (their calls are refused). Prints setting
names and problems only - never a value.

Usage (from backend/, with the environment you want to check loaded):
    python -m scripts.check_config          # settings only
    python -m scripts.check_config --db     # also billing prices (needs DATABASE_URL)
Exit code 1 when there is an error, 0 otherwise (warnings are reported).
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.ai.core import config_check  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Check KEEL's configuration.")
    parser.add_argument("--db", action="store_true", help="also check provider prices in the database")
    args = parser.parse_args(argv)

    findings = config_check.check_environment()
    if args.db:
        import psycopg2

        conn = psycopg2.connect(os.environ["DATABASE_URL"].replace("+asyncpg", ""))
        try:
            findings += config_check.check_billing(conn)
        finally:
            conn.close()
    where = "deployed (" + os.getenv("SENTRY_ENVIRONMENT", "") + ")" if config_check.deployed() else "local development"
    print(f"KEEL configuration check - {where}")
    for finding in findings:
        print("  " + finding.line())
    errors = sum(f.level == config_check.ERROR for f in findings)
    print(f"{errors} error(s), {len(findings) - errors} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
