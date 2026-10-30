"""
KEEL - Quick Sale (manual sale entry).

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

Also decrements inventory.stock_quantity by the sold quantity in the same
transaction - the whole point of a "Quick Sale" action next to a stock
count is that selling something reduces what's left, and a sale that left
stock_quantity untouched would make that column actively misleading right
after the action that's supposed to explain a change in it. When a
product HAS a tracked stock count, a sale that would take it negative is
rejected outright (InsufficientStockError) rather than silently floored -
stock is authoritative once it exists, so overselling past it is a real
error, not a data-drift footnote. A product with no inventory row at all
is untouched and unblocked either way, consistent with this codebase's
existing rule of never fabricating a stock number that was never actually
set (see products.py's stock_quantity=None handling) - untracked stock is
not the same thing as zero stock.

The inventory row (when one exists) is locked with SELECT ... FOR UPDATE
before the check, so two concurrent quick sales against the same product
can't both read the same stock_quantity and both pass the check - the
second sale's lock acquisition blocks until the first one's transaction
commits or rolls back, the same real serialization guarantee an ordinary
bank-account-balance check would need.

unit_price defaults to the product's own current_price when the caller
doesn't override it - the common case ("I sold one at the listed price")
without forcing every call to repeat a number the product record already
has. payment_status is always 'PAID': a quick sale records a completed,
already-paid transaction at the point of entry, not a pending invoice to
collect on later (that's what the full invoicing flow, if/when built,
would be for).
"""
import uuid
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from src.ai.core.quantities import Number, as_quantity, format_quantity

_FOUR_DP = Decimal("0.0001")


class ProductNotFoundError(Exception):
    """Raised when product_id doesn't resolve to a real, active product
    for this tenant - never silently record a sale against nothing."""


class InsufficientStockError(Exception):
    """Raised when quantity exceeds a product's own tracked stock_quantity.
    Never raised for a product with no inventory row at all - that means
    stock isn't tracked for it, not that it's zero."""


def record_quick_sale(
    conn, tenant_id: str, user_id: Optional[str], product_id: str,
    quantity: Number, unit_price: Optional[Number] = None,
) -> dict:
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT localized_text(product_name), current_price, currency "
            "FROM products WHERE tenant_id = %s AND product_id = %s AND deleted_at IS NULL;",
            (tenant_id, product_id),
        )
        product_row = cursor.fetchone()
        if product_row is None:
            raise ProductNotFoundError(f"No active product {product_id} for this tenant.")
        product_name, current_price, currency = product_row

        cursor.execute(
            "SELECT stock_quantity FROM inventory WHERE tenant_id = %s AND product_id = %s FOR UPDATE;",
            (tenant_id, product_id),
        )
        inventory_row = cursor.fetchone()
        quantity = Decimal(str(quantity)).quantize(_FOUR_DP)
        if inventory_row is not None and quantity > inventory_row[0]:
            raise InsufficientStockError(
                f"Only {format_quantity(inventory_row[0])} unit(s) of {product_name} in stock; "
                f"cannot sell {format_quantity(quantity)}."
            )

        # Preserve the existing 4-dp paid total and record its exact residual
        # separately to satisfy invoice_items' accounting equality.
        resolved_unit_price = Decimal(str(unit_price if unit_price is not None else current_price)).quantize(_FOUR_DP)
        total = (quantity * resolved_unit_price).quantize(_FOUR_DP, rounding=ROUND_HALF_UP)
        invoice_id = str(uuid.uuid4())
        invoice_number = f"QS-{uuid.uuid4().hex[:10].upper()}"

        cursor.execute(
            "INSERT INTO invoices (invoice_id, tenant_id, invoice_number, subtotal, total_amount, "
            "currency, payment_status, created_by_user_id) "
            "VALUES (%s, %s, %s, %s, %s, %s, 'PAID', %s);",
            (invoice_id, tenant_id, invoice_number, total, total, currency, user_id),
        )
        cursor.execute(
            "INSERT INTO invoice_items (tenant_id, invoice_id, product_id, quantity, unit_price, total_price, rounding_adjustment) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s);",
            (tenant_id, invoice_id, product_id, quantity, resolved_unit_price, total, total - quantity * resolved_unit_price),
        )
        if inventory_row is not None:
            cursor.execute(
                "UPDATE inventory SET stock_quantity = stock_quantity - %s, updated_at = NOW() "
                "WHERE tenant_id = %s AND product_id = %s;",
                (quantity, tenant_id, product_id),
            )

    return {
        "invoice_id": invoice_id,
        "invoice_number": invoice_number,
        "product_id": product_id,
        "product_name": product_name,
        "quantity": as_quantity(quantity),
        "unit_price": float(resolved_unit_price),
        "total_amount": float(total),
        "currency": currency,
    }
