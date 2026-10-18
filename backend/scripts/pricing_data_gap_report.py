"""
How much data does price intelligence actually have, and what is missing?

Read-only. For one tenant (--tenant-id) or every tenant with products, prints
the market-price coverage (market_scraper/price_coverage.py, the same numbers
as GET /pricing/coverage), plus the other inputs a price decision depends on:
products with a cost (the margin floor), products with a barcode (exact
price-database matches), and recommendation_outcomes (the history learned
pricing needs - spec S19 keeps it disabled until that exists).

    DATABASE_URL=postgresql://ceopro_admin:...@host/db \\
        python scripts/pricing_data_gap_report.py [--tenant-id <uuid>] [--limit 20]

Connects as the schema owner, so it sees every tenant: run it against a
database you own, never expose its output to a tenant.
"""
import argparse
import os
import sys
from collections import Counter

import psycopg2

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.market_scraper import price_coverage  # noqa: E402

_TENANTS = """
    SELECT t.tenant_id, COUNT(*) AS products
    FROM products p JOIN companies t ON t.tenant_id = p.tenant_id
    WHERE p.deleted_at IS NULL AND (%s::uuid IS NULL OR t.tenant_id = %s::uuid)
    GROUP BY t.tenant_id ORDER BY products DESC LIMIT %s;
"""
_INPUTS = """
    SELECT COUNT(*) FILTER (WHERE cost_price IS NOT NULL AND cost_price > 0)
    FROM products WHERE tenant_id = %s AND deleted_at IS NULL;
"""
_OUTCOMES = "SELECT COUNT(*), COUNT(*) FILTER (WHERE user_decision <> 'PENDING') FROM recommendation_outcomes WHERE tenant_id = %s;"


def _pct(part: int, whole: int) -> str:
    return f"{part / whole * 100:.0f}%" if whole else "n/a"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tenant-id")
    parser.add_argument("--limit", type=int, default=20, help="most-populated tenants to report (default 20)")
    args = parser.parse_args()
    url = os.getenv("DATABASE_URL")
    if not url:
        print("DATABASE_URL is required", file=sys.stderr)
        return 2

    conn = psycopg2.connect(url)
    totals, reasons = Counter(), Counter()
    try:
        with conn.cursor() as cursor:
            cursor.execute(_TENANTS, (args.tenant_id, args.tenant_id, args.limit))
            tenants = cursor.fetchall()
        if not tenants:
            print("No tenant with products found.")
            return 0
        for tenant_id, products in tenants:
            tenant_id = str(tenant_id)
            summary = price_coverage.get_price_coverage(conn, tenant_id, limit=0)["summary"]
            with conn.cursor() as cursor:
                cursor.execute(_INPUTS, (tenant_id,))
                (with_cost,) = cursor.fetchone()
                cursor.execute(_OUTCOMES, (tenant_id,))
                outcomes, decided = cursor.fetchone()
            print(f"{tenant_id}  products={products}")
            print(f"  market price : {summary['with_market_price']}/{products} ({_pct(summary['with_market_price'], products)})"
                  f"  competitor={summary['with_competitor_price']}  reference-only={summary['with_reference_price_only']}")
            print(f"  gaps by cause: {summary['gaps_by_reason']}")
            print(f"  stale={summary['stale_prices']}  currency-mismatch={summary['currency_mismatches']}"
                  f"  inactive-mapping={summary['inactive_mappings']}")
            print(f"  with cost    : {with_cost}/{products} ({_pct(with_cost, products)})   with barcode: {products - summary['products_without_barcode']}/{products}")
            print(f"  outcomes     : {outcomes} recorded, {decided} decided\n")
            totals.update(products=products, priced=summary["with_market_price"], cost=with_cost, outcomes=outcomes, acted=decided)
            reasons.update(summary["gaps_by_reason"])
        print(f"TOTAL ({len(tenants)} tenants): {totals['priced']}/{totals['products']} products have a market price "
              f"({_pct(totals['priced'], totals['products'])}); {totals['cost']} have a cost; "
              f"{totals['outcomes']} outcomes ({totals['acted']} decided)")
        print(f"Dominant gap cause: {reasons.most_common(1)[0][0] if reasons and any(reasons.values()) else 'none'}  {dict(reasons)}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
