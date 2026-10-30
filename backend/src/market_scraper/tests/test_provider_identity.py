"""Native restricted-role tests for migration 95 provider record identity."""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse, urlunparse

import psycopg2
import pytest

from src.market_scraper.provider_identity import (
    ProviderIdentityError,
    associate_provider_record,
    persist_shopify_records,
    persist_woocommerce_records,
)
from src.market_scraper.shopify import ShopifyRecord
from src.market_scraper.woocommerce import WooRecord

ADMIN_URL = os.getenv("AI_TEST_DATABASE_URL")
APP_PASSWORD = os.getenv("APP_DB_PASSWORD")
pytestmark = pytest.mark.skipif(not ADMIN_URL or not APP_PASSWORD,
                                reason="AI_TEST_DATABASE_URL and APP_DB_PASSWORD are required for native identity tests")


def _connect_app(tenant, actor):
    parsed = urlparse(ADMIN_URL)
    app_url = urlunparse(parsed._replace(netloc=f"ceopro_app:{APP_PASSWORD}@{parsed.hostname}:{parsed.port}"))
    conn = psycopg2.connect(app_url)
    with conn.cursor() as cur:
        # Session context survives helper commits, matching the request-scoped
        # context installed by the existing authenticated DB connection layer.
        cur.execute("SELECT set_config('app.current_tenant_id',%s,false)", (tenant,))
        cur.execute("SELECT set_config('app.current_user_id',%s,false)", (actor,))
    return conn


def _seed(provider="shopify", second_source=False):
    admin = psycopg2.connect(ADMIN_URL)
    admin.autocommit = True
    tenant, actor, staff, source, canonical = (str(uuid.uuid4()) for _ in range(5))
    sources = [source]
    with admin.cursor() as cur:
        cur.execute("ALTER ROLE ceopro_app WITH PASSWORD %s", (APP_PASSWORD,))
        cur.execute("INSERT INTO companies(tenant_id,business_name,country_code,primary_currency) VALUES(%s,'M95 test','JO','JOD')", (tenant,))
        cur.execute("INSERT INTO users(user_id,email,password_hash,full_name) VALUES(%s,%s,'x','owner')", (actor, f"m95-{actor}@example.test"))
        cur.execute("INSERT INTO users(user_id,email,password_hash,full_name) VALUES(%s,%s,'x','staff')", (staff, f"m95-{staff}@example.test"))
        cur.execute("INSERT INTO tenant_users(tenant_id,user_id,role_key) VALUES(%s,%s,'owner'),(%s,%s,'staff')", (tenant, actor, tenant, staff))
        cur.execute("INSERT INTO products(product_id,tenant_id,product_name,current_price,currency) VALUES(%s,%s,'{\"en\":\"Canonical\"}'::jsonb,10,'JOD')", (canonical, tenant))
        if second_source:
            sources.append(str(uuid.uuid4()))
        for index, source_id in enumerate(sources):
            collector = provider
            domain = f"store{index}-{tenant[:8]}.myshopify.com" if provider == "shopify" else f"https://store{index}.example.test"
            store_id = f"gid://shopify/Shop/{uuid.uuid4().int % 1000000000 + 1}" if provider == "shopify" else str(9000 + index)
            provenance = "shopify_authenticated_shop_query" if provider == "shopify" else "woocommerce_authenticated_store_identity"
            cur.execute("INSERT INTO data_sources(source_id,tenant_id,source_name,source_type,collector_key,collector_config,is_active) VALUES(%s,%s,%s,'OWN_SYSTEM_CONNECTOR',%s,'{}',true)", (source_id, tenant, f"store-{index}", collector))
            cur.execute("INSERT INTO keel_provider_sources(tenant_id,source_id,provider,verified_store_id,verified_store_domain,identity_provenance,verified_at,verified_by_user_id) VALUES(%s,%s,%s,%s,%s,%s,now(),%s)", (tenant, source_id, provider, store_id, domain, provenance, actor))
    admin.close()
    return {"tenant": tenant, "actor": actor, "staff": staff, "source": source, "sources": sources,
            "canonical": canonical}


def _shopify_records(product_id="gid://shopify/Product/100", order_id="gid://shopify/Order/300"):
    updated = "2026-10-20T12:00:00Z"
    variant_id = "gid://shopify/ProductVariant/200"
    return [
        ShopifyRecord("product", product_id, {"id": product_id, "title": "private catalog title", "updatedAt": updated, "sku": "SHARED-SKU"}),
        ShopifyRecord("variant", variant_id, {"id": variant_id, "title": "variant", "updatedAt": updated}, product_id),
        ShopifyRecord("order", order_id, {"id": order_id, "updatedAt": updated, "email": "private@example.test"}),
        ShopifyRecord("line_item", "gid://shopify/LineItem/400", {"id": "gid://shopify/LineItem/400", "quantity": 2,
                     "variant": {"id": variant_id, "product": {"id": product_id}}, "title": "private line"}, order_id),
    ]


def test_restricted_role_observes_source_scoped_product_variant_order_line_and_no_canonical_write():
    seed = _seed()
    conn = _connect_app(seed["tenant"], seed["actor"])
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT current_user,rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user")
            assert cur.fetchone() == ("ceopro_app", False, False)
            cur.execute("SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid='public.keel_provider_record_identities'::regclass")
            assert cur.fetchone() == (True, True)
        results = persist_shopify_records(conn, seed["source"], _shopify_records())
        conn.commit()
        assert [r["entity_type"] for r in results] == ["product", "variant", "order", "order_line_item"]
        assert all(r["mapping_status"] == "pending_review" for r in results)
        with conn.cursor() as cur:
            cur.execute("SELECT entity_type,provider_record_id,parent_identity_id,related_product_provider_id,related_variant_provider_id,mapping_status,canonical_product_id FROM keel_provider_record_identities WHERE tenant_id=%s ORDER BY entity_type", (seed["tenant"],))
            rows = cur.fetchall()
            assert len(rows) == 4
            line = next(row for row in rows if row[0] == "order_line_item")
            assert line[3:] == ("gid://shopify/Product/100", "gid://shopify/ProductVariant/200", "pending_review", None)
            cur.execute("SELECT count(*) FROM keel_provider_record_revisions WHERE tenant_id=%s", (seed["tenant"],))
            assert cur.fetchone()[0] == 4
            cur.execute("SELECT current_price FROM products WHERE tenant_id=%s AND product_id=%s", (seed["tenant"], seed["canonical"]))
            assert str(cur.fetchone()[0]) == "10.0000"
            cur.execute("SELECT count(*) FROM keel_provider_record_identities WHERE tenant_id=%s AND provider_record_id='gid://shopify/Product/100'", (str(uuid.uuid4()),))
            assert cur.fetchone()[0] == 0
            with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                cur.execute("INSERT INTO keel_provider_record_identities(tenant_id,source_id,provider,entity_type,provider_record_id,current_revision_sha256) VALUES(%s,%s,'shopify','product','gid://shopify/Product/999',%s)", (seed["tenant"], seed["source"], "a"*64))
            conn.rollback()
    finally:
        conn.close()


def test_same_provider_id_in_two_verified_stores_is_distinct_and_concurrent_retry_is_idempotent():
    seed = _seed(second_source=True)
    def persist(source):
        c = _connect_app(seed["tenant"], seed["actor"])
        try:
            out = persist_shopify_records(c, source, [ShopifyRecord("product", "gid://shopify/Product/777", {"id":"gid://shopify/Product/777","updatedAt":"2026-10-20T12:00:00Z","sku":"SAME"})])
            c.commit()
            return out[0]
        finally:
            c.close()
    first = persist(seed["sources"][0])
    second = persist(seed["sources"][1])
    assert first["identity_id"] != second["identity_id"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        raced = list(pool.map(lambda _: persist(seed["sources"][0]), range(2)))
    assert raced[0]["identity_id"] == raced[1]["identity_id"] == first["identity_id"]
    assert sum(item["duplicate"] for item in raced) >= 1
    c = _connect_app(seed["tenant"], seed["actor"])
    with c.cursor() as cur:
        cur.execute("SELECT count(DISTINCT source_id),count(*) FROM keel_provider_record_identities WHERE tenant_id=%s AND provider='shopify' AND entity_type='product' AND provider_record_id='gid://shopify/Product/777'", (seed["tenant"],))
        assert cur.fetchone() == (2,2)
        cur.execute("SELECT count(*) FROM keel_provider_record_revisions WHERE tenant_id=%s AND provider_record_identity_id=%s", (seed["tenant"], first["identity_id"]))
        assert cur.fetchone()[0] == 1
    c.close()


def test_reviewer_context_audits_association_and_conflicting_revision_preserves_mapping():
    seed = _seed()
    conn = _connect_app(seed["tenant"], seed["actor"])
    try:
        product = persist_shopify_records(conn, seed["source"], _shopify_records()[:1])[0]
        conn.commit()
        decision = associate_provider_record(conn, product["identity_id"], "product", seed["canonical"], reason_code="explicit_review")
        conn.commit()
        again = associate_provider_record(conn, product["identity_id"], "product", seed["canonical"], reason_code="explicit_review")
        conn.commit()
        assert not decision["duplicate"] and again["duplicate"]
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.current_user_id',%s,false)", (seed["staff"],))
            with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                associate_provider_record(conn, product["identity_id"], "product", seed["canonical"])
            conn.rollback()
            cur.execute("SELECT set_config('app.current_tenant_id',%s,false)", (seed["tenant"],))
            cur.execute("SELECT set_config('app.current_user_id',%s,false)", (seed["actor"],))
            cur.execute("SELECT * FROM public.keel_provider_identity_observe(%s,'product','gid://shopify/Product/100',NULL,NULL,NULL,%s,%s::timestamptz,%s,NULL)",
                        (seed["source"], "same-time-different-revision", "2026-10-20T12:00:00Z", "b"*64))
            row = cur.fetchone()
            assert row[1] == "conflict"
        conn.commit()
        with conn.cursor() as cur:
            cur.execute("SELECT mapping_status,canonical_product_id FROM keel_provider_record_identities WHERE tenant_id=%s AND provider_record_identity_id=%s", (seed["tenant"], product["identity_id"]))
            assert cur.fetchone() == ("conflict", seed["canonical"])
            cur.execute("SELECT reviewer_user_id,decision,target_kind,canonical_product_id FROM keel_provider_record_reviews WHERE tenant_id=%s AND provider_record_identity_id=%s", (seed["tenant"], product["identity_id"]))
            review = cur.fetchone()
            assert review == (seed["actor"], "associate", "product", seed["canonical"])
            cur.execute("SELECT count(*) FROM audit_logs WHERE tenant_id=%s AND record_id=%s AND action_type='PROVIDER_RECORD_ASSOCIATED'", (seed["tenant"], product["identity_id"]))
            assert cur.fetchone()[0] == 1
        unversioned = ShopifyRecord("product", "gid://shopify/Product/101", {"id":"gid://shopify/Product/101", "sku":"NO-REVISION"})
        first = persist_shopify_records(conn, seed["source"], [unversioned])[0]
        conn.commit()
        associate_provider_record(conn, first["identity_id"], "product", seed["canonical"])
        conn.commit()
        repeated = persist_shopify_records(conn, seed["source"], [unversioned])[0]
        conn.commit()
        assert repeated["mapping_status"] == "conflict" and repeated["duplicate"]
        with conn.cursor() as cur:
            cur.execute("SELECT canonical_product_id FROM keel_provider_record_identities WHERE tenant_id=%s AND provider_record_identity_id=%s", (seed["tenant"], first["identity_id"]))
            assert cur.fetchone()[0] == seed["canonical"]
    finally:
        conn.close()


def test_cross_source_parent_is_rejected_and_source_and_product_deletions_are_restricted():
    seed = _seed(second_source=True)
    conn1 = _connect_app(seed["tenant"], seed["actor"])
    saved = persist_shopify_records(conn1, seed["sources"][0], _shopify_records()[:2])
    product = saved[0]
    conn1.commit(); conn1.close()
    conn2 = _connect_app(seed["tenant"], seed["actor"])
    try:
        with pytest.raises(psycopg2.errors.ForeignKeyViolation):
            persist_shopify_records(conn2, seed["sources"][1], [ShopifyRecord("variant", "gid://shopify/ProductVariant/888", {"id":"gid://shopify/ProductVariant/888","updatedAt":"2026-10-20T12:00:00Z"}, "gid://shopify/Product/100")])
        conn2.rollback()
    finally:
        conn2.close()
    assoc = _connect_app(seed["tenant"], seed["actor"])
    associate_provider_record(assoc, product["identity_id"], "product", seed["canonical"])
    assoc.commit(); assoc.close()
    admin = psycopg2.connect(ADMIN_URL)
    try:
        with admin.cursor() as cur:
            with pytest.raises(psycopg2.errors.ForeignKeyViolation):
                cur.execute("DELETE FROM products WHERE tenant_id=%s AND product_id=%s", (seed["tenant"], seed["canonical"]))
            admin.rollback()
            with admin.cursor() as cur:
                with pytest.raises(psycopg2.errors.ForeignKeyViolation):
                    cur.execute("DELETE FROM keel_provider_sources WHERE tenant_id=%s AND source_id=%s", (seed["tenant"], seed["sources"][0]))
            admin.rollback()
            with admin.cursor() as cur:
                with pytest.raises(psycopg2.errors.ForeignKeyViolation):
                    cur.execute("DELETE FROM keel_provider_record_identities WHERE tenant_id=%s AND provider_record_identity_id=%s", (seed["tenant"], product["identity_id"]))
            admin.rollback()
            with admin.cursor() as cur:
                with pytest.raises(psycopg2.errors.ForeignKeyViolation):
                    cur.execute("DELETE FROM companies WHERE tenant_id=%s", (seed["tenant"],))
            admin.rollback()
    finally:
        admin.close()


def test_cross_tenant_identity_is_not_visible_or_associable():
    owner = _seed()
    other = _seed()
    owner_conn = _connect_app(owner["tenant"], owner["actor"])
    identity = persist_shopify_records(owner_conn, owner["source"], _shopify_records()[:1])[0]
    owner_conn.commit(); owner_conn.close()
    other_conn = _connect_app(other["tenant"], other["actor"])
    try:
        with other_conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM keel_provider_record_identities")
            assert cur.fetchone()[0] == 0
        with pytest.raises(psycopg2.errors.NoDataFound):
            associate_provider_record(other_conn, identity["identity_id"], "product", other["canonical"])
        other_conn.rollback()
    finally:
        other_conn.close()


def test_woocommerce_provider_identity_and_line_item_fields_are_non_pii():
    seed = _seed(provider="woocommerce")
    class CaptureCursor:
        def __init__(self): self.params=[]
        def __enter__(self): return self
        def __exit__(self,*_): return False
        def execute(self,query,params): self.params.append(params)
        def fetchone(self): return (uuid.uuid4(), "pending_review", False)
    class CaptureConnection:
        def __init__(self): self.c=CaptureCursor()
        def cursor(self): return self.c
    conn=CaptureConnection()
    records=[WooRecord("product",17,{"id":17,"name":"not persisted"}),
             WooRecord("order",31,{"id":31,"date_modified_gmt":"2026-10-20T12:00:00","billing":{"email":"private@example.test"},
                                    "line_items":[{"id":41,"product_id":17,"variation_id":0,"name":"private","total":"22.00"}]})]
    assert isinstance(records[0].provider_id, int)
    persisted=persist_woocommerce_records(conn,seed["source"],records)
    assert [r["entity_type"] for r in persisted]==["product","order","order_line_item"]
    flattened=json.dumps(conn.c.params, default=str)
    assert "private@example.test" not in flattened and "not persisted" not in flattened and "22.00" not in flattened
    assert all(len(params[8])==64 for params in conn.c.params)


def test_invalid_provider_record_ids_fail_before_database_write():
    class C:
        def __enter__(self): return self
        def __exit__(self,*_): return False
        def execute(self,*_): raise AssertionError("database must not be called")
    class Conn:
        def cursor(self): return C()
    with pytest.raises(ProviderIdentityError):
        persist_shopify_records(Conn(), "source", [ShopifyRecord("product", "not-a-shopify-gid", {"id":"not-a-shopify-gid"})])
