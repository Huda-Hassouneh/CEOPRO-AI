"""Guarded verification of main's existing billing and entitlement authority.

Run from backend: python -m scripts.integration_review [--database]
Only isolated test fixtures are written. Does not migrate databases or call
Stripe. Native multi-session and runtime-role login tests require PostgreSQL.
"""

import argparse
import os
import subprocess
import sys
import tempfile

from scripts.billing_verification import BACKEND, validate_test_environment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", action="store_true")
    parser.add_argument("--junitxml", help="Optional local test-result output file")
    args = parser.parse_args()
    env = dict(os.environ)
    validate_test_environment(env, database=args.database)
    env.update(
        BILLING_DATABASE_TESTS="1" if args.database else "0",
        KEEL_TEST_DISABLE_METERING="0",
        UNASSIGNED_PLAN_ACCESS="none",
        PYTHONDONTWRITEBYTECODE="1",
    )
    if not args.database:
        for key in (
            "BILLING_TEST_DATABASE_URL",
            "AI_TEST_DATABASE_URL",
            "DATABASE_URL",
            "APP_DB_PASSWORD",
        ):
            env.pop(key, None)
    extra = ["--junitxml", args.junitxml] if args.junitxml else []
    with tempfile.TemporaryDirectory(prefix="keel-review-pytest-") as cache:
        return subprocess.call(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "-ra",
                "-o",
                f"cache_dir={cache}",
                *extra,
                "tests/billing",
                "tests/entitlements",
                "tests/integration_review",
                "tests/remediation",
                "src/ai/tests/test_billing_consistency.py",
            ],
            cwd=BACKEND,
            env=env,
        )


if __name__ == "__main__":
    raise SystemExit(main())
