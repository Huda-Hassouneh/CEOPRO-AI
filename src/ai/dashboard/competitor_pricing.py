"""
CEOPRO AI - Dashboard Competitor Price Positioning (presentation layer, not
a new model).

Replaces the mockup's Market Share pie chart: this platform tracks
competitor PRICES, not overall market share, so a price-positioning bar
chart (your price vs. the market average, per product) is the honest
thing to show instead of a number nothing here computes. Same source
query shape as insights/pipeline.py::_load_price_gaps() and rag/
structured_summaries.py::generate_market_pricing_summary() - only the
most recent scraped price per mapped competitor, averaged per product -
extended here with the product name/currency a chart needs to label its
bars, and capped to the biggest gaps so the chart stays readable.
"""
DEFAULT_LIMIT = 10


def get_competitor_price_positioning(conn, tenant_id: str, limit: int = DEFAULT_LIMIT) -> list:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT p.product_id,
                   COALESCE(p.product_name->>'en', p.product_name->>'ar', p.product_name::text) AS product_name,
                   p.current_price, p.currency,
                   AVG(latest.scraped_price) AS avg_competitor_price,
                   COUNT(*) AS competitor_count
            FROM products p
            JOIN competitor_product_mappings cpm ON cpm.tenant_id = p.tenant_id AND cpm.product_id = p.product_id
            JOIN LATERAL (
                SELECT cpr.scraped_price
                FROM competitor_prices cpr
                WHERE cpr.tenant_id = cpm.tenant_id AND cpr.mapping_id = cpm.mapping_id
                ORDER BY cpr.observed_at DESC
                LIMIT 1
            ) latest ON TRUE
            WHERE p.tenant_id = %s AND p.deleted_at IS NULL
            GROUP BY p.product_id, p.product_name, p.current_price, p.currency;
            """,
            (tenant_id,),
        )
        rows = cursor.fetchall()

    positioning = []
    for product_id, product_name, current_price, currency, avg_competitor_price, competitor_count in rows:
        current_price = float(current_price)
        avg_competitor_price = float(avg_competitor_price)
        if avg_competitor_price <= 0:
            continue
        price_gap_pct = round((current_price - avg_competitor_price) / avg_competitor_price * 100, 1)
        positioning.append({
            "product_id": str(product_id),
            "product_name": product_name,
            "currency": currency,
            "your_price": current_price,
            "market_average_price": round(avg_competitor_price, 2),
            "price_gap_pct": price_gap_pct,
            "competitors_compared": int(competitor_count),
        })

    positioning.sort(key=lambda row: abs(row["price_gap_pct"]), reverse=True)
    return positioning[:limit]
