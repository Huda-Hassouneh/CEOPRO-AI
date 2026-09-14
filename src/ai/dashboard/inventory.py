"""
CEOPRO AI - Dashboard Inventory Status (presentation layer, not a new
model, no new table - `inventory` already exists in the schema).

The mockup's "Inventory Status" card was previously flagged out of scope
entirely (see metrics.py's own docstring) because the `inventory` table
is not populated by any real ingestion/sales path yet - no CSV/XLSX
import or POS/ERP sync currently writes stock_quantity anywhere. That's
still true, and this module does not change it: it reads the real table
for real, honestly reports "no data yet" (has_data=False) for a tenant
who has never had inventory rows written, and only ever returns a real
percentage/count once real inventory rows exist - never a fabricated
number to fill the card.

in_stock = stock_quantity > 0. low_stock = stock_quantity <= reorder_level
(both real, already-existing columns - reorder_level is a real per-
product threshold set at inventory-row creation, not invented here).
"""


def get_inventory_status(conn, tenant_id: str) -> dict:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                COUNT(*) AS total_products,
                COUNT(*) FILTER (WHERE i.stock_quantity > 0) AS in_stock_count,
                COUNT(*) FILTER (WHERE i.stock_quantity <= i.reorder_level) AS low_stock_count
            FROM inventory i
            JOIN products p ON p.tenant_id = i.tenant_id AND p.product_id = i.product_id
            WHERE i.tenant_id = %s AND p.deleted_at IS NULL;
            """,
            (tenant_id,),
        )
        total_products, in_stock_count, low_stock_count = cursor.fetchone()

    if total_products == 0:
        return {"has_data": False, "in_stock_pct": None, "low_stock_count": None, "tracked_products": 0}

    return {
        "has_data": True,
        "in_stock_pct": round(in_stock_count / total_products * 100, 1),
        "low_stock_count": int(low_stock_count),
        "tracked_products": int(total_products),
    }
