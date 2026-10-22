from decimal import Decimal

import pytest

from src.market_scraper.provider_business_values import (
    ProviderBusinessValueError,
    business_value_fingerprint,
    normalize_shopify_record,
    normalize_woocommerce_record,
)
from src.market_scraper.shopify import PRODUCT_VARIANTS_QUERY, PRODUCTS_QUERY


def test_shopify_variant_preserves_provider_money_and_named_currency():
    values, findings = normalize_shopify_record("variant", {
        "title": "Blue / M", "sku": "B-M", "barcode": "123", "updatedAt": "2026-10-01T00:00:00Z",
        "price": {"amount": "19.9900", "currencyCode": "USD"},
        "compareAtPrice": {"amount": "25.00", "currencyCode": "USD"},
        "inventoryItem": {"tracked": True},
    })
    assert values["price"] == {"amount": "19.9900", "currency_code": "USD", "provider_field": "price"}
    assert values["compare_at_price"]["amount"] == "25.00"
    assert values["inventory_tracked"] is True
    assert findings == []


def test_shopify_order_retains_provider_status_and_distinct_totals():
    values, findings = normalize_shopify_record("order", {
        "name": "#1001", "displayFinancialStatus": "PENDING", "displayFulfillmentStatus": "UNFULFILLED",
        "currencyCode": "EUR", "createdAt": "2026-10-02T10:00:00Z", "updatedAt": "2026-10-03T10:00:00Z",
        "cancelledAt": None, "test": False,
        "totalPriceSet": {"shopMoney": {"amount": "30.00", "currencyCode": "EUR"}},
        "totalTaxSet": {"shopMoney": {"amount": "2.40", "currencyCode": "EUR"}},
        "totalShippingPriceSet": {"shopMoney": {"amount": "4.00", "currencyCode": "EUR"}},
        "totalDiscountsSet": {"shopMoney": {"amount": "1.00", "currencyCode": "EUR"}},
        "billingAddress": {"address1": "must not persist", "email": "private@example.test"},
    })
    assert values["status"] == "PENDING"
    assert values["provider_totals"]["tax"]["amount"] == "2.40"
    assert values["provider_totals"]["shipping"]["amount"] == "4.00"
    assert "billingAddress" not in values and "email" not in str(values)
    assert findings == []


def test_shopify_line_item_keeps_provider_product_and_variant_ids():
    values, findings = normalize_shopify_record("order_line_item", {
        "title": "Blue / M", "quantity": 2, "sku": "B-M",
        "variant": {"id": "gid://shopify/ProductVariant/42", "product": {"id": "gid://shopify/Product/7"}},
        "originalUnitPriceSet": {"shopMoney": {"amount": "12.50", "currencyCode": "USD"}},
        "discountedTotalSet": {"shopMoney": {"amount": "22.00", "currencyCode": "USD"}},
    })
    assert values["product_provider_id"] == "gid://shopify/Product/7"
    assert values["variant_provider_id"] == "gid://shopify/ProductVariant/42"
    assert values["discounted_total"]["amount"] == "22.00"
    assert findings == []


def test_woocommerce_product_holds_fields_not_supported_by_m98_contract():
    values, findings = normalize_woocommerce_record("product", {
        "name": "Coffee", "type": "simple", "sku": "C-1", "price": "15.2500",
        "regular_price": "16.00", "sale_price": "15.2500", "stock_quantity": 91,
        "billing": {"email": "private@example.test"},
    })
    assert values == {"title": "Coffee", "status": None, "created_at": None, "updated_at": None}
    assert {f["field"] for f in findings} == {"sku", "type", "price", "regular_price", "sale_price"}
    assert {f["code"] for f in findings} == {"provider_business_field_not_supported"}
    assert "stock_quantity" not in values
    assert "billing" not in values and "email" not in str(values)


def test_woocommerce_variation_keeps_approved_revision_timestamps():
    values, findings = normalize_woocommerce_record("variant", {
        "name": "Coffee 1kg", "type": "variation", "sku": "C-1-1KG",
        "price": "15.00", "date_created_gmt": "2026-10-20T12:00:00",
        "date_modified_gmt": "2026-10-21T12:00:00",
    }, store_currency="USD")
    assert values["created_at"] == "2026-10-20T12:00:00"
    assert values["updated_at"] == "2026-10-21T12:00:00"
    assert findings == []


def test_woocommerce_order_preserves_status_totals_and_nonpi_refund_reference():
    values, findings = normalize_woocommerce_record("order", {
        "status": "processing", "currency": "GBP", "total": "42.10", "discount_total": "2.00",
        "shipping_total": "4.50", "total_tax": "1.10", "date_created_gmt": "2026-10-10T00:00:00",
        "refunds": [{"id": 33, "total": "-3.00", "reason": "private note"}],
        "billing": {"email": "private@example.test"},
    }, store_currency="GBP")
    assert values["status"] == "processing"
    assert values["provider_totals"]["shipping_total"] == "4.50"
    assert values["refund_references"] == [{"provider_refund_id": "33", "provider_amount": "-3.00"}]
    assert "billing" not in values and "private note" not in str(values)
    assert findings == []


def test_woocommerce_line_items_keep_source_ids_without_customer_fields():
    values, findings = normalize_woocommerce_record("order_line_item", {
        "name": "Tea", "quantity": 1, "sku": "T-1", "product_id": 5, "variation_id": 8,
        "subtotal": "10.00", "total": "9.00", "subtotal_tax": "0.00", "total_tax": "0.00",
        "meta_data": [{"key": "customer_email", "value": "private@example.test"}],
    }, store_currency="CAD")
    assert values["product_provider_id"] == "5"
    assert values["variant_provider_id"] == "8"
    assert values["provider_amounts"]["total"] == "9.00"
    assert "meta_data" not in values and "email" not in str(values)
    assert findings == []


def test_woocommerce_line_item_does_not_infer_historical_currency_from_current_store():
    values, _ = normalize_woocommerce_record(
        "order_line_item", {"name": "Tea", "quantity": 1, "product_id": 5}, store_currency="CAD",
    )
    assert values["currency_code"] is None


@pytest.mark.parametrize("payload", [
    {"name": "x", "price": "NaN"},
    {"name": "x", "price": True},
])
def test_invalid_woocommerce_money_is_rejected(payload):
    with pytest.raises(ProviderBusinessValueError):
        normalize_woocommerce_record("product", payload, store_currency="USD")


def test_fingerprint_is_stable_and_sensitive_to_typed_value_changes():
    values = {"title": "A", "price": Decimal("1.00")}
    assert business_value_fingerprint(values) == business_value_fingerprint({"price": Decimal("1.00"), "title": "A"})
    assert business_value_fingerprint(values) != business_value_fingerprint({"title": "A", "price": Decimal("2.00")})


def test_shopify_product_queries_fetch_provider_variant_price_contract():
    assert "price { amount currencyCode }" in PRODUCTS_QUERY
    assert "compareAtPrice { amount currencyCode }" in PRODUCTS_QUERY
    assert "price { amount currencyCode }" in PRODUCT_VARIANTS_QUERY
    assert "compareAtPrice { amount currencyCode }" in PRODUCT_VARIANTS_QUERY
