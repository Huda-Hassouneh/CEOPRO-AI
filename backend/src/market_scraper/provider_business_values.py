"""PII-minimized, provider-specific business-value normalization.

These functions prepare read-only Shopify and WooCommerce records for typed
staging. They preserve provider semantics and do not post canonical data.
"""
from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping


class ProviderBusinessValueError(ValueError):
    """The provider record cannot be safely represented as a typed draft."""


_MAX_TEXT = 2048


def _text(value: Any, field: str, *, required: bool = False, limit: int = _MAX_TEXT) -> str | None:
    if value is None:
        if required:
            raise ProviderBusinessValueError(f"{field} is required")
        return None
    if not isinstance(value, str) or len(value) > limit or any(ord(ch) < 32 and ch not in "\t\n\r" for ch in value):
        raise ProviderBusinessValueError(f"{field} is invalid")
    value = value.strip()
    if required and not value:
        raise ProviderBusinessValueError(f"{field} is required")
    return value or None


def _money(value: Any, field: str, currency: Any = None) -> dict[str, str | None] | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        amount = value.get("amount")
        code = value.get("currencyCode") or value.get("currency") or currency
    else:
        amount, code = value, currency
    if isinstance(amount, bool) or not isinstance(amount, (str, int, Decimal)):
        raise ProviderBusinessValueError(f"{field} amount is invalid")
    try:
        amount_text = format(Decimal(str(amount)), "f")
    except (InvalidOperation, ValueError):
        raise ProviderBusinessValueError(f"{field} amount is invalid") from None
    if not Decimal(amount_text).is_finite() or len(amount_text) > 64:
        raise ProviderBusinessValueError(f"{field} amount is invalid")
    if code is not None and (not isinstance(code, str) or len(code) != 3 or not code.isalpha() or not code.isupper()):
        raise ProviderBusinessValueError(f"{field} currency is invalid")
    return {"amount": amount_text, "currency_code": code, "provider_field": field}


def _shop_money(value: Any, field: str) -> dict[str, str | None] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ProviderBusinessValueError(f"{field} is invalid")
    shop_money = value.get("shopMoney")
    return _money(shop_money, field) if shop_money is not None else None


def _decimal_text(value: Any, field: str, *, required: bool = False) -> str | None:
    if value is None:
        if required:
            raise ProviderBusinessValueError(f"{field} is required")
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise ProviderBusinessValueError(f"{field} is invalid")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ProviderBusinessValueError(f"{field} is invalid") from None
    if not number.is_finite() or len(format(number, "f")) > 64:
        raise ProviderBusinessValueError(f"{field} is invalid")
    return format(number, "f")


def _currency_code(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) != 3 or not value.isalpha() or not value.isupper():
        raise ProviderBusinessValueError(f"{field} is invalid")
    return value


def _findings_for_identity(entity_type: str, values: dict[str, Any]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    if entity_type in {"product", "variant"} and not values.get("title"):
        findings.append({"field": "title", "code": "provider_title_missing"})
    if entity_type == "order_line_item" and values.get("product_provider_id") is None:
        findings.append({"field": "product_provider_id", "code": "product_identity_unavailable"})
    if entity_type == "order_line_item" and values.get("variant_provider_id") is not None and values.get("product_provider_id") is None:
        findings.append({"field": "variant_provider_id", "code": "variant_parent_identity_unavailable"})
    return findings


def normalize_shopify_record(entity_type: str, payload: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Return safe typed values for one Shopify product/order identity."""
    if not isinstance(payload, Mapping):
        raise ProviderBusinessValueError("Shopify provider record is invalid")
    values: dict[str, Any]
    if entity_type == "product":
        values = {"title": _text(payload.get("title"), "title", required=True),
                  "handle": _text(payload.get("handle"), "handle"),
                  "status": _text(payload.get("status"), "status", limit=80),
                  "vendor": _text(payload.get("vendor"), "vendor", limit=300),
                  "created_at": _text(payload.get("createdAt"), "createdAt", limit=100),
                  "updated_at": _text(payload.get("updatedAt"), "updatedAt", limit=100)}
    elif entity_type == "variant":
        price = payload.get("price")
        compare = payload.get("compareAtPrice")
        values = {"title": _text(payload.get("title"), "title", required=True),
                  "sku": _text(payload.get("sku"), "sku", limit=255),
                  "barcode": _text(payload.get("barcode"), "barcode", limit=255),
                  "price": _money(price, "price") if price is not None else None,
                  "compare_at_price": _money(compare, "compareAtPrice") if compare is not None else None,
                  "inventory_tracked": payload.get("inventoryItem", {}).get("tracked")
                      if isinstance(payload.get("inventoryItem"), Mapping) else None,
                  "updated_at": _text(payload.get("updatedAt"), "updatedAt", limit=100)}
        if values["inventory_tracked"] is not None and not isinstance(values["inventory_tracked"], bool):
            raise ProviderBusinessValueError("inventory tracked flag is invalid")
    elif entity_type == "order":
        currency = _currency_code(payload.get("currencyCode"), "currencyCode")
        totals = {key: _shop_money(payload.get(provider_key), provider_key) for key, provider_key in (
            ("total", "totalPriceSet"), ("tax", "totalTaxSet"),
            ("shipping", "totalShippingPriceSet"), ("discounts", "totalDiscountsSet"))}
        values = {"name": _text(payload.get("name"), "name", limit=255),
                  "status": _text(payload.get("displayFinancialStatus"), "displayFinancialStatus", limit=80),
                  "fulfillment_status": _text(payload.get("displayFulfillmentStatus"), "displayFulfillmentStatus", limit=80),
                  "cancelled_at": _text(payload.get("cancelledAt"), "cancelledAt", limit=100),
                  "test_order": payload.get("test") if isinstance(payload.get("test"), bool) else None,
                  "currency_code": currency, "provider_totals": totals,
                  "created_at": _text(payload.get("createdAt"), "createdAt", limit=100),
                  "updated_at": _text(payload.get("updatedAt"), "updatedAt", limit=100)}
    elif entity_type == "order_line_item":
        variant = payload.get("variant") if isinstance(payload.get("variant"), Mapping) else {}
        product = variant.get("product") if isinstance(variant.get("product"), Mapping) else {}
        quantity = payload.get("quantity")
        if isinstance(quantity, bool) or not isinstance(quantity, int):
            raise ProviderBusinessValueError("line item quantity is invalid")
        values = {"title": _text(payload.get("title"), "title", limit=500), "quantity": quantity,
                  "sku": _text(payload.get("sku"), "sku", limit=255),
                  "product_provider_id": _text(product.get("id"), "product id", limit=255),
                  "variant_provider_id": _text(variant.get("id"), "variant id", limit=255),
                  "original_unit_price": _shop_money(payload.get("originalUnitPriceSet"), "originalUnitPriceSet"),
                  "discounted_total": _shop_money(payload.get("discountedTotalSet"), "discountedTotalSet")}
    else:
        raise ProviderBusinessValueError("unsupported Shopify provider record type")
    return values, _findings_for_identity(entity_type, values)


def normalize_woocommerce_record(entity_type: str, payload: Mapping[str, Any], *, store_currency: str | None = None) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Return allowlisted WooCommerce REST values; never retain whole payloads."""
    if not isinstance(payload, Mapping):
        raise ProviderBusinessValueError("WooCommerce provider record is invalid")
    currency = _currency_code(store_currency, "store currency")
    values: dict[str, Any]
    if entity_type in {"product", "variant"}:
        values = {"title": _text(payload.get("name"), "name", required=True),
                  "status": _text(payload.get("status"), "status", limit=80),
                  "sku": _text(payload.get("sku"), "sku", limit=255),
                  "barcode": _text(payload.get("global_unique_id"), "global_unique_id", limit=255),
                  "product_type": _text(payload.get("type"), "type", limit=80),
                  "price": _decimal_text(payload.get("price"), "price"),
                  "regular_price": _decimal_text(payload.get("regular_price"), "regular_price"),
                  "sale_price": _decimal_text(payload.get("sale_price"), "sale_price"),
                  "currency_code": currency,
                  "created_at": _text(payload.get("date_created_gmt") or payload.get("date_created"), "date_created", limit=100),
                  "updated_at": _text(payload.get("date_modified_gmt") or payload.get("date_modified"), "date_modified", limit=100)}
        if any(v is not None for v in (values["price"], values["regular_price"], values["sale_price"])) and currency is None:
            return values, [{"field": "currency_code", "code": "store_currency_unavailable"}]
    elif entity_type == "order":
        refunds = payload.get("refunds") or []
        if not isinstance(refunds, list):
            raise ProviderBusinessValueError("order refunds are invalid")
        safe_refunds = []
        for refund in refunds:
            if not isinstance(refund, Mapping):
                raise ProviderBusinessValueError("order refund reference is invalid")
            safe_refunds.append({"provider_refund_id": _text(str(refund.get("id")) if refund.get("id") is not None else None,
                                                              "refund id", limit=40),
                                 "provider_amount": _decimal_text(refund.get("total"), "refund total")})
        values = {"status": _text(payload.get("status"), "status", limit=80),
                  "currency_code": currency or _currency_code(payload.get("currency"), "currency"),
                  "provider_totals": {key: _decimal_text(payload.get(provider_key), provider_key) for key, provider_key in (
                      ("total", "total"), ("discount_total", "discount_total"),
                      ("shipping_total", "shipping_total"), ("tax_total", "total_tax"))},
                  "created_at": _text(payload.get("date_created_gmt") or payload.get("date_created"), "date_created", limit=100),
                  "updated_at": _text(payload.get("date_modified_gmt") or payload.get("date_modified"), "date_modified", limit=100),
                  "refund_references": safe_refunds}
    elif entity_type == "order_line_item":
        quantity = payload.get("quantity")
        if isinstance(quantity, bool) or not isinstance(quantity, int):
            raise ProviderBusinessValueError("line item quantity is invalid")
        values = {"title": _text(payload.get("name"), "name", limit=500), "quantity": quantity,
                  "sku": _text(payload.get("sku"), "sku", limit=255),
                  "product_provider_id": _text(str(payload.get("product_id")) if payload.get("product_id") else None,
                                                "product id", limit=40),
                  "variant_provider_id": _text(str(payload.get("variation_id")) if payload.get("variation_id") else None,
                                                "variation id", limit=40),
                  "provider_amounts": {key: _decimal_text(payload.get(provider_key), provider_key) for key, provider_key in (
                      ("subtotal", "subtotal"), ("total", "total"),
                      ("subtotal_tax", "subtotal_tax"), ("total_tax", "total_tax"))},
                  "currency_code": currency}
    else:
        raise ProviderBusinessValueError("unsupported WooCommerce provider record type")
    return values, _findings_for_identity(entity_type, values)


def business_value_fingerprint(values: Mapping[str, Any]) -> str:
    """Stable content identity for exact replay suppression."""
    material = json.dumps(values, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")
    return hashlib.sha256(material).hexdigest()
