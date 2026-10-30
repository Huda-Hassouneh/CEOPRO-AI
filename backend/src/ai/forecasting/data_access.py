"""
KEEL - Demand Forecasting Data Access.
Reads daily aggregated demand history and product context. Read-only against
tables owned by other services (transactions, products, inventory); this module
never writes outside forecasting's own tables (handled in evidence.py).
"""

from datetime import date, datetime, timedelta, timezone
from typing import Optional

import pandas as pd
import psycopg2
from src.ai.core.business_time import business_today


def load_daily_demand(
    conn: "psycopg2.extensions.connection", tenant_id: str, product_id: str, through: Optional[date] = None,
) -> pd.DataFrame:
    """
    Returns a daily-indexed DataFrame with columns [date, quantity, avg_unit_price],
    aggregated from invoices/invoice_items - the sales record every screen
    reads, which includes imported sales and sales recorded in the app (the
    `transactions` table only ever held imported rows). Days with zero sales are filled with quantity=0
    so the series has no implicit gaps (required for lag/rolling features and for
    walk-forward validation to see a true daily cadence).

    `through` (default: yesterday, UTC) extends the series past the last sale
    with zero-sales days. Found in acceptance testing: the series used to end
    at the product's LAST SALE, so a Ramadan-only item last sold in March was
    forecast "for March" at Ramadan demand, and a discontinued product kept a
    healthy forecast forever. Today itself is excluded - it isn't over yet.
    """
    through = through or (business_today(conn) - timedelta(days=1))
    query = """
        SELECT
            i.issue_date::date AS sale_date,
            SUM(ii.quantity) AS quantity,
            AVG(ii.unit_price) AS avg_unit_price
        FROM invoice_items ii
        JOIN invoices i ON i.tenant_id = ii.tenant_id AND i.invoice_id = ii.invoice_id
        WHERE ii.tenant_id = %s AND ii.product_id = %s
          AND i.payment_status <> 'CANCELLED'
        GROUP BY i.issue_date::date
        ORDER BY sale_date;
    """
    with conn.cursor() as cursor:
        cursor.execute(query, (tenant_id, product_id))
        rows = cursor.fetchall()

    if not rows:
        return pd.DataFrame(columns=["date", "quantity", "avg_unit_price"])

    raw = pd.DataFrame(rows, columns=["date", "quantity", "avg_unit_price"])
    raw["date"] = pd.to_datetime(raw["date"])

    end = max(raw["date"].max(), pd.Timestamp(through))
    full_index = pd.date_range(start=raw["date"].min(), end=end, freq="D")
    daily = raw.set_index("date").reindex(full_index)
    daily.index.name = "date"

    # SUM(numeric) arrives as Decimal; the feature pipeline needs floats.
    daily["quantity"] = daily["quantity"].astype(float).fillna(0.0)
    daily["avg_unit_price"] = daily["avg_unit_price"].ffill().bfill()

    return daily.reset_index()


def load_product_context(conn: "psycopg2.extensions.connection", tenant_id: str, product_id: str) -> Optional[dict]:
    """
    Returns static product/inventory context used as constant features.
    Inventory only tracks current_stock (no history), so this is necessarily a
    snapshot, not a time-varying signal.
    """
    query = """
        SELECT p.current_price, p.category, i.stock_quantity, c.country_code
        FROM products p
        JOIN companies c ON c.tenant_id = p.tenant_id
        LEFT JOIN inventory i ON i.tenant_id = p.tenant_id AND i.product_id = p.product_id
        WHERE p.tenant_id = %s AND p.product_id = %s AND p.deleted_at IS NULL;
    """
    with conn.cursor() as cursor:
        cursor.execute(query, (tenant_id, product_id))
        row = cursor.fetchone()

    if not row:
        return None

    return {
        "current_price": float(row[0]) if row[0] is not None else None,
        "category": row[1],
        "current_stock": float(row[2]) if row[2] is not None else None,
        "country_code": row[3],
    }
