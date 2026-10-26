from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.market_scraper import provider_business_staging as staging


class _Cursor:
    def __init__(self, conn):
        self.conn = conn
        self.result = None

    def execute(self, query, params=()):
        self.conn.calls.append((query, params))
        if "keel_provider_business_stage98" in query:
            self.result = (str(uuid4()), 1, False)
        else:
            self.result = None

    def fetchone(self):
        return self.result

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _Connection:
    def __init__(self):
        self.calls = []

    def cursor(self):
        return _Cursor(self)


def _identity(entity, provider_id, *, status="associated"):
    return {"identity_id": str(uuid4()), "entity_type": entity,
            "provider_record_id": provider_id, "mapping_status": status}


def test_shopify_products_orders_and_lines_stage_as_allowlisted_values():
    conn = _Connection()
    product_id = "gid://shopify/Product/1"
    variant_id = "gid://shopify/ProductVariant/2"
    order_id = "gid://shopify/Order/3"
    line_id = "gid://shopify/LineItem/4"
    records = [
        SimpleNamespace(entity_type="product", provider_id=product_id,
                        payload={"title": "Coffee", "billingAddress": {"email": "private@example.test"}}),
        SimpleNamespace(entity_type="variant", provider_id=variant_id,
                        payload={"title": "Whole bean", "sku": "C-1"}),
        SimpleNamespace(entity_type="order", provider_id=order_id, payload={"name": "#1", "test": False}),
        SimpleNamespace(entity_type="line_item", provider_id=line_id, parent_provider_id=order_id,
                        payload={"title": "Coffee", "quantity": 1, "variant": {"id": variant_id,
                                 "product": {"id": product_id}}}),
    ]
    identities = [_identity("product", product_id), _identity("variant", variant_id),
                  _identity("order", order_id), _identity("order_line_item", line_id)]
    result = staging.stage_provider_business_records(
        conn, provider="shopify", source_id=str(uuid4()), ingestion_job_id=str(uuid4()),
        receipt={"receipt_id": str(uuid4()), "worker_id": "worker", "lease_generation": 1},
        configuration_version=1, records=records, identity_rows=identities,
    )
    assert result == {"records_seen": 4, "revisions_created": 4, "duplicates": 0,
                      "invalid": 0, "review_required": 0, "valid": 4}
    staged = [json.loads(call[1][8]) for call in conn.calls]
    assert "billingAddress" not in staged[0]
    assert staged[3]["product_provider_id"] == product_id
    assert all("email" not in json.dumps(value) for value in staged)


def test_ambiguous_identity_and_normalization_findings_remain_review_required():
    conn = _Connection()
    record_id = "gid://shopify/Product/99"
    result = staging.stage_provider_business_records(
        conn, provider="shopify", source_id=str(uuid4()), ingestion_job_id=str(uuid4()),
        receipt={"receipt_id": str(uuid4()), "worker_id": "worker", "lease_generation": 2},
        configuration_version=3,
        records=[SimpleNamespace(entity_type="product", provider_id=record_id, payload={"title": "Possible match"})],
        identity_rows=[_identity("product", record_id, status="pending_review")],
    )
    assert result["review_required"] == 1
    findings = json.loads(conn.calls[0][1][9])
    assert findings == [{"field": "provider_identity", "code": "pending_review"}]


def test_invalid_provider_data_is_saved_as_safe_validation_finding():
    conn = _Connection()
    record_id = 4
    result = staging.stage_provider_business_records(
        conn, provider="woocommerce", source_id=str(uuid4()), ingestion_job_id=str(uuid4()),
        receipt={"receipt_id": str(uuid4()), "worker_id": "worker", "lease_generation": 1},
        configuration_version=1,
        records=[SimpleNamespace(entity_type="order", provider_id=record_id, payload={"refunds": "not-a-list"})],
        identity_rows=[_identity("order", str(record_id))], store_currency="USD",
    )
    assert result["invalid"] == 1
    assert json.loads(conn.calls[0][1][8]) == {}
    assert json.loads(conn.calls[0][1][9]) == [{"field": "record", "code": "provider_record_invalid"}]


def test_missing_m95_identity_blocks_business_record_staging():
    conn = _Connection()
    with pytest.raises(staging.ProviderBusinessStagingError, match="no persisted M95 identity"):
        staging.stage_provider_business_records(
            conn, provider="shopify", source_id=str(uuid4()), ingestion_job_id=str(uuid4()),
            receipt={"receipt_id": str(uuid4()), "worker_id": "worker", "lease_generation": 1},
            configuration_version=1,
            records=[SimpleNamespace(entity_type="product", provider_id="gid://shopify/Product/1", payload={"title": "A"})],
            identity_rows=[],
        )


def test_woocommerce_nested_order_items_stage_as_distinct_provider_records():
    conn = _Connection()
    order = SimpleNamespace(entity_type="order", provider_id=10, payload={
        "status": "processing", "currency": "USD",
        "line_items": [{"id": 11, "name": "Tea", "quantity": 2, "product_id": 5,
                        "variation_id": 0, "total": "8.00"}],
    })
    result = staging.stage_provider_business_records(
        conn, provider="woocommerce", source_id=str(uuid4()), ingestion_job_id=str(uuid4()),
        receipt={"receipt_id": str(uuid4()), "worker_id": "worker", "lease_generation": 1},
        configuration_version=1, records=[order],
        identity_rows=[_identity("order", "10"), _identity("order_line_item", "11")], store_currency="USD",
    )
    assert result["records_seen"] == 2
    assert json.loads(conn.calls[1][1][8])["product_provider_id"] == "5"


def test_woocommerce_line_item_currency_comes_from_parent_order_not_store_default():
    conn = _Connection()
    order = SimpleNamespace(entity_type="order", provider_id=10, payload={
        "status": "processing", "currency": "EUR", "line_items": [
            {"id": 11, "name": "Tea", "quantity": 1, "product_id": 5, "total": "8.00"},
        ],
    })
    staging.stage_provider_business_records(
        conn, provider="woocommerce", source_id=str(uuid4()), ingestion_job_id=str(uuid4()),
        receipt={"receipt_id": str(uuid4()), "worker_id": "worker", "lease_generation": 1},
        configuration_version=1, records=[order],
        identity_rows=[_identity("order", "10"), _identity("order_line_item", "11")], store_currency="CAD",
    )
    assert json.loads(conn.calls[1][1][8])["currency_code"] == "EUR"


def test_real_woo_variation_without_name_uses_only_provider_parent_and_attributes():
    from src.market_scraper.woocommerce import WooRecord
    records=[WooRecord('product',1,{'id':1,'name':'Coffee','type':'variable'}),WooRecord('variation',2,{'id':2,'sku':'C-1KG','price':'15','attributes':[{'name':'Size','option':'1kg'}]},1)]
    staged=staging._records_for_staging('woocommerce',records)
    assert staged[1][2]['name']=='Coffee / 1kg'
    values,findings=staging.normalize_woocommerce_record('variant',staged[1][2],store_currency='USD')
    assert values['title']=='Coffee / 1kg' and values['price']=='15' and findings==[]
