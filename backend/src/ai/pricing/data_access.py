"""
KEEL - Price Intelligence Data Access.
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

# Every product needs a market reference, so an old price is better than none:
# the window is 3 years. Only each competitor's latest price is used (see
# _load_competitor_prices), and the pipeline discloses the collection date of
# old data (spec S19's "Date of collection" requirement).
MAX_PRICE_AGE_DAYS = int(os.getenv("PRICING_MAX_PRICE_AGE_DAYS", "1095"))


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
    # DISTINCT ON: each competitor's LATEST qualifying price only. Found in
    # acceptance testing: two observations of the same rival counted as a
    # "2-competitor market average", so a competitor scraped (or checked)
    # repeatedly outweighed the others and inflated the confidence.
    query = f"""
        SELECT DISTINCT ON (tc.global_competitor_id)
               cp.competitor_price_id, tc.global_competitor_id, gc.competitor_name, cp.scraped_price,
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
          AND cp.observed_at >= NOW() - (%s || ' days')::interval
        ORDER BY tc.global_competitor_id, cp.observed_at DESC;
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


# Competitors excluded only because they sit outside the tenant's operating
# region (see competitor_classification.py) are still valid market references
# when nothing local exists - estimation.py adjusts their prices for the
# regional difference before use. Manufacturers/wholesalers never qualify.
OUT_OF_REGION_REASON_PREFIX = "excluded: competitor country"


def load_reference_competitor_prices(conn, tenant_id: str, product_id: str, max_age_days: int = None) -> list:
    """
    Latest usable price per competitor for this product in ANY currency, from
    competitors that are tracked OR were excluded only for being out of
    region; plus the product's market reference prices (price_lookup/:
    market_price_observations, plausible ones only). Each record carries
    `source` ("competitor" | "market_reference").
    """
    max_age_days = MAX_PRICE_AGE_DAYS if max_age_days is None else max_age_days
    competitor_query = """
        SELECT DISTINCT ON (tc.global_competitor_id)
               cp.competitor_price_id, gc.competitor_name, cp.scraped_price, cp.currency, cp.observed_at
        FROM competitor_prices cp
        JOIN competitor_product_mappings cpm ON cpm.mapping_id = cp.mapping_id AND cpm.tenant_id = cp.tenant_id
        JOIN tenant_competitors tc ON tc.tenant_id = cpm.tenant_id AND tc.global_competitor_id = cpm.global_competitor_id
        JOIN global_competitors gc ON gc.global_competitor_id = tc.global_competitor_id
        WHERE cp.tenant_id = %s
          AND cpm.product_id = %s
          AND cp.is_exact_data = TRUE
          AND cp.source_status = 'ALLOWED'
          AND cp.is_available = TRUE
          AND cpm.is_active = TRUE
          AND gc.is_manufacturer = FALSE
          AND (tc.is_tracked = TRUE OR tc.classification_reason LIKE %s)
          AND cp.observed_at >= NOW() - (%s || ' days')::interval
        ORDER BY tc.global_competitor_id, cp.observed_at DESC;
    """
    observation_query = """
        SELECT DISTINCT ON (COALESCE(seller_name, provider))
               observation_id, COALESCE(seller_name, provider), price, currency, observed_at
        FROM market_price_observations
        WHERE tenant_id = %s AND product_id = %s AND plausible IS NOT FALSE
          AND observed_at >= NOW() - (%s || ' days')::interval
        ORDER BY COALESCE(seller_name, provider), observed_at DESC;
    """
    with conn.cursor() as cursor:
        cursor.execute(competitor_query, (tenant_id, product_id, OUT_OF_REGION_REASON_PREFIX + "%", str(max_age_days)))
        competitor_rows = cursor.fetchall()
        cursor.execute(observation_query, (tenant_id, product_id, str(max_age_days)))
        observation_rows = cursor.fetchall()
    return [
        {"price_entry_id": str(r[0]), "competitor_name": r[1], "price_found": float(r[2]), "currency": r[3],
         "captured_at": r[4], "source": source}
        for source, rows in (("competitor", competitor_rows), ("market_reference", observation_rows))
        for r in rows
    ]


def load_tenant_market_snapshot(conn, tenant_id: str, max_age_days: int = None) -> list:
    """
    One entry per active product: {product_id, category, cost, current_price,
    currency, prices: [(price, currency)]} using each competitor's latest
    usable price plus plausible market reference prices. Calibration input
    for estimation.py (regional factor, peer markup); includes products with
    no prices (empty list).
    """
    max_age_days = MAX_PRICE_AGE_DAYS if max_age_days is None else max_age_days
    products_query = """
        SELECT product_id, category, cost_price, current_price, currency
        FROM products WHERE tenant_id = %s AND deleted_at IS NULL;
    """
    competitor_query = """
        SELECT DISTINCT ON (cpm.product_id, tc.global_competitor_id)
               cpm.product_id, cp.scraped_price, cp.currency
        FROM competitor_prices cp
        JOIN competitor_product_mappings cpm ON cpm.mapping_id = cp.mapping_id AND cpm.tenant_id = cp.tenant_id
        JOIN tenant_competitors tc ON tc.tenant_id = cpm.tenant_id AND tc.global_competitor_id = cpm.global_competitor_id
        JOIN global_competitors gc ON gc.global_competitor_id = tc.global_competitor_id
        WHERE cp.tenant_id = %s
          AND cp.is_exact_data = TRUE AND cp.source_status = 'ALLOWED' AND cp.is_available = TRUE
          AND cpm.is_active = TRUE AND gc.is_manufacturer = FALSE
          AND (tc.is_tracked = TRUE OR tc.classification_reason LIKE %s)
          AND cp.observed_at >= NOW() - (%s || ' days')::interval
        ORDER BY cpm.product_id, tc.global_competitor_id, cp.observed_at DESC;
    """
    observation_query = """
        SELECT DISTINCT ON (product_id, COALESCE(seller_name, provider)) product_id, price, currency
        FROM market_price_observations
        WHERE tenant_id = %s AND plausible IS NOT FALSE AND observed_at >= NOW() - (%s || ' days')::interval
        ORDER BY product_id, COALESCE(seller_name, provider), observed_at DESC;
    """
    with conn.cursor() as cursor:
        cursor.execute(products_query, (tenant_id,))
        product_rows = cursor.fetchall()
        cursor.execute(competitor_query, (tenant_id, OUT_OF_REGION_REASON_PREFIX + "%", str(max_age_days)))
        competitor_rows = cursor.fetchall()
        cursor.execute(observation_query, (tenant_id, str(max_age_days)))
        observation_rows = cursor.fetchall()

    products = {
        str(r[0]): {
            "product_id": str(r[0]),
            "category": _category_key(r[1]),
            "cost": float(r[2]) if r[2] is not None else None,
            "current_price": float(r[3]),
            "currency": r[4],
            "prices": [],
        }
        for r in product_rows
    }
    for product_id, price, price_currency in [*competitor_rows, *observation_rows]:
        if str(product_id) in products:
            products[str(product_id)]["prices"].append((float(price), price_currency))
    return list(products.values())


def _category_key(category) -> Optional[str]:
    if isinstance(category, dict):
        text = category.get("en") or next((v for v in category.values() if isinstance(v, str) and v), None)
    else:
        text = category
    return text.strip().lower() if isinstance(text, str) and text.strip() else None


def load_comparable_prices(conn, tenant_id: str, product_id: str, currency: str, max_age_days: int = None) -> list:
    """
    Prices of competitors' items that are not the same product but can stand in for it, from the
    price comparison ladder (market_scraper/price_comparison/): EQUIVALENT rows (the same item in
    another quantity, already scaled to this product's) and SIMILAR rows that are a like-for-like swap
    (direction 'same': another flavour or variant at the same size and richness). SIMILAR rows where
    one side has more in it (a bigger size, extras, a nearby quantity) are left out: averaging them in
    would pull a richer product's price down toward leaner items, or the reverse. Pairs where one name is the
    other plus words nobody has judged yet (an extra or just a variant) are left out too. ADDED_VALUE rows are
    never returned: the company's richer product is not what a market average measures. Same-currency, tracked, non-manufacturer competitors, within the
    freshness window. `price_found` is the comparable price; each record carries its `tier`.
    A deployment without the table yet returns [].
    """
    max_age_days = MAX_PRICE_AGE_DAYS if max_age_days is None else max_age_days
    query = """
        SELECT c.comparison_id, c.global_competitor_id, gc.competitor_name, c.comparable_price, c.currency,
               c.observed_at, c.tier
        FROM product_price_comparisons c
        JOIN tenant_competitors tc ON tc.tenant_id = c.tenant_id AND tc.global_competitor_id = c.global_competitor_id
        JOIN global_competitors gc ON gc.global_competitor_id = c.global_competitor_id
        WHERE c.tenant_id = %s AND c.product_id = %s AND c.currency = %s
          AND (c.tier = 'EQUIVALENT' OR (c.tier = 'SIMILAR' AND c.direction = 'same'))
          AND NOT (c.reasons @> '[{"code": "specificity_unclear"}]'::jsonb)
          AND tc.is_tracked = TRUE AND gc.is_manufacturer = FALSE
          AND c.observed_at >= NOW() - (%s || ' days')::interval;
    """
    with conn.cursor() as cursor:
        cursor.execute("SAVEPOINT comparable_prices_read;")
        try:
            cursor.execute(query, (tenant_id, product_id, currency, str(max_age_days)))
            rows = cursor.fetchall()
        except Exception as exc:  # noqa: BLE001
            cursor.execute("ROLLBACK TO SAVEPOINT comparable_prices_read;")
            if getattr(exc, "pgcode", None) != "42P01":  # undefined_table: migration 20261024000000 not applied yet
                raise
            return []
        cursor.execute("RELEASE SAVEPOINT comparable_prices_read;")
    return [
        {"price_entry_id": str(r[0]), "competitor_id": str(r[1]), "competitor_name": r[2], "price_found": float(r[3]),
         "currency": r[4], "captured_at": r[5], "tier": r[6]}
        for r in rows
    ]
