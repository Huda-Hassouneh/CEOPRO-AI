from src.ai.extraction.typed_imports import TypedImportError, validate_typed_import_row


def test_sales_row_allowlists_fields_and_normalizes_types():
    row = validate_typed_import_row("sales", {"product_name":"Olive Oil","quantity":"2.5","unit_price":"3.20",
        "currency":"jod","transaction_date":"2026-10-20","email":"private"}, source_row_key="row:1")
    assert row["validation_outcome"] == "valid"
    assert row["typed_values"] == {"product_name":"Olive Oil","quantity":"2.5","unit_price":"3.20","currency":"JOD","transaction_date":"2026-10-20"}


def test_invoice_provider_product_id_is_held_for_review():
    row = validate_typed_import_row("invoice", {"invoice_id":"INV-A","invoice_date":"2026-10-20","currency":"USD",
        "provider_product_id":"gid://shopify/Product/4","quantity":1,"unit_price":8}, source_row_key="line:1")
    assert row["validation_outcome"] == "review_required"
    assert row["ambiguity_code"] == "provider_identity_requires_review"


def test_inventory_bad_quantity_and_unresolved_location_are_retained():
    row = validate_typed_import_row("inventory", {"provider_product_id":"gid://shopify/ProductVariant/9",
        "provider_location_id":"gid://shopify/Location/2","quantity":-2,"quantity_semantics":"available",
        "observed_at":"2026-10-20T12:00:00Z"}, source_row_key="stock:9")
    assert row["validation_outcome"] == "invalid"
    assert {finding["field"] for finding in row["validation_findings"]} == {"product_reference","quantity","location_id"}


def test_invalid_money_currency_and_date_findings():
    row = validate_typed_import_row("sales", {"product_name":"x","quantity":0,"unit_price":"bad",
        "currency":"US","transaction_date":"20/10/2026"}, source_row_key="row:bad")
    assert row["validation_outcome"] == "invalid"
    assert {finding["field"] for finding in row["validation_findings"]} == {"quantity","unit_price","currency","transaction_date"}


def test_unknown_category_has_no_invented_contract():
    try:
        validate_typed_import_row("refund", {}, source_row_key="1")
    except TypedImportError:
        return
    raise AssertionError("unknown import category must be rejected")
