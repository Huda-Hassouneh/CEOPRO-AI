"""
Creates the Stripe Product and Prices for KEEL's plan catalog and records each
Stripe price id against its plan and billing period (billing_plan_prices).
Safe to re-run: existing price ids are kept, and every create carries an
idempotency key derived from plan, period, amount and currency.

Adapted from the reference project's production-plan bootstrap (read-only
reference: prisma/bootstrap/production-plans.ts and helpers/stripe.ts).

Usage (from backend/, with DATABASE_URL and STRIPE_SECRET_KEY set):
    python -m scripts.stripe_sync_catalog            # create missing prices
    python -m scripts.stripe_sync_catalog --dry-run  # show what would change
A live key (sk_live_...) also requires CONFIRM_LIVE_STRIPE=YES.
"""
import argparse
import hashlib
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg2  # noqa: E402

from src.ai.billing import config, stripe_api  # noqa: E402


def _minor(amount: float, currency: str) -> int:
    zero_decimal = {"jpy", "krw", "vnd", "clp", "xaf", "xof", "xpf", "bif", "djf", "gnf", "kmf", "mga", "pyg", "rwf", "ugx", "vuv"}
    return int(round(amount)) if currency.lower() in zero_decimal else int(round(amount * 100))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    key = config.stripe_secret_key()
    if not key:
        print("STRIPE_SECRET_KEY is not set.", file=sys.stderr)
        return 2
    if key.startswith("sk_live_") and os.getenv("CONFIRM_LIVE_STRIPE") != "YES":
        print("Refusing to change a live Stripe account without CONFIRM_LIVE_STRIPE=YES.", file=sys.stderr)
        return 2

    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT p.price_id, p.plan_key, u.display_name, p.period_code, p.interval_months, p.amount, p.currency
                FROM billing_plan_prices p JOIN usage_plans u ON u.plan_key = p.plan_key
                WHERE p.retired_at IS NULL AND p.stripe_price_id IS NULL AND u.self_serve AND u.is_active
                ORDER BY u.tier_level, p.interval_months;
                """
            )
            missing = cursor.fetchall()
        if not missing:
            print("Every self-serve plan price already has a Stripe price.")
            return 0
        product_id = os.getenv("STRIPE_PRODUCT_ID")
        if not product_id and not args.dry_run:
            product_id = stripe_api.create_product("KEEL", idempotency_key="apex-product-v1")["id"]
            print(f"Created Stripe product {product_id}. Set STRIPE_PRODUCT_ID={product_id} for future runs.")
        for price_id, plan_key, plan_name, period, months, amount, currency in missing:
            unit_amount = _minor(float(amount), currency)
            label = f"{plan_name} - {period} - {amount} {currency}"
            if args.dry_run:
                print(f"would create: {label}")
                continue
            digest = hashlib.sha256(f"{plan_key}|{period}|{unit_amount}|{currency}".encode()).hexdigest()[:24]
            price = stripe_api.create_price({
                "product": product_id,
                "currency": currency.lower(),
                "unit_amount": unit_amount,
                "recurring": {"interval": "month", "interval_count": months},
                "nickname": f"KEEL {plan_name} ({period})",
                "metadata": {"plan_key": plan_key, "period_code": period},
            }, idempotency_key=f"apex-price-{digest}")
            with conn.cursor() as cursor:
                cursor.execute("UPDATE billing_plan_prices SET stripe_price_id = %s WHERE price_id = %s;", (price["id"], price_id))
            conn.commit()
            print(f"created {price['id']}: {label}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
