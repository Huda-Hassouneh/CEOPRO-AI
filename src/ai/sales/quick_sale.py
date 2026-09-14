"""
CEOPRO AI - Quick Sale (manual sale entry).

The mockup's "Quick Sale" action was previously flagged as unsupported
entirely - there was genuinely no write path into invoices/invoice_items
anywhere in this codebase. That table pair is real and already read by
several modules (insights/pipeline.py calls it "the platform's real
internal sales record"; dashboard/metrics.py's Revenue/Sales/Growth cards
and dashboard/forecast_detail.py's average-daily-demand both read it) -
uploaded/synced sales instead land in the separate `transactions` table
(src/ai/extraction/promotion.py, src/market_scraper's connector sync).
invoices/invoice_items was always the intended MANUAL entry path; nothing
had ever been built to actually write to it. This closes that real gap
with the smallest honest write: one invoice + one invoice_item per quick
sale, no new tables, no new columns.

unit_price defaults to the product's own current_price when the caller
doesn't override it - the common case ("I sold one at the listed price")
without forcing every call to repeat a number the product record already
has. payment_status is always 'PAID': a quick sale records a completed,
already-paid transaction at the point of entry, not a pending invoice to
collect on later (that's what the full invoicing flow, if/when built,
would be for).
"""
import uuid
from typing import Optional


class ProductNotFoundError(Exception):
    """Raised when product_id doesn't resolve to a real, active product
    for this tenant - never silently record a sale against nothing."""


def record_quick_sale(
    conn, tenant_id: str, user_id: Optional[str], product_id: str,
    quantity: int, unit_price: Optional[float] = None,
) -> dict:
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT COALESCE(product_name->>'en', product_name->>'ar', product_name::text), current_price, currency "
            "FROM products WHERE tenant_id = %s AND product_id = %s AND deleted_at IS NULL;",
            (tenant_id, product_id),
        )
        product_row = cursor.fetchone()
        if product_row is None:
            raise ProductNotFoundError(f"No active product {product_id} for this tenant.")
        product_name, current_price, currency = product_row

        resolved_unit_price = float(unit_price) if unit_price is not None else float(current_price)
        total = round(resolved_unit_price * quantity, 4)
        invoice_id = str(uuid.uuid4())
        invoice_number = f"QS-{uuid.uuid4().hex[:10].upper()}"

        cursor.execute(
            "INSERT INTO invoices (invoice_id, tenant_id, invoice_number, subtotal, total_amount, "
            "currency, payment_status, created_by_user_id) "
            "VALUES (%s, %s, %s, %s, %s, %s, 'PAID', %s);",
            (invoice_id, tenant_id, invoice_number, total, total, currency, user_id),
        )
        cursor.execute(
            "INSERT INTO invoice_items (tenant_id, invoice_id, product_id, quantity, unit_price, total_price) "
            "VALUES (%s, %s, %s, %s, %s, %s);",
            (tenant_id, invoice_id, product_id, quantity, resolved_unit_price, total),
        )

    return {
        "invoice_id": invoice_id,
        "invoice_number": invoice_number,
        "product_id": product_id,
        "product_name": product_name,
        "quantity": quantity,
        "unit_price": resolved_unit_price,
        "total_amount": total,
        "currency": currency,
    }
