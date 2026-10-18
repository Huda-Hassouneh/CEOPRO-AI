"""
Operator tool: put a company on a plan without online payment (an agreed
Custom plan, an invoice paid by bank transfer, or a pilot). Recorded as
source='manual'; a later Stripe subscription takes over automatically.

Usage (from backend/, with DATABASE_URL set):
    python -m scripts.assign_plan --tenant <tenant_id> --plan pro --months 1
    python -m scripts.assign_plan --tenant <tenant_id> --plan custom --months 12
    python -m scripts.assign_plan --tenant <tenant_id> --show
"""
import argparse
import os
import sys
from datetime import date, timedelta

import psycopg2


def main() -> int:
    parser = argparse.ArgumentParser(description="Assign a plan to a company.")
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--plan")
    parser.add_argument("--months", type=int, default=1)
    parser.add_argument("--status", default="active", choices=["active", "trialing", "paused", "cancelled"])
    parser.add_argument("--show", action="store_true")
    args = parser.parse_args()
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT business_name FROM companies WHERE tenant_id = %s;", (args.tenant,))
            company = cursor.fetchone()
            if not company:
                print("No company with that id.", file=sys.stderr)
                return 1
            if not args.show:
                if not args.plan:
                    parser.error("--plan is required unless --show is given")
                cursor.execute("SELECT 1 FROM usage_plans WHERE plan_key = %s;", (args.plan,))
                if not cursor.fetchone():
                    print(f"Unknown plan {args.plan!r}.", file=sys.stderr)
                    return 1
                start = date.today()
                end = start + timedelta(days=30 * args.months) - timedelta(days=1)
                cursor.execute(
                    """
                    INSERT INTO tenant_plan_assignments (tenant_id, plan_key, status, current_period_start, current_period_end, source)
                    VALUES (%s, %s, %s, %s, %s, 'manual')
                    ON CONFLICT (tenant_id) DO UPDATE SET plan_key = EXCLUDED.plan_key, status = EXCLUDED.status,
                        current_period_start = EXCLUDED.current_period_start, current_period_end = EXCLUDED.current_period_end,
                        source = 'manual', updated_at = CURRENT_TIMESTAMP;
                    """,
                    (args.tenant, args.plan, args.status, start, end),
                )
                conn.commit()
            cursor.execute(
                "SELECT plan_key, status, current_period_start, current_period_end, source FROM tenant_plan_assignments WHERE tenant_id = %s;",
                (args.tenant,),
            )
            print(company[0], cursor.fetchone())
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
