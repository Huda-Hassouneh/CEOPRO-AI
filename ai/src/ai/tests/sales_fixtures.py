"""Test helper: record a sale the way imports and Quick Sale do (an invoice
with one line), so every screen and the forecasts see it."""
import uuid


def insert_sale(cursor, tenant_id, product_id, quantity, unit_price, when, currency="JOD"):
    invoice_id = str(uuid.uuid4())
    total = float(quantity) * float(unit_price)
    cursor.execute(
        "INSERT INTO invoices (invoice_id, tenant_id, invoice_number, issue_date, subtotal, total_amount, currency, payment_status) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, 'PAID');",
        (invoice_id, tenant_id, f"T-{invoice_id[:12]}", when, total, total, currency),
    )
    cursor.execute(
        "INSERT INTO invoice_items (tenant_id, invoice_id, product_id, quantity, unit_price, total_price) VALUES (%s, %s, %s, %s, %s, %s);",
        (tenant_id, invoice_id, product_id, quantity, unit_price, total),
    )
