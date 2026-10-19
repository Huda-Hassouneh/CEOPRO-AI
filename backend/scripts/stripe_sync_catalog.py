"""
Links KEEL's plan catalog (billing_plan_prices) to Stripe prices, creating a
Stripe price only when no matching one exists. Safe to run any number of times,
at any time, against any database: it first reads the KEEL product and its
active prices from Stripe and reconciles them with the database (see
src/ai/billing/catalog_sync.py) instead of relying on Stripe idempotency keys,
which expire after 24 hours.

Usage (from backend/, with DATABASE_URL and STRIPE_SECRET_KEY set):
    python -m scripts.stripe_sync_catalog --dry-run   # show ADOPT / CREATE / drift, change nothing
    python -m scripts.stripe_sync_catalog             # apply
Exit codes: 0 ok, 1 a person must resolve a mismatch (drift/missing price), 2 unsafe or unconfigured.
A live key (sk_live_...) also requires CONFIRM_LIVE_STRIPE=YES.
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg2  # noqa: E402

from src.ai.billing import catalog_sync, config, stripe_api  # noqa: E402

_LOCK_KEY = "keel_stripe_catalog_sync"


def _rows(conn) -> list:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT p.price_id, p.plan_key, u.display_name, p.period_code, p.interval_months, p.amount, p.currency, p.stripe_price_id
            FROM billing_plan_prices p JOIN usage_plans u ON u.plan_key = p.plan_key
            WHERE p.retired_at IS NULL AND u.self_serve AND u.is_active
            ORDER BY u.tier_level, p.interval_months;
            """
        )
        keys = ("price_id", "plan_key", "display_name", "period_code", "interval_months", "amount", "currency", "stripe_price_id")
        rows = [dict(zip(keys, r)) for r in cursor.fetchall()]
    for row in rows:
        row["price_id"] = str(row["price_id"])
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    key = config.stripe_secret_key()
    if not key:
        print("STRIPE_SECRET_KEY is not set.", file=sys.stderr)
        return 2
    if key.startswith(("sk_live_", "rk_live_")) and os.getenv("CONFIRM_LIVE_STRIPE") != "YES":
        print("Refusing to change a live Stripe account without CONFIRM_LIVE_STRIPE=YES.", file=sys.stderr)
        return 2

    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    try:
        with conn.cursor() as cursor:
            # One sync at a time per database: two concurrent runs could otherwise both create.
            cursor.execute("SELECT pg_try_advisory_lock(hashtextextended(%s, 0));", (_LOCK_KEY,))
            if not cursor.fetchone()[0]:
                print("Another catalog sync is running against this database; try again shortly.", file=sys.stderr)
                return 2
        try:
            try:
                product_id = catalog_sync.pick_product(stripe_api.list_products(), os.getenv("STRIPE_PRODUCT_ID") or None)
            except catalog_sync.CatalogError as err:
                print(f"STOP: {err}", file=sys.stderr)
                return 2
            prices = stripe_api.list_prices(product_id) if product_id else []
            actions = catalog_sync.plan(_rows(conn), prices, product_id)

            print(f"Stripe product: {product_id or '(none yet - will be created)'}; {len(prices)} active price(s) on it.")
            for a in actions:
                note = f" -> {a.stripe_price_id}" if a.stripe_price_id else ""
                print(f"{a.kind.upper():10} {a.label}{note}{(' | ' + a.detail) if a.detail else ''}")
            bad = catalog_sync.problems(actions)
            if bad:
                print(f"\nSTOP: {len(bad)} mismatch(es) between the database and Stripe need a person to resolve (see above). Nothing was changed.", file=sys.stderr)
                return 1
            if args.dry_run:
                print("\nDry run: nothing changed.")
                return 0

            if not product_id and any(a.kind == "create" for a in actions):
                product_id = stripe_api.create_product(catalog_sync.PRODUCT_NAME, idempotency_key="apex-product-v1")["id"]
                for a in actions:
                    if a.kind == "create":
                        a.params["product"] = product_id
                print(f"Created Stripe product {product_id}.")

            def link(row_id, stripe_price_id):
                with conn.cursor() as cursor:
                    cursor.execute("UPDATE billing_plan_prices SET stripe_price_id = %s WHERE price_id = %s AND stripe_price_id IS NULL;",
                                   (stripe_price_id, row_id))
                conn.commit()

            def create(params):
                # A key derived from the exact request still stops a double-click within Stripe's window;
                # correctness no longer depends on it because plan() ran against live Stripe state just now.
                import hashlib
                digest = hashlib.sha256(repr(sorted(params.items())).encode()).hexdigest()[:24]
                return stripe_api.create_price(params, idempotency_key=f"apex-price-{digest}")

            done = catalog_sync.apply(actions, link, create)
            print(f"\nDone: {done['adopted']} adopted, {done['created']} created.")
            return 0
        finally:
            with conn.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock(hashtextextended(%s, 0));", (_LOCK_KEY,))
            conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
