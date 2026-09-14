"""
CEOPRO AI - Dashboard Unified Search (presentation layer, not a new
model, no new table).

The top-bar "Search products, competitors, insights..." box. Products
and tracked competitors are real, name-searchable rows this platform
already has (products.product_name, global_competitors.competitor_name)
- a plain case-insensitive substring match over both, unioned into one
result list labeled by type. "Insights" are deliberately NOT included:
insights/cross_signal.py's findings are computed fresh per request, not
stored as searchable rows anywhere - indexing them would mean either a
new table (out of scope here) or running full insight detection on
every keystroke, neither of which this endpoint does.
"""
DEFAULT_LIMIT = 10


def search(conn, tenant_id: str, query_text: str, limit: int = DEFAULT_LIMIT) -> dict:
    query_text = (query_text or "").strip()
    if not query_text:
        return {"products": [], "competitors": []}

    like_pattern = f"%{query_text}%"

    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT product_id, COALESCE(product_name->>'en', product_name->>'ar', product_name::text) AS name
            FROM products
            WHERE tenant_id = %s AND deleted_at IS NULL
              AND (product_name->>'en' ILIKE %s OR product_name->>'ar' ILIKE %s)
            ORDER BY name ASC
            LIMIT %s;
            """,
            (tenant_id, like_pattern, like_pattern, limit),
        )
        product_rows = cursor.fetchall()

        cursor.execute(
            """
            SELECT gc.global_competitor_id, gc.competitor_name, gc.website_url
            FROM tenant_competitors tc
            JOIN global_competitors gc ON gc.global_competitor_id = tc.global_competitor_id
            WHERE tc.tenant_id = %s AND tc.is_tracked = TRUE AND gc.competitor_name ILIKE %s
            ORDER BY gc.competitor_name ASC
            LIMIT %s;
            """,
            (tenant_id, like_pattern, limit),
        )
        competitor_rows = cursor.fetchall()

    return {
        "products": [{"product_id": str(pid), "name": name} for pid, name in product_rows],
        "competitors": [
            {"global_competitor_id": str(cid), "name": name, "website_url": website_url}
            for cid, name, website_url in competitor_rows
        ],
    }
