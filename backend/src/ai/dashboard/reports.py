"""
KEEL - Reports (real sales export). Same pure-aggregation/read-layer
style as dashboard/metrics.py and dashboard/financial_summary.py.

Closes a real, previously-unreachable-from-the-UI gap: invoices/
invoice_items have existed since Final_schema.sql, and financial_summary.py
already computes deterministic gross-profit numbers from them for the
Business Copilot's chat answers - but nothing let a tenant see or export
their own line-item sales data directly. `GET /reports/sales` (routers/
reports.py) is the first real read surface for it.

Same cost_price honesty discipline as financial_summary.py: a product's
line_gross_profit is null (never a fabricated 0) whenever that product's
cost_price is unset - never silently treated as free-to-acquire.
"""
import uuid
from datetime import datetime, timezone
from typing import Iterator, Optional

DEFAULT_ROW_LIMIT = 1000
MAX_ROW_LIMIT = 5000
EXPORT_BATCH_SIZE = 2000

_FILTER = """
    ii.tenant_id = %(tenant_id)s
    AND (%(start_date)s::timestamptz IS NULL OR i.issue_date >= %(start_date)s)
    AND (%(end_date)s::timestamptz IS NULL OR i.issue_date < %(end_date)s)
"""

_SELECT = """
    SELECT
        i.invoice_id, i.invoice_number, i.issue_date, i.customer_name,
        i.currency, i.payment_status,
        p.product_id, localized_text(p.product_name),
        ii.quantity, ii.unit_price, ii.total_price, p.cost_price,
        ii.invoice_item_id
    FROM invoice_items ii
    JOIN invoices i ON i.tenant_id = ii.tenant_id AND i.invoice_id = ii.invoice_id
    JOIN products p ON p.tenant_id = ii.tenant_id AND p.product_id = ii.product_id
"""

# Most recent first; the line item id breaks ties so pages never overlap or
# skip rows when several lines share an invoice date.
_ORDER = "ORDER BY i.issue_date DESC, ii.invoice_item_id DESC"


def _row(record) -> dict:
    (invoice_id, invoice_number, issue_date, customer_name, currency, payment_status,
     product_id, product_name, quantity, unit_price, total_price, cost_price, _item_id) = record
    has_cost_data = cost_price is not None
    return {
        "invoice_id": str(invoice_id),
        "invoice_number": invoice_number,
        "issue_date": issue_date.isoformat(),
        "customer_name": customer_name,
        "currency": currency,
        "payment_status": payment_status,
        "product_id": str(product_id),
        "product_name": product_name,
        "quantity": float(quantity),
        "unit_price": float(unit_price),
        "total_price": float(total_price),
        "has_cost_data": has_cost_data,
        "line_gross_profit": float((unit_price - cost_price) * quantity) if has_cost_data else None,
    }


def count_sales_rows(conn, tenant_id: str, start_date: Optional[datetime] = None,
                     end_date: Optional[datetime] = None) -> int:
    with conn.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT COUNT(*)
            FROM invoice_items ii
            JOIN invoices i ON i.tenant_id = ii.tenant_id AND i.invoice_id = ii.invoice_id
            WHERE {_FILTER};
            """,
            {"tenant_id": tenant_id, "start_date": start_date, "end_date": end_date},
        )
        return cursor.fetchone()[0]


def get_sales_report(
    conn, tenant_id: str,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    limit: int = DEFAULT_ROW_LIMIT,
    offset: int = 0,
) -> dict:
    """One page of invoice line items, most recent first: `limit` rows
    (capped at MAX_ROW_LIMIT) starting at `offset`. `total_row_count` is the
    whole period's count, so callers can page through all of it; the full
    period is exported by iter_sales_rows() instead."""
    limit = min(max(limit, 1), MAX_ROW_LIMIT)
    offset = max(offset, 0)
    total_row_count = count_sales_rows(conn, tenant_id, start_date, end_date)
    with conn.cursor() as cursor:
        cursor.execute(
            f"{_SELECT} WHERE {_FILTER} {_ORDER} LIMIT %(limit)s OFFSET %(offset)s;",
            {"tenant_id": tenant_id, "start_date": start_date, "end_date": end_date,
             "limit": limit, "offset": offset},
        )
        report_rows = [_row(record) for record in cursor.fetchall()]

    return {
        "rows": report_rows,
        "returned_row_count": len(report_rows),
        "total_row_count": total_row_count,
        "offset": offset,
        "limit": limit,
        "truncated": offset + len(report_rows) < total_row_count,
        "start_date": start_date.isoformat() if start_date else None,
        "end_date": end_date.isoformat() if end_date else None,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def iter_sales_rows(
    conn, tenant_id: str,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    batch_size: int = EXPORT_BATCH_SIZE,
) -> Iterator[dict]:
    """Every line item in the period, most recent first, streamed from one
    server-side cursor `batch_size` rows at a time, so a large history never
    sits in memory at once. One query, one sort: the order spans two tables,
    so no index can serve it, and the earlier keyset batches re-sorted the
    whole history once per batch (27 sorts for a 53,000-line export)."""
    params = {"tenant_id": tenant_id, "start_date": start_date, "end_date": end_date}
    with conn.cursor(name=f"sales_export_{uuid.uuid4().hex}") as cursor:
        cursor.itersize = batch_size
        cursor.execute(f"{_SELECT} WHERE {_FILTER} {_ORDER};", params)
        for record in cursor:
            yield _row(record)
