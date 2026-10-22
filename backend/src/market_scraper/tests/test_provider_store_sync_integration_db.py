"""Native restricted-role tests for the complete Shopify evidence worker."""
from __future__ import annotations

import os
import threading
import uuid
from urllib.parse import urlparse, urlunparse

import psycopg2
import pytest
from cryptography.fernet import Fernet

from src.market_scraper import connector_worker, data_access, provider_store_sync
from src.market_scraper.provider_lifecycle import bind_verified_provider_source
from src.market_scraper.shopify import ShopifyGraphQLClient, ShopifyRecord
from src.market_scraper.woocommerce import WooRecord

ADMIN_URL = os.getenv("AI_TEST_DATABASE_URL")
APP_PASSWORD = os.getenv("APP_DB_PASSWORD")
pytestmark = pytest.mark.skipif(
    not ADMIN_URL or not APP_PASSWORD,
    reason="AI_TEST_DATABASE_URL and APP_DB_PASSWORD are required for native Shopify worker verification",
)


def _app_url() -> str:
    parsed = urlparse(ADMIN_URL)
    return urlunparse(parsed._replace(netloc=f"ceopro_app:{APP_PASSWORD}@{parsed.hostname}:{parsed.port}"))


def _rows(sql: str, params: tuple = ()) -> list[tuple]:
    with psycopg2.connect(ADMIN_URL) as conn, conn.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchall()


class _ShopifyFixture:
    def __init__(self, shop_id: str, domain: str, mode: str, hooks=None):
        self.shop_id, self.domain, self.mode = shop_id, domain, mode
        self.hooks = hooks
        self.updated = "2026-10-20T10:00:00Z"
        self.product_id = "gid://shopify/Product/11001"
        self.variant_id = "gid://shopify/ProductVariant/11002"
        self.order_id = "gid://shopify/Order/11003"
        self.line_id = "gid://shopify/LineItem/11004"
        self.location_id = "gid://shopify/Location/11005"
        self.inventory_id = "gid://shopify/InventoryLevel/11006"

    def verify_connection(self):
        return {
            "verified": True, "shop_id": self.shop_id, "shop_domain": self.domain,
            "granted_scopes": frozenset({"read_products", "read_orders", "read_inventory"}),
        }

    def iter_products(self):
        ShopifyGraphQLClient.require_scopes(self.verify_connection(), ("read_products",))
        if self.hooks:
            self.hooks["started"].set()
            if not self.hooks["continue"].wait(timeout=15):
                raise TimeoutError("native credential-rotation fixture timed out")
        product = ShopifyRecord("product", self.product_id, {"id": self.product_id, "updatedAt": self.updated})
        variant = ShopifyRecord("variant", self.variant_id,
                                {"id": self.variant_id, "updatedAt": self.updated, "sku": "SAME-SKU"},
                                self.product_id)
        records = [product, variant, product, variant]
        if self.mode == "persistence_error":
            return iter([
                ShopifyRecord("product", "gid://shopify/Product/11999",
                              {"id": "gid://shopify/Product/11999", "updatedAt": self.updated}),
                ShopifyRecord("variant", "invalid-id", {"id": "invalid-id"}, self.product_id),
            ])
        if self.mode == "retry":
            records.extend([
                ShopifyRecord("product", "gid://shopify/Product/11999",
                              {"id": "gid://shopify/Product/11999", "updatedAt": self.updated}),
                ShopifyRecord("variant", "gid://shopify/ProductVariant/11998",
                              {"id": "gid://shopify/ProductVariant/11998", "updatedAt": self.updated},
                              "gid://shopify/Product/11999"),
            ])
        return iter(records)

    def iter_orders(self):
        ShopifyGraphQLClient.require_scopes(self.verify_connection(), ("read_orders",))
        order = ShopifyRecord("order", self.order_id, {"id": self.order_id, "updatedAt": self.updated})
        line = ShopifyRecord("line_item", self.line_id,
                             {"id": self.line_id, "variant": {"id": self.variant_id,
                              "product": {"id": self.product_id}}}, self.order_id)
        return iter([order, line, order, line])

    def iter_inventory(self):
        ShopifyGraphQLClient.require_scopes(self.verify_connection(), ("read_inventory",))
        location = ShopifyRecord("location", self.location_id,
                                 {"id": self.location_id, "name": "Fixture warehouse",
                                  "isActive": True, "updatedAt": self.updated})
        level = ShopifyRecord("inventory_level", self.inventory_id,
                              {"id": self.inventory_id, "updatedAt": self.updated,
                               "item": {"id": "gid://shopify/InventoryItem/11007",
                                        "variant": {"id": self.variant_id}},
                               "quantities": [{"name": "available", "quantity": 8},
                                              {"name": "on_hand", "quantity": 10}]},
                              self.location_id)
        return iter([location, level, location, level])


def test_worker_dispatch_persists_all_streams_atomically_and_recovers(monkeypatch):
    tenant, actor, source, canonical_product = (str(uuid.uuid4()) for _ in range(4))
    shop_id = f"gid://shopify/Shop/{int(uuid.UUID(tenant)) % 10**12}"
    domain = f"{tenant.replace('-', '')[:12]}.myshopify.com"
    monkeypatch.setenv("APP_DB_PASSWORD", APP_PASSWORD)
    monkeypatch.setenv("SCRAPER_DATABASE_URL", _app_url())
    monkeypatch.setenv("SCRAPER_ACTOR_USER_ID", actor)
    monkeypatch.setenv("KEEL_ENT008_STAGE2_ENABLED", "true")
    monkeypatch.setenv("CREDENTIAL_VAULT_MASTER_KEY", Fernet.generate_key().decode())
    with psycopg2.connect(ADMIN_URL) as admin:
        admin.autocommit = True
        with admin.cursor() as cursor:
            cursor.execute(
                "INSERT INTO companies(tenant_id,business_name,country_code,primary_currency) "
                "VALUES(%s,%s,'JO','JOD')", (tenant, f"Shopify worker {tenant[:8]}"),
            )
            cursor.execute(
                "INSERT INTO users(user_id,email,password_hash,full_name) VALUES(%s,%s,'x','Worker test')",
                (actor, f"shopify-worker-{actor}@example.test"),
            )
            staff = str(uuid.uuid4())
            cursor.execute("INSERT INTO users(user_id,email,password_hash,full_name) VALUES(%s,%s,'x','Worker staff')",
                           (staff, f"shopify-staff-{staff}@example.test"))
            cursor.execute("INSERT INTO tenant_users(tenant_id,user_id,role_key) VALUES(%s,%s,'owner')", (tenant, actor))
            cursor.execute("INSERT INTO tenant_users(tenant_id,user_id,role_key) VALUES(%s,%s,'staff')", (tenant, staff))
            cursor.execute(
                "INSERT INTO tenant_plan_assignments(tenant_id,plan_key,status,source) "
                "VALUES(%s,'starter','active','manual')", (tenant,),
            )
            cursor.execute(
                "INSERT INTO data_sources(source_id,tenant_id,source_name,source_type,collector_key,collector_config,"
                "is_active,policy_status,approval_reference,approved_by,approved_at,privacy_reviewed_at,sync_frequency_minutes) "
                "VALUES(%s,%s,'Shopify fixture','OWN_SYSTEM_CONNECTOR','shopify',"
                "'{\"api_version\":\"2026-10\",\"max_pages\":3}'::jsonb,true,'ALLOWED',"
                "'synthetic-test-approval',%s,now(),now(),1)", (source, tenant, actor),
            )
            cursor.execute(
                "INSERT INTO products(product_id,tenant_id,product_name,current_price,currency,source) "
                "VALUES(%s,%s,'{\"en\":\"Keep canonical\"}'::jsonb,12.5,'USD','MANUAL')",
                (canonical_product, tenant),
            )
            cursor.execute("INSERT INTO inventory(tenant_id,product_id,stock_quantity) VALUES(%s,%s,13)",
                           (tenant, canonical_product))
        data_access.set_source_credentials(admin, tenant, source, {"access_token": "synthetic-native-token"})

    assert "synthetic-native-token" not in _rows(
        "SELECT connection_credentials_vault FROM data_sources WHERE tenant_id=%s AND source_id=%s",
        (tenant, source),
    )[0][0]
    app_conn = psycopg2.connect(_app_url())
    with app_conn.cursor() as cursor:
        cursor.execute("SELECT set_config('app.current_tenant_id',%s,false)", (tenant,))
        cursor.execute("SELECT set_config('app.current_user_id',%s,false)", (actor,))
        cursor.execute("SELECT current_user,rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user")
        assert cursor.fetchone() == ("ceopro_app", False, False)
        cursor.execute(
            "SELECT relrowsecurity,relforcerowsecurity FROM pg_class "
            "WHERE oid='public.keel_provider_record_identities'::regclass",
        )
        assert cursor.fetchone() == (True, True)
    bind_verified_provider_source(
        app_conn, tenant_id=tenant, source_id=source, provider="shopify",
        verification={"verified": True, "shop_id": shop_id, "shop_domain": domain, "api_version": "2026-10"},
    )
    app_conn.commit()
    app_conn.close()

    state = {"mode": "success", "hooks": None}
    factory = lambda *_args, **_kwargs: _ShopifyFixture(shop_id, domain, state["mode"], state["hooks"])
    original = provider_store_sync.run_due_provider_syncs
    dispatch = lambda conn, tenant_id: original(conn, tenant_id, client_factory=factory)
    monkeypatch.setattr(connector_worker.provider_store_sync, "run_due_provider_syncs", dispatch)
    data_access._POOL = None
    first = connector_worker.run_connector_syncs_for_tenant(tenant)
    assert len(first["provider_store"]) == 1
    result = first["provider_store"][0]
    assert result["stream_results"] == {"products": 4, "orders": 4, "inventory": 4}
    assert result["full_scan"] is True and result["canonical_promotion"] is False
    assert _rows("SELECT stream_key,continuation FROM keel_provider_sync_checkpoints "
                 "WHERE tenant_id=%s ORDER BY stream_key", (tenant,)) == [
                     ("inventory", {}), ("orders", {}), ("products", {}),
                 ]
    assert _rows("SELECT entity_type,count(*) FROM keel_provider_record_identities "
                 "WHERE tenant_id=%s GROUP BY entity_type ORDER BY entity_type", (tenant,)) == [
                     ("order", 1), ("order_line_item", 1), ("product", 1), ("variant", 1),
                 ]
    assert _rows("SELECT count(*) FROM keel_inventory_observations WHERE tenant_id=%s", (tenant,))[0][0] == 2
    assert _rows("SELECT entity_type,count(*) FROM keel_provider_business_revisions WHERE tenant_id=%s "
                 "GROUP BY entity_type ORDER BY entity_type", (tenant,)) == [
                     ("order", 1), ("order_line_item", 1), ("product", 1), ("variant", 1),
                 ]
    assert _rows("SELECT validation_status,count(*) FROM keel_provider_business_revisions WHERE tenant_id=%s "
                 "GROUP BY validation_status ORDER BY validation_status", (tenant,)) == [
                     ("invalid", 3), ("review_required", 1),
                 ]
    assert _rows("SELECT relrowsecurity,relforcerowsecurity FROM pg_class "
                 "WHERE oid='public.keel_provider_business_revisions'::regclass") == [(True, True)]
    # App role has read-only table grants; writes must pass the fenced M98 command.
    app_conn = psycopg2.connect(_app_url())
    with app_conn.cursor() as cursor:
        cursor.execute("SET LOCAL ROLE ceopro_app")
        cursor.execute("SELECT set_config('app.current_tenant_id',%s,true)", (tenant,))
        cursor.execute("SELECT set_config('app.current_user_id',%s,true)", (actor,))
        with pytest.raises(psycopg2.errors.InsufficientPrivilege):
            cursor.execute("INSERT INTO keel_provider_business_revisions(tenant_id,source_id,provider,provider_record_identity_id,"
                           "entity_type,revision_number,provider_identity_revision_sha256,business_values_sha256,typed_values,"
                           "validation_status,ingestion_job_id) SELECT tenant_id,source_id,provider,provider_record_identity_id,"
                           "entity_type,1,repeat('a',64),repeat('b',64),'{}','invalid',latest_ingestion_job_id "
                           "FROM keel_provider_record_identities WHERE tenant_id=%s LIMIT 1", (tenant,))
        app_conn.rollback()
    app_conn.close()

    # Review decisions are tenant-owner/admin-only, append-only and idempotent.
    review_revision = _rows("SELECT business_revision_id FROM keel_provider_business_revisions "
                            "WHERE tenant_id=%s AND validation_status='review_required'", (tenant,))[0][0]
    app_conn = psycopg2.connect(_app_url())
    with app_conn.cursor() as cursor:
        cursor.execute("SELECT set_config('app.current_tenant_id',%s,false)", (tenant,))
        cursor.execute("SELECT set_config('app.current_user_id',%s,false)", (actor,))
        cursor.execute("SELECT * FROM keel_provider_business_review98(%s,'approve','review-key-1','owner_review')",
                       (review_revision,))
        review_id, duplicate = cursor.fetchone()
        assert duplicate is False
        app_conn.commit()
        cursor.execute("SELECT * FROM keel_provider_business_review98(%s,'approve','review-key-1','owner_review')",
                       (review_revision,))
        assert cursor.fetchone() == (review_id, True)
        app_conn.commit()
    app_conn.close()

    # Exercise the actual FastAPI preview/history/review contract over HTTP
    # against the disposable database and restricted ceopro_app pool.
    monkeypatch.setenv("JWT_SECRET", "native-m98-test-signing-secret-with-32-bytes-minimum")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from src.ai import db as api_db
    from src.ai.core.security import create_access_token
    from src.ai.routers import onboarding
    monkeypatch.setattr(api_db, "_POOL", None)
    http_app = FastAPI()
    http_app.include_router(onboarding.router)
    owner_token, _ = create_access_token(tenant, actor, email_verified=True)
    staff_token, _ = create_access_token(tenant, staff, email_verified=True)
    with TestClient(http_app) as http:
        assert http.get(f"/onboarding/sources/{source}/provider-records").status_code == 401
        response = http.get(f"/onboarding/sources/{source}/provider-records?limit=20&offset=0",
                            headers={"Authorization": f"Bearer {owner_token}"})
        assert response.status_code == 200
        body = response.json()
        assert len(body["items"]) == 4
        approved_item = next(row for row in body["items"] if row["business_revision_id"] == str(review_revision))
        assert approved_item["review_decision"] == "approve"
        assert approved_item["canonical_status"] == "not_posted"
        history = http.get(f"/onboarding/sources/{source}/provider-records/"
                           f"{approved_item['provider_record_identity_id']}/revisions",
                           headers={"Authorization": f"Bearer {owner_token}"})
        assert history.status_code == 200 and len(history.json()["revisions"]) == 1
        repeated_review = http.post(f"/onboarding/sources/{source}/provider-records/reviews", json={
            "business_revision_id": str(review_revision), "decision": "approve",
            "idempotency_key": "review-key-1", "reason_code": "owner_review",
        }, headers={"Authorization": f"Bearer {owner_token}"})
        assert repeated_review.status_code == 200
        assert repeated_review.json()["duplicate"] is True
        denied_review = http.post(f"/onboarding/sources/{source}/provider-records/reviews", json={
            "business_revision_id": str(review_revision), "decision": "reject",
            "idempotency_key": "staff-review-1", "reason_code": "staff_not_allowed",
        }, headers={"Authorization": f"Bearer {staff_token}"})
        assert denied_review.status_code == 403
    api_db.close_pool()
    app_conn = psycopg2.connect(_app_url())
    with app_conn.cursor() as cursor:
        cursor.execute("SELECT set_config('app.current_tenant_id',%s,false)", (tenant,))
        cursor.execute("SELECT set_config('app.current_user_id',%s,false)", (staff,))
        with pytest.raises(psycopg2.errors.InsufficientPrivilege):
            cursor.execute("SELECT * FROM keel_provider_business_review98(%s,'reject','staff-review','not_authorized')",
                           (_rows("SELECT business_revision_id FROM keel_provider_business_revisions WHERE tenant_id=%s "
                                  "AND validation_status='invalid' ORDER BY business_revision_id LIMIT 1", (tenant,))[0][0],))
        app_conn.rollback()
    app_conn.close()

    # M98 evidence remains append-only even for the migration owner, while
    # ordinary restricted-role reads stay tenant-scoped.
    app_conn = psycopg2.connect(_app_url())
    with app_conn.cursor() as cursor:
        cursor.execute("SET LOCAL ROLE ceopro_app")
        cursor.execute("SELECT set_config('app.current_tenant_id',%s,true)", (str(uuid.uuid4()),))
        cursor.execute("SELECT set_config('app.current_user_id',%s,true)", (actor,))
        cursor.execute("SELECT count(*) FROM keel_provider_business_revisions WHERE tenant_id=%s", (tenant,))
        assert cursor.fetchone() == (0,)
    app_conn.rollback()
    app_conn.close()
    evidence_conn = psycopg2.connect(ADMIN_URL)
    with evidence_conn.cursor() as cursor:
        with pytest.raises(psycopg2.errors.ObjectNotInPrerequisiteState):
            cursor.execute("UPDATE keel_provider_business_revisions SET typed_values='{}'::jsonb "
                           "WHERE tenant_id=%s AND business_revision_id=%s", (tenant, review_revision))
    evidence_conn.rollback()
    with evidence_conn.cursor() as cursor:
        with pytest.raises(psycopg2.errors.ObjectNotInPrerequisiteState):
            cursor.execute("DELETE FROM keel_provider_business_revisions WHERE tenant_id=%s AND business_revision_id=%s",
                           (tenant, review_revision))
    evidence_conn.rollback()
    evidence_conn.close()

    before = {
        table: _rows(f"SELECT count(*) FROM {table} WHERE tenant_id=%s", (tenant,))[0][0]
        for table in ("products", "transactions", "invoices", "inventory", "tenant_usage_counters", "usage_ledger")
    }
    with psycopg2.connect(ADMIN_URL) as admin, admin.cursor() as cursor:
        cursor.execute("UPDATE data_sources SET last_synced_at=NULL WHERE tenant_id=%s AND source_id=%s",
                       (tenant, source))
    state["mode"] = "persistence_error"
    failed = connector_worker.run_connector_syncs_for_tenant(tenant)["provider_store"][0]
    assert "error" in failed
    assert _rows("SELECT count(*) FROM keel_provider_record_identities WHERE tenant_id=%s "
                 "AND provider_record_id='gid://shopify/Product/11999'", (tenant,))[0][0] == 0
    assert _rows("SELECT job_status FROM ingestion_jobs WHERE tenant_id=%s AND source_id=%s "
                 "AND job_status='FAILED'", (tenant, source))
    assert _rows("SELECT checkpoint_version FROM keel_provider_sync_checkpoints "
                 "WHERE tenant_id=%s AND source_id=%s AND stream_key='products'", (tenant, source)) == [(1,)]

    with psycopg2.connect(ADMIN_URL) as admin, admin.cursor() as cursor:
        cursor.execute("UPDATE data_sources SET last_synced_at=NULL WHERE tenant_id=%s AND source_id=%s",
                       (tenant, source))
    state["mode"] = "retry"
    retry = connector_worker.run_connector_syncs_for_tenant(tenant)["provider_store"]
    assert len(retry) == 1 and retry[0]["checkpoint_advanced"] is True
    assert _rows("SELECT count(*) FROM keel_provider_record_identities WHERE tenant_id=%s "
                 "AND provider_record_id='gid://shopify/Product/11999'", (tenant,))[0][0] == 1
    assert _rows("SELECT count(*) FROM keel_provider_record_identities WHERE tenant_id=%s", (tenant,))[0][0] == 6
    assert _rows("SELECT stream_key,checkpoint_version,continuation FROM keel_provider_sync_checkpoints "
                 "WHERE tenant_id=%s ORDER BY stream_key", (tenant,)) == [
                     ("inventory", 2, {}), ("orders", 2, {}), ("products", 2, {}),
                 ]
    after = {
        table: _rows(f"SELECT count(*) FROM {table} WHERE tenant_id=%s", (tenant,))[0][0]
        for table in before
    }
    assert after == before
    assert _rows("SELECT stock_quantity FROM inventory WHERE tenant_id=%s", (tenant,))[0][0] == 13
    assert _rows("SELECT current_price FROM products WHERE tenant_id=%s", (tenant,))[0][0] == 12.5
    assert _rows("SELECT count(*) FROM ingestion_jobs WHERE tenant_id=%s AND job_status='COMPLETED'", (tenant,))[0][0] == 2
    assert _rows("SELECT count(*) FROM keel_operation_receipts WHERE tenant_id=%s AND state='completed'", (tenant,))[0][0] == 2

    # Change credentials while a source-level read is in flight. The worker may
    # finish its synthetic read, but the source fingerprint fence must reject
    # evidence/job/checkpoint commit and the stale verification must not replay.
    with psycopg2.connect(ADMIN_URL) as admin, admin.cursor() as cursor:
        cursor.execute("UPDATE data_sources SET last_synced_at=NULL WHERE tenant_id=%s AND source_id=%s",
                       (tenant, source))
    hooks = {"started": threading.Event(), "continue": threading.Event()}
    state.update(mode="success", hooks=hooks)
    data_access._POOL = None
    worker_result = []
    thread = threading.Thread(
        target=lambda: worker_result.append(connector_worker.run_connector_syncs_for_tenant(tenant)),
        daemon=True,
    )
    thread.start()
    try:
        assert hooks["started"].wait(timeout=10), "worker did not reach the provider read boundary"
        with psycopg2.connect(ADMIN_URL) as admin:
            data_access.set_source_credentials(admin, tenant, source,
                                               {"access_token": "synthetic-rotated-token"})
        hooks["continue"].set()
        thread.join(timeout=20)
        assert not thread.is_alive(), "worker did not release after credential rotation"
    finally:
        hooks["continue"].set()
        thread.join(timeout=20)
    stale_result = worker_result[0]["provider_store"][0]
    assert "error" in stale_result
    assert _rows("SELECT checkpoint_version FROM keel_provider_sync_checkpoints "
                 "WHERE tenant_id=%s ORDER BY stream_key", (tenant,)) == [(2,), (2,), (2,)]
    assert _rows("SELECT last_synced_at FROM data_sources WHERE tenant_id=%s AND source_id=%s",
                 (tenant, source)) == [(None,)]
    assert _rows("SELECT connection_state FROM keel_provider_sources WHERE tenant_id=%s AND source_id=%s",
                 (tenant, source)) == [("verification_required",)]
    assert _rows("SELECT count(*) FROM keel_provider_record_identities WHERE tenant_id=%s", (tenant,))[0][0] == 6
    assert _rows("SELECT count(*) FROM keel_inventory_observations WHERE tenant_id=%s", (tenant,))[0][0] == 2
    data_access._POOL = None


def test_woocommerce_retry_reuses_failed_job_and_persists_only_scoped_evidence(monkeypatch):
    tenant, actor, source, canonical_product = (str(uuid.uuid4()) for _ in range(4))
    store_url = f"https://{tenant.replace('-', '')[:12]}.example.test"
    monkeypatch.setenv("APP_DB_PASSWORD", APP_PASSWORD)
    monkeypatch.setenv("SCRAPER_DATABASE_URL", _app_url())
    monkeypatch.setenv("SCRAPER_ACTOR_USER_ID", actor)
    monkeypatch.setenv("KEEL_ENT008_STAGE2_ENABLED", "true")
    monkeypatch.setenv("CREDENTIAL_VAULT_MASTER_KEY", Fernet.generate_key().decode())

    with psycopg2.connect(ADMIN_URL) as admin:
        admin.autocommit = True
        with admin.cursor() as cursor:
            cursor.execute(
                "INSERT INTO companies(tenant_id,business_name,country_code,primary_currency) "
                "VALUES(%s,%s,'US','USD')", (tenant, f"WooCommerce retry {tenant[:8]}"),
            )
            cursor.execute(
                "INSERT INTO users(user_id,email,password_hash,full_name) VALUES(%s,%s,'x','Woo test owner')",
                (actor, f"woo-worker-{actor}@example.test"),
            )
            cursor.execute("INSERT INTO tenant_users(tenant_id,user_id,role_key) VALUES(%s,%s,'owner')",
                           (tenant, actor))
            cursor.execute(
                "INSERT INTO tenant_plan_assignments(tenant_id,plan_key,status,source) "
                "VALUES(%s,'starter','active','manual')", (tenant,),
            )
            cursor.execute(
                "INSERT INTO data_sources(source_id,tenant_id,source_name,source_url,source_type,collector_key,"
                "collector_config,is_active,policy_status,approval_reference,approved_by,approved_at,"
                "privacy_reviewed_at,sync_frequency_minutes) VALUES(%s,%s,'Woo fixture',%s,"
                "'OWN_SYSTEM_CONNECTOR','woocommerce',%s::jsonb,true,'ALLOWED','synthetic-test-approval',%s,now(),now(),1)",
                (source, tenant, store_url,
                 '{"provider":"woocommerce","store_url":"' + store_url + '","max_pages":3}', actor),
            )
            cursor.execute(
                "INSERT INTO products(product_id,tenant_id,product_name,current_price,currency,source) "
                "VALUES(%s,%s,'{\"en\":\"Canonical unchanged\"}'::jsonb,12.5,'USD','MANUAL')",
                (canonical_product, tenant),
            )
            cursor.execute("INSERT INTO inventory(tenant_id,product_id,stock_quantity) VALUES(%s,%s,13)",
                           (tenant, canonical_product))
        data_access.set_source_credentials(admin, tenant, source,
                                           {"consumer_key": "fixture-key", "consumer_secret": "fixture-secret"})

    app_conn = psycopg2.connect(_app_url())
    with app_conn.cursor() as cursor:
        cursor.execute("SELECT set_config('app.current_tenant_id',%s,false)", (tenant,))
        cursor.execute("SELECT set_config('app.current_user_id',%s,false)", (actor,))
    bind_verified_provider_source(
        app_conn, tenant_id=tenant, source_id=source, provider="woocommerce",
        verification={"verified": True, "api": "wc/v3", "products_accessible": True,
                      "orders_accessible": True, "currency_code": "USD", "canonical_store_url": store_url},
    )
    app_conn.commit()
    app_conn.close()

    state = {"invalid": True}
    original_safe_error = provider_store_sync.safe_connector_error
    captured_errors = []

    def _capture_safe_error(error, operation="Connector synchronization"):
        captured_errors.append((type(error).__name__, str(error), operation))
        return original_safe_error(error, operation)

    monkeypatch.setattr(provider_store_sync, "safe_connector_error", _capture_safe_error)

    class _WooFixture:
        def __init__(self, url, _key, _secret, **_kwargs):
            self.url = url

        def verify_connection(self):
            return {"verified": True, "api": "wc/v3", "products_accessible": True,
                    "orders_accessible": True, "currency_code": "USD", "canonical_store_url": self.url}

        def iter_products(self):
            product = WooRecord("product", 101, {
                "id": 101, "name": "Provider widget", "sku": "WIDGET-101", "type": "simple",
                "status": "publish", "price": "10.00", "regular_price": "10.00",
                "manage_stock": True, "stock_quantity": 7, "date_modified_gmt": "2026-10-20T10:00:00",
            })
            if state["invalid"]:
                return iter([product, WooRecord("product", 0, {"id": 0, "name": "invalid"})])
            return iter([product])

        def iter_orders(self):
            return iter([WooRecord("order", 201, {
                "id": 201, "status": "processing", "currency": "USD", "total": "10.00",
                "date_created_gmt": "2026-10-20T10:00:00",
                "line_items": [{"id": 301, "product_id": 101, "variation_id": 0, "name": "Widget",
                                "quantity": 1, "sku": "WIDGET-101", "subtotal": "10.00", "total": "10.00"}],
            })])

    with psycopg2.connect(_app_url()) as app_conn:
        with app_conn.cursor() as cursor:
            cursor.execute("SELECT set_config('app.current_tenant_id',%s,false)", (tenant,))
            cursor.execute("SELECT set_config('app.current_user_id',%s,false)", (actor,))
        before_canonical = {
            table: _rows(f"SELECT count(*) FROM {table} WHERE tenant_id=%s", (tenant,))[0][0]
            for table in ("transactions", "invoices", "tenant_usage_counters", "usage_ledger")
        }
        before_stock = _rows("SELECT stock_quantity FROM inventory WHERE tenant_id=%s AND product_id=%s",
                             (tenant, canonical_product))[0][0]

        first = provider_store_sync.run_due_provider_syncs(
            app_conn, tenant, woocommerce_client_factory=_WooFixture,
        )
        assert len(first) == 1 and "error" in first[0]
        failed_job = _rows("SELECT job_id FROM ingestion_jobs WHERE tenant_id=%s AND source_id=%s "
                           "AND job_status='FAILED'", (tenant, source))[0][0]
        assert _rows("SELECT count(*) FROM keel_provider_record_identities WHERE tenant_id=%s", (tenant,))[0][0] == 0
        assert _rows("SELECT count(*) FROM keel_provider_sync_checkpoints WHERE tenant_id=%s", (tenant,))[0][0] == 0

        state["invalid"] = False
        retried = provider_store_sync.run_due_provider_syncs(
            app_conn, tenant, woocommerce_client_factory=_WooFixture,
        )
        assert len(retried) == 1 and retried[0].get("checkpoint_advanced") is True, (
            f"unexpected WooCommerce retry result: {retried!r}; captured errors: {captured_errors!r}"
        )
        assert retried[0]["full_scan"] is True and retried[0]["canonical_promotion"] is False
        completed_job = _rows("SELECT job_id FROM ingestion_jobs WHERE tenant_id=%s AND source_id=%s "
                              "AND job_status='COMPLETED'", (tenant, source))[0][0]
        assert str(completed_job) == str(failed_job)
        assert _rows("SELECT stream_key,checkpoint_version,continuation FROM keel_provider_sync_checkpoints "
                     "WHERE tenant_id=%s ORDER BY stream_key", (tenant,)) == [
                         ("inventory", 1, {}), ("orders", 1, {}), ("products", 1, {}),
                     ]
        assert _rows("SELECT entity_type,count(*) FROM keel_provider_record_identities WHERE tenant_id=%s "
                     "GROUP BY entity_type ORDER BY entity_type", (tenant,)) == [
                         ("order", 1), ("order_line_item", 1), ("product", 1),
                     ]
        assert _rows("SELECT count(*) FROM keel_provider_business_revisions WHERE tenant_id=%s", (tenant,))[0][0] == 3
        assert _rows("SELECT count(*) FROM keel_inventory_observations WHERE tenant_id=%s", (tenant,))[0][0] == 1
        after_canonical = {
            table: _rows(f"SELECT count(*) FROM {table} WHERE tenant_id=%s", (tenant,))[0][0]
            for table in before_canonical
        }
        assert after_canonical == before_canonical
        assert _rows("SELECT stock_quantity FROM inventory WHERE tenant_id=%s AND product_id=%s",
                     (tenant, canonical_product))[0][0] == before_stock == 13
    app_conn.close()
