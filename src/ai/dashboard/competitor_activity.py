"""
CEOPRO AI - Dashboard Recent Competitor Activity (presentation layer, not
a new model, no new tables).

The mockup's "Recent Competitor Changes"/"Recent Competitor Activity"
feeds ask for real detected events (new product launched, marketing
campaign detected, price change...) - this platform only ever actually
detects ONE of those honestly today: a real price change, from two
consecutive competitor_prices observations on the same mapping. "New
product launched" and "marketing campaign detected" have no underlying
signal anywhere in this codebase (no product-catalog-diff detection, no
social/ad monitoring) - inventing them here would be exactly the kind of
fabricated insight this platform's own SYSTEM_PROMPT explicitly forbids
the chatbot from doing, so this module does not either. A mapping with
fewer than two price observations simply has no change to report yet -
that's a real, honest absence, not a bug.
"""
DEFAULT_LIMIT = 10


def get_recent_competitor_price_changes(conn, tenant_id: str, limit: int = DEFAULT_LIMIT) -> list:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            WITH ranked AS (
                SELECT cpr.mapping_id, cpr.scraped_price, cpr.currency, cpr.observed_at,
                       ROW_NUMBER() OVER (PARTITION BY cpr.mapping_id ORDER BY cpr.observed_at DESC) AS rn
                FROM competitor_prices cpr
                WHERE cpr.tenant_id = %(tenant_id)s
            )
            SELECT gc.competitor_name,
                   COALESCE(p.product_name->>'en', p.product_name->>'ar', p.product_name::text) AS product_name,
                   latest.scraped_price, prior.scraped_price, latest.currency, latest.observed_at
            FROM ranked latest
            JOIN ranked prior ON prior.mapping_id = latest.mapping_id AND prior.rn = 2
            JOIN competitor_product_mappings cpm ON cpm.tenant_id = %(tenant_id)s AND cpm.mapping_id = latest.mapping_id
            JOIN global_competitors gc ON gc.global_competitor_id = cpm.global_competitor_id
            JOIN products p ON p.tenant_id = cpm.tenant_id AND p.product_id = cpm.product_id
            WHERE latest.rn = 1 AND p.deleted_at IS NULL
            ORDER BY latest.observed_at DESC
            LIMIT %(limit)s;
            """,
            {"tenant_id": tenant_id, "limit": limit},
        )
        rows = cursor.fetchall()

    changes = []
    for competitor_name, product_name, latest_price, prior_price, currency, observed_at in rows:
        latest_price = float(latest_price)
        prior_price = float(prior_price)
        change_pct = round((latest_price - prior_price) / prior_price * 100, 1) if prior_price else None
        direction = "unchanged" if not change_pct else ("increase" if change_pct > 0 else "decrease")
        changes.append({
            "competitor_name": competitor_name,
            "product_name": product_name,
            "latest_price": latest_price,
            "prior_price": prior_price,
            "currency": currency,
            "price_change_pct": change_pct,
            "direction": direction,
            "observed_at": observed_at.isoformat(),
        })
    return changes
