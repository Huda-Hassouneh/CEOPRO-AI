"""
Competitor prices the business owner records by hand.

Found in first-customer acceptance testing: competitor_prices was only ever
written by the automated scraper, so a business whose competitors have no
scrapeable website (a shop across the street, a supplier's printed price
list, a marketplace that blocks bots) - or any deployment where scraping is
unavailable - could never get a price recommendation: pricing only ever
answered "No competitor price data found". Owners already check rivals'
prices on store visits and by phone; this records those observations into
the same tables the scraper writes (an active competitor_product_mappings
row plus a competitor_prices row), so pricing, the dashboard's competitor
pricing card and price-competitiveness all use them with no special case.
Recorded as exact, ALLOWED data - the owner saw the price themselves.
"""
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional


class NotFound(LookupError):
    """Unknown/untracked competitor or product for this tenant (RLS-hidden
    rows from another tenant look exactly the same - deliberately)."""


def _tracked_competitor(conn, tenant_id: str, competitor_id: str) -> Optional[str]:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT gc.competitor_name FROM tenant_competitors tc
            JOIN global_competitors gc ON gc.global_competitor_id = tc.global_competitor_id
            WHERE tc.tenant_id = %s AND tc.global_competitor_id = %s AND tc.is_tracked = TRUE;
            """,
            (tenant_id, competitor_id),
        )
        row = cursor.fetchone()
    return row[0] if row else None


def record_competitor_price(
    conn, tenant_id: str, competitor_id: str, product_id: str, price: Decimal, currency: str,
    product_url: Optional[str] = None, observed_at: Optional[datetime] = None,
) -> dict:
    competitor_name = _tracked_competitor(conn, tenant_id, competitor_id)
    if competitor_name is None:
        raise NotFound("Competitor not found")
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT COALESCE(product_name->>'en', product_name->>'ar', product_name::text) FROM products "
            "WHERE tenant_id = %s AND product_id = %s AND deleted_at IS NULL;",
            (tenant_id, product_id),
        )
        product_row = cursor.fetchone()
        if product_row is None:
            raise NotFound("Product not found")
        cursor.execute(
            """
            INSERT INTO competitor_product_mappings (tenant_id, global_competitor_id, product_id, competitor_product_url)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (tenant_id, global_competitor_id, product_id) DO UPDATE
                SET is_active = TRUE,
                    competitor_product_url = COALESCE(EXCLUDED.competitor_product_url, competitor_product_mappings.competitor_product_url)
            RETURNING mapping_id;
            """,
            (tenant_id, competitor_id, product_id, product_url),
        )
        mapping_id = cursor.fetchone()[0]
        observed = observed_at or datetime.now(timezone.utc)
        cursor.execute(
            """
            INSERT INTO competitor_prices
                (tenant_id, mapping_id, scraped_price, currency, is_available, observed_at, source_status, is_exact_data)
            VALUES (%s, %s, %s, %s, TRUE, %s, 'ALLOWED', TRUE)
            RETURNING competitor_price_id;
            """,
            (tenant_id, mapping_id, price, currency, observed),
        )
        price_id = cursor.fetchone()[0]
    return {
        "competitor_price_id": str(price_id),
        "competitor_id": competitor_id,
        "competitor_name": competitor_name,
        "product_id": product_id,
        "product_name": product_row[0],
        "price": float(price),
        "currency": currency,
        "observed_at": observed.isoformat(),
    }


def list_competitor_prices(conn, tenant_id: str, competitor_id: str, limit: int = 100) -> list:
    if _tracked_competitor(conn, tenant_id, competitor_id) is None:
        raise NotFound("Competitor not found")
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT cp.competitor_price_id, cpm.product_id,
                   COALESCE(p.product_name->>'en', p.product_name->>'ar', p.product_name::text),
                   cp.scraped_price, cp.currency, cp.observed_at, cpm.competitor_product_url,
                   p.current_price, p.currency
            FROM competitor_prices cp
            JOIN competitor_product_mappings cpm ON cpm.tenant_id = cp.tenant_id AND cpm.mapping_id = cp.mapping_id
            JOIN products p ON p.tenant_id = cpm.tenant_id AND p.product_id = cpm.product_id AND p.deleted_at IS NULL
            WHERE cp.tenant_id = %s AND cpm.global_competitor_id = %s
            ORDER BY cp.observed_at DESC
            LIMIT %s;
            """,
            (tenant_id, competitor_id, limit),
        )
        rows = cursor.fetchall()
    return [
        {
            "competitor_price_id": str(price_id), "product_id": str(product_id), "product_name": name,
            "price": float(price), "currency": currency, "observed_at": observed.isoformat(),
            "product_url": url, "own_price": float(own_price), "own_currency": own_currency,
        }
        for price_id, product_id, name, price, currency, observed, url, own_price, own_currency in rows
    ]
