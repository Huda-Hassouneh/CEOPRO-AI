"""Native PostgreSQL 17 tests for Migration 96, gated to a disposable database."""
from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse, urlunparse

import psycopg2
import pytest

from src.market_scraper.inventory_provenance import (
    decide_inventory_authority,
    decide_provider_location_association,
    list_inventory_authority_history,
    list_inventory_observation_history,
    list_provider_inventory_location_history,
    persist_shopify_inventory_records,
    persist_woocommerce_inventory_records,
    register_canonical_inventory_location,
)
from src.market_scraper.provider_identity import associate_provider_record, persist_shopify_records
from src.market_scraper.shopify import ShopifyRecord
from src.market_scraper.woocommerce import WooRecord

ADMIN_URL = os.getenv("AI_TEST_DATABASE_URL")
APP_PASSWORD = os.getenv("APP_DB_PASSWORD")
pytestmark = pytest.mark.skipif(not ADMIN_URL or not APP_PASSWORD,
    reason="AI_TEST_DATABASE_URL and APP_DB_PASSWORD are required for native inventory tests")


def _app(tenant: str, actor: str):
    parsed = urlparse(ADMIN_URL)
    conn = psycopg2.connect(urlunparse(parsed._replace(netloc=f"ceopro_app:{APP_PASSWORD}@{parsed.hostname}:{parsed.port}")))
    with conn.cursor() as cur:
        cur.execute("SELECT set_config('app.current_tenant_id',%s,false)", (tenant,))
        cur.execute("SELECT set_config('app.current_user_id',%s,false)", (actor,))
    conn.commit()
    return conn


def _seed(*, providers=("shopify",), stock=37):
    admin = psycopg2.connect(ADMIN_URL)
    admin.autocommit = True
    tenant, actor, staff, product = (str(uuid.uuid4()) for _ in range(4))
    sources = [str(uuid.uuid4()) for _ in providers]
    with admin.cursor() as cur:
        cur.execute("ALTER ROLE ceopro_app WITH PASSWORD %s", (APP_PASSWORD,))
        cur.execute("INSERT INTO companies(tenant_id,business_name,country_code,primary_currency) VALUES(%s,'M96 test','JO','JOD')", (tenant,))
        cur.execute("INSERT INTO users(user_id,email,password_hash,full_name) VALUES(%s,%s,'x','owner'),(%s,%s,'x','staff')",
                    (actor,f"m96-owner-{actor}@example.test",staff,f"m96-staff-{staff}@example.test"))
        cur.execute("INSERT INTO tenant_users(tenant_id,user_id,role_key) VALUES(%s,%s,'owner'),(%s,%s,'staff')",
                    (tenant,actor,tenant,staff))
        cur.execute("INSERT INTO products(product_id,tenant_id,product_name,current_price,currency) VALUES(%s,%s,'{\"en\":\"Canonical\"}'::jsonb,10,'JOD')",(product,tenant))
        cur.execute("INSERT INTO inventory(tenant_id,product_id,stock_quantity) VALUES(%s,%s,%s)",(tenant,product,stock))
        for index,(source,provider) in enumerate(zip(sources,providers)):
            store_id=f"gid://shopify/Shop/{1000+index}" if provider=="shopify" else str(9000+index)
            domain=f"m96-{index}.myshopify.com" if provider=="shopify" else f"https://m96-{index}.example.test"
            provenance="shopify_authenticated_shop_query" if provider=="shopify" else "woocommerce_authenticated_store_identity"
            cur.execute("INSERT INTO data_sources(source_id,tenant_id,source_name,source_type,collector_key,collector_config,is_active) VALUES(%s,%s,%s,'OWN_SYSTEM_CONNECTOR',%s,'{}',true)",
                        (source,tenant,f"M96 source {index}",provider))
            cur.execute("INSERT INTO keel_provider_sources(tenant_id,source_id,provider,verified_store_id,verified_store_domain,identity_provenance,verified_at,verified_by_user_id) VALUES(%s,%s,%s,%s,%s,%s,now(),%s)",
                        (tenant,source,provider,store_id,domain,provenance,actor))
    admin.close()
    return {"tenant":tenant,"actor":actor,"staff":staff,"product":product,"sources":sources,"stock":stock}


def _shopify_level(location="gid://shopify/Location/1", quantity=11, *, updated="2026-10-20T12:00:00Z"):
    return [
        ShopifyRecord("location", location, {"id":location,"name":"Fulfillment A","isActive":True,"updatedAt":updated}),
        ShopifyRecord("inventory_level", "gid://shopify/InventoryLevel/2", {
            "id":"gid://shopify/InventoryLevel/2","updatedAt":updated,
            "item":{"id":"gid://shopify/InventoryItem/3","variant":{"id":"gid://shopify/ProductVariant/4"}},
            "quantities":[{"name":"available","quantity":quantity},{"name":"on_hand","quantity":quantity+2}],
        }, location),
    ]


def test_restricted_role_observations_locations_authority_and_canonical_stock_preservation():
    seed=_seed()
    conn=_app(seed["tenant"],seed["actor"])
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT current_user,rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user")
            assert cur.fetchone()==("ceopro_app",False,False)
            cur.execute("SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid='public.keel_inventory_observations'::regclass")
            assert cur.fetchone()==(True,True)
        identities=persist_shopify_records(conn,seed["sources"][0],[
            ShopifyRecord("product","gid://shopify/Product/5",{"id":"gid://shopify/Product/5","updatedAt":"2026-10-20T12:00:00Z"}),
            ShopifyRecord("variant","gid://shopify/ProductVariant/4",{"id":"gid://shopify/ProductVariant/4","updatedAt":"2026-10-20T12:00:00Z"},"gid://shopify/Product/5"),
        ])
        variant=identities[1]["identity_id"]
        associate_provider_record(conn,variant,"product",seed["product"],reason_code="explicit_review")
        observations=persist_shopify_inventory_records(conn,seed["sources"][0],_shopify_level())
        assert len(observations)==2 and all(row["reconciliation_status"]=="unmatched_location" for row in observations)
        location_id=None
        with conn.cursor() as cur:
            cur.execute("SELECT provider_location_identity_id FROM keel_provider_inventory_locations WHERE tenant_id=%s",(seed["tenant"],))
            location_id=str(cur.fetchone()[0])
        canonical_location=register_canonical_inventory_location(conn,"warehouse-a","Warehouse A")
        decide_provider_location_association(conn,seed["sources"][0],location_id,"associate",canonical_location,"verified_location_review")
        # Repeated provider fetch is idempotent and preserves the original evidence snapshot.
        replay=persist_shopify_inventory_records(conn,seed["sources"][0],_shopify_level())
        assert all(item["duplicate"] for item in replay)
        assert len(list_inventory_observation_history(conn,canonical_product_id=seed["product"])) == 2
        assert len(list_provider_inventory_location_history(conn,seed["sources"][0])) == 1
        authority_id=decide_inventory_authority(conn,canonical_product_id=seed["product"],canonical_location_id=canonical_location,
            quantity_semantics="available",decision="select",authority_kind="provider",source_id=seed["sources"][0],
            provider="shopify",provider_record_identity_id=variant,provider_location_identity_id=location_id,evidence_code="tenant_selected")
        assert decide_inventory_authority(conn,canonical_product_id=seed["product"],canonical_location_id=canonical_location,
            quantity_semantics="available",decision="select",authority_kind="provider",source_id=seed["sources"][0],
            provider="shopify",provider_record_identity_id=variant,provider_location_identity_id=location_id,evidence_code="tenant_selected")==authority_id
        decide_inventory_authority(conn,canonical_product_id=seed["product"],canonical_location_id=canonical_location,
            quantity_semantics="available",decision="revoke",authority_kind="provider",evidence_code="review_revoked")
        history=list_inventory_authority_history(conn,canonical_product_id=seed["product"],canonical_location_id=canonical_location)
        assert [row["decision"] for row in history]==["revoke","select"]
        with conn.cursor() as cur:
            cur.execute("SELECT count(*),count(DISTINCT quantity_semantics) FROM keel_inventory_observations WHERE tenant_id=%s",(seed["tenant"],))
            assert cur.fetchone()==(2,2)
            cur.execute("SELECT stock_quantity FROM inventory WHERE tenant_id=%s AND product_id=%s",(seed["tenant"],seed["product"]))
            assert cur.fetchone()[0]==seed["stock"]
            cur.execute("SELECT count(*) FROM keel_inventory_authority_decisions WHERE tenant_id=%s",(seed["tenant"],))
            assert cur.fetchone()[0]==2
            cur.execute("SELECT decision,prior_decision_id FROM keel_inventory_authority_decisions WHERE tenant_id=%s ORDER BY decision_sequence",(seed["tenant"],))
            decisions=cur.fetchall()
            assert decisions[0][0]=="select" and decisions[1]==("revoke",authority_id)
        with pytest.raises(psycopg2.errors.InsufficientPrivilege):
            with conn.cursor() as cur:
                cur.execute("INSERT INTO keel_inventory_authority_decisions(tenant_id) VALUES(%s)",(seed["tenant"],))
        conn.rollback()
    finally:
        conn.close()


def test_staff_cannot_select_authority_and_cross_tenant_location_isolation():
    seed=_seed()
    conn=_app(seed["tenant"],seed["staff"])
    try:
        with pytest.raises(psycopg2.errors.InsufficientPrivilege):
            register_canonical_inventory_location(conn,"staff-location","Staff location")
        conn.rollback()
        with conn.cursor() as cur:
            other=str(uuid.uuid4())
            cur.execute("SELECT count(*) FROM keel_inventory_locations WHERE tenant_id=%s",(other,))
            assert cur.fetchone()[0]==0
    finally:
        conn.close()


def test_woocommerce_stock_quantity_has_no_fabricated_location_and_replays_idempotently():
    seed=_seed(providers=("woocommerce",))
    conn=_app(seed["tenant"],seed["actor"])
    record=WooRecord("product",42,{"id":42,"manage_stock":True,"stock_quantity":-2,"date_modified_gmt":"2026-10-20T12:00:00"})
    try:
        first=persist_woocommerce_inventory_records(conn,seed["sources"][0],[record])
        second=persist_woocommerce_inventory_records(conn,seed["sources"][0],[record])
        assert first[0]["quantity_semantics"]=="woocommerce_stock_quantity"
        assert first[0]["reconciliation_status"]=="unmatched_product"
        assert second[0]["duplicate"] is True
        with conn.cursor() as cur:
            cur.execute("SELECT provider_location_identity_id,canonical_location_id,quantity FROM keel_inventory_observations WHERE tenant_id=%s",(seed["tenant"],))
            assert cur.fetchone()==(None,None,-2)
            cur.execute("SELECT stock_quantity FROM inventory WHERE tenant_id=%s AND product_id=%s",(seed["tenant"],seed["product"]))
            assert cur.fetchone()[0]==seed["stock"]
    finally:
        conn.close()


def test_concurrent_replays_create_one_observation():
    seed=_seed(providers=("woocommerce",))
    rec=WooRecord("product",73,{"id":73,"manage_stock":True,"stock_quantity":4,"date_modified_gmt":"2026-10-20T12:00:00"})
    def run():
        conn=_app(seed["tenant"],seed["actor"])
        try:
            result=persist_woocommerce_inventory_records(conn,seed["sources"][0],[rec])
            conn.commit()
            return result
        finally:
            conn.close()
    with ThreadPoolExecutor(max_workers=4) as executor:
        results=list(executor.map(lambda _:run(),range(4)))
    assert sum(not batch[0]["duplicate"] for batch in results)==1
    admin=psycopg2.connect(ADMIN_URL)
    try:
        with admin.cursor() as cur:
            cur.execute("SELECT count(*) FROM keel_inventory_observations WHERE tenant_id=%s",(seed["tenant"],))
            assert cur.fetchone()[0]==1
    finally:
        admin.close()


def test_conflicting_quantity_at_same_provider_revision_is_retained_and_flagged():
    seed=_seed(providers=("woocommerce",))
    conn=_app(seed["tenant"],seed["actor"])
    try:
        first=WooRecord("product",88,{"id":88,"manage_stock":True,"stock_quantity":5,"date_modified_gmt":"2026-10-20T12:00:00"})
        second=WooRecord("product",88,{"id":88,"manage_stock":True,"stock_quantity":7,"date_modified_gmt":"2026-10-20T12:00:00"})
        assert persist_woocommerce_inventory_records(conn,seed["sources"][0],[first])[0]["reconciliation_status"]=="unmatched_product"
        assert persist_woocommerce_inventory_records(conn,seed["sources"][0],[second])[0]["reconciliation_status"]=="conflict"
        with conn.cursor() as cur:
            cur.execute("SELECT count(*),count(*) FILTER (WHERE reconciliation_status='conflict'),count(DISTINCT quantity) FROM keel_inventory_observations WHERE tenant_id=%s",(seed["tenant"],))
            assert cur.fetchone()==(2,1,2)
    finally:
        conn.close()
