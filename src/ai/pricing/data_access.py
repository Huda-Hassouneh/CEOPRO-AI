"""
CEOPRO AI - Price Intelligence Data Access.
Reads own product price and competitor price records. Read-only against
tables owned by other services/teams (products, global_competitors/
tenant_competitors/competitor_product_mappings, competitor_prices - the
latter per DATA_OWNERSHIP_AND_CONTRACTS.md is written by the "AI Market
Scraper Service", a separate service this module only reads from).

Final_schema.sql restructured competitor pricing around competitor_product_mappings
(tenant_id, global_competitor_id, product_id, ...) - a competitor price now
joins directly to a specific product via that mapping, already resolved at
mapping-creation time. There is no more free-text product_name_captured to
fuzzy-match against products.product_name at query time (see matching.py's
docstring) - load_competitor_prices() below takes product_id directly.
"""

import os
from typing import Optional

# Stale competitor price data is worse than none - an old price silently
# treated as current would violate spec S19's "Date of collection" requirement.
MAX_PRICE_AGE_DAYS = int(os.getenv("PRICING_MAX_PRICE_AGE_DAYS", "30"))


def _representative_name(product_name) -> str:
    """
    products.product_name is JSONB (multilingual, e.g. {"en": "...", "ar": "..."}).
    Prefers English for a stable, deterministic display/log name; falls back
    to whichever language is actually populated if English isn't. Not used
    for matching (there is none left in the pricing path - see module
    docstring), only for evidence explanations and logging.
    """
    if isinstance(product_name, dict):
        if product_name.get("en"):
            return product_name["en"]
        return next(iter(product_name.values()), "")
    return product_name or ""


def load_own_product(conn, tenant_id: str, product_id: str) -> Optional[dict]:
    query = """
        SELECT product_name, current_price, currency, cost_price
        FROM products
        WHERE tenant_id = %s AND product_id = %s AND deleted_at IS NULL;
    """
    with conn.cursor() as cursor:
        cursor.execute(query, (tenant_id, product_id))
        row = cursor.fetchone()

    if not row:
        return None

    return {
        "product_name": _representative_name(row[0]),
        "current_price": float(row[1]),
        "currency": row[2],
        "cost": float(row[3]) if row[3] is not None else None,
    }


def _load_competitor_prices(
    conn, tenant_id: str, product_id: str, currency_filter: str, currency_operator: str, max_age_days: int
) -> list:
    query = f"""
        SELECT cp.competitor_price_id, tc.global_competitor_id, gc.competitor_name, cp.scraped_price,
               cp.currency, cp.observed_at
        FROM competitor_prices cp
        JOIN competitor_product_mappings cpm ON cpm.mapping_id = cp.mapping_id AND cpm.tenant_id = cp.tenant_id
        JOIN tenant_competitors tc ON tc.tenant_id = cpm.tenant_id AND tc.global_competitor_id = cpm.global_competitor_id
        JOIN global_competitors gc ON gc.global_competitor_id = tc.global_competitor_id
        WHERE cp.tenant_id = %s
          AND cpm.product_id = %s
          AND cp.currency {currency_operator} %s
          AND cp.is_exact_data = TRUE
          AND cp.source_status = 'ALLOWED'
          AND cp.is_available = TRUE
          AND cpm.is_active = TRUE
          AND tc.is_tracked = TRUE
          AND cp.observed_at >= NOW() - (%s || ' days')::interval;
    """
    with conn.cursor() as cursor:
        cursor.execute(query, (tenant_id, product_id, currency_filter, str(max_age_days)))
        rows = cursor.fetchall()

    return [
        {
            "price_entry_id": str(row[0]),
            "competitor_id": str(row[1]),
            "competitor_name": row[2],
            "price_found": float(row[3]),
            "currency": row[4],
            "captured_at": row[5],
        }
        for row in rows
    ]


def load_competitor_prices(conn, tenant_id: str, product_id: str, currency: str, max_age_days: int = None) -> list:
    """
    Only same-currency records for this specific product are returned -
    cross-currency comparison needs currency_rates (spec S9), handled
    separately by load_cross_currency_competitor_prices(). Only ALLOWED-source,
    exact-data, available records within the freshness window are returned
    (spec S13 Collection Policy Engine, spec S19's "Date of collection"),
    and only from mappings/competitors this tenant still actively tracks -
    a stale price from a competitor or mapping the tenant has since
    deactivated shouldn't influence a live recommendation.
    """
    max_age_days = MAX_PRICE_AGE_DAYS if max_age_days is None else max_age_days
    return _load_competitor_prices(conn, tenant_id, product_id, currency, "=", max_age_days)


def load_cross_currency_competitor_prices(
    conn, tenant_id: str, product_id: str, exclude_currency: str, max_age_days: int = None
) -> list:
    """
    Same filters as load_competitor_prices, but for every OTHER currency -
    i.e. candidates for cross-country reference (spec S19's "CROSS-COUNTRY
    COMPARISON"), never blended into the same-currency "LOCAL MARKET
    COMPARISON" set load_competitor_prices returns.
    """
    max_age_days = MAX_PRICE_AGE_DAYS if max_age_days is None else max_age_days
    return _load_competitor_prices(conn, tenant_id, product_id, exclude_currency, "!=", max_age_days)
