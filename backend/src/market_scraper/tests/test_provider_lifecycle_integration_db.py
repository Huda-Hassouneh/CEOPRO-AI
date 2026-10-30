"""Native restricted-role tests for migration 94 provider lifecycle data."""

import json
import os
import uuid
from urllib.parse import urlparse, urlunparse

import psycopg2
import pytest

from src.ai.core import operation_receipts
from src.market_scraper.provider_lifecycle import (
    advance_completed_checkpoint,
    authenticate_and_record_shopify_delivery,
    bind_verified_provider_source,
)
from src.market_scraper.shopify import ShopifyError

ADMIN_URL = os.getenv("AI_TEST_DATABASE_URL")
APP_PASSWORD = os.getenv("APP_DB_PASSWORD")
pytestmark = pytest.mark.skipif(
    not ADMIN_URL or not APP_PASSWORD,
    reason="AI_TEST_DATABASE_URL and APP_DB_PASSWORD are required for native provider lifecycle verification",
)


def _app_url():
    parsed = urlparse(ADMIN_URL)
    return urlunparse(parsed._replace(netloc=f"ceopro_app:{APP_PASSWORD}@{parsed.hostname}:{parsed.port}"))


@pytest.fixture
def lifecycle_seed():
    admin = psycopg2.connect(ADMIN_URL)
    admin.autocommit = True
    tenants = []
    with admin.cursor() as cur:
        cur.execute("ALTER ROLE ceopro_app WITH PASSWORD %s", (APP_PASSWORD,))
        for label in ("a", "b"):
            tenant, actor, source = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
            tenants.append((tenant, actor, source))
            cur.execute(
                "INSERT INTO companies(tenant_id,business_name,country_code,primary_currency) VALUES(%s,%s,'JO','JOD')",
                (tenant, f"provider lifecycle {label}"),
            )
            cur.execute(
                "INSERT INTO users(user_id,email,password_hash,full_name) VALUES(%s,%s,'x',%s)",
                (actor, f"provider-{label}-{actor}@example.test", label),
            )
            cur.execute("INSERT INTO tenant_users(tenant_id,user_id,role_key) VALUES(%s,%s,'owner')", (tenant, actor))
            cur.execute(
                "INSERT INTO data_sources(source_id,tenant_id,source_name,source_type,collector_key,collector_config,is_active) "
                "VALUES(%s,%s,'store','OWN_SYSTEM_CONNECTOR','shopify','{}'::jsonb,TRUE)",
                (source, tenant),
            )
    yield admin, tenants
    with admin.cursor() as cur:
        ids = [row[0] for row in tenants]
        cur.execute("DELETE FROM keel_provider_delivery_receipts WHERE tenant_id=ANY(%s::uuid[])", (ids,))
        cur.execute("DELETE FROM keel_provider_sync_checkpoints WHERE tenant_id=ANY(%s::uuid[])", (ids,))
        cur.execute("DELETE FROM keel_provider_sources WHERE tenant_id=ANY(%s::uuid[])", (ids,))
        cur.execute("DELETE FROM keel_operation_receipts WHERE tenant_id=ANY(%s::uuid[])", (ids,))
        cur.execute("DELETE FROM ingestion_jobs WHERE tenant_id=ANY(%s::uuid[])", (ids,))
        cur.execute("DELETE FROM data_sources WHERE tenant_id=ANY(%s::uuid[])", (ids,))
        cur.execute("DELETE FROM tenant_users WHERE tenant_id=ANY(%s::uuid[])", (ids,))
        cur.execute("DELETE FROM users WHERE user_id=ANY(%s::uuid[])", ([row[1] for row in tenants],))
        cur.execute("DELETE FROM companies WHERE tenant_id=ANY(%s::uuid[])", (ids,))
    admin.close()


def _tenant_app_connection(tenant, actor):
    conn = psycopg2.connect(_app_url())
    _apply_context(conn, tenant, actor)
    return conn


def _apply_context(conn, tenant, actor):
    with conn.cursor() as cur:
        cur.execute("SELECT set_config('app.current_tenant_id',%s,true)", (tenant,))
        cur.execute("SELECT set_config('app.current_user_id',%s,true)", (actor,))


def _verified(conn, tenant, source):
    numeric_id = str(int(uuid.UUID(tenant)) % 10**12)
    domain = f"{tenant.replace('-', '')[:10]}.myshopify.com"
    return bind_verified_provider_source(
        conn,
        tenant_id=tenant,
        source_id=source,
        provider="shopify",
        verification={
            "verified": True,
            "shop_id": f"gid://shopify/Shop/{numeric_id}",
            "shop_domain": domain,
            "api_version": "2026-10",
        },
    )


def test_expired_shopify_receipt_recovery_executes_in_native_database(lifecycle_seed):
    """Exercise all three recovery statements, including verified Shopify replay."""
    admin, tenants = lifecycle_seed
    tenant, actor, source = tenants[0]
    app_conn = _tenant_app_connection(tenant, actor)
    try:
        _verified(app_conn, tenant, source)
        app_conn.commit()
        _apply_context(app_conn, tenant, actor)
        with admin.cursor() as cur:
            cur.execute(
                "UPDATE data_sources SET policy_status='ALLOWED',approval_reference='synthetic-test',"
                "approved_by=%s,approved_at=now(),privacy_reviewed_at=now() "
                "WHERE tenant_id=%s::uuid AND source_id=%s::uuid",
                (actor, tenant, source),
            )
            receipt_id = str(uuid.uuid4())
            cur.execute(
                "INSERT INTO keel_operation_receipts "
                "(receipt_id,tenant_id,source_id,operation_type,principal_kind,actor_user_id,period_start,"
                "request_fingerprint,idempotency_key,state,lease_owner,lease_expires_at,lease_generation,"
                "provider_started_at,provider_outcome,target_kind,target_id) "
                "VALUES(%s::uuid,%s::uuid,%s::uuid,'scheduled_connector_sync','service',%s::uuid,current_date,"
                "repeat('a',64),%s::uuid,'provider_started','stale-worker',now()-interval '1 second',1,"
                "now(),'unknown','source',%s::uuid)",
                (receipt_id, tenant, source, actor, str(uuid.uuid4()), source),
            )
        _apply_context(app_conn, tenant, actor)

        assert operation_receipts.recover_expired(app_conn, tenant) == {
            "retryable": 1,
            "reconciliation_required": 0,
        }
        _apply_context(app_conn, tenant, actor)
        with app_conn.cursor() as cur:
            cur.execute(
                "SELECT state,provider_started_at,provider_outcome FROM keel_operation_receipts "
                "WHERE tenant_id=%s::uuid AND receipt_id=%s::uuid",
                (tenant, receipt_id),
            )
            assert cur.fetchone() == ("retryable", None, "not_started")
    finally:
        app_conn.close()


def test_restricted_role_provider_binding_reconnect_is_tenant_scoped_and_delete_restricted(lifecycle_seed):
    admin, tenants = lifecycle_seed
    tenant_a, actor_a, source_a = tenants[0]
    tenant_b, actor_b, source_b = tenants[1]
    app_conn = _tenant_app_connection(tenant_a, actor_a)
    try:
        with app_conn.cursor() as cur:
            cur.execute("SELECT current_user,rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user")
            assert cur.fetchone() == ("ceopro_app", False, False)
            cur.execute("SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid='public.keel_provider_sources'::regclass")
            assert cur.fetchone() == (True, True)
        first = _verified(app_conn, tenant_a, source_a)
        again = _verified(app_conn, tenant_a, source_a)
        assert first["reconnected"] is False
        assert again["reconnected"] is True
        app_conn.commit()
        _apply_context(app_conn, tenant_a, actor_a)
        with app_conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM keel_provider_sources WHERE tenant_id=%s::uuid", (tenant_a,))
            assert cur.fetchone()[0] == 1
            cur.execute("SELECT count(*) FROM keel_provider_sources WHERE tenant_id=%s::uuid", (tenant_b,))
            assert cur.fetchone()[0] == 0
            cur.execute(
                "SELECT count(*) FROM audit_logs WHERE tenant_id=%s::uuid AND record_id=%s::uuid "
                "AND action_type IN ('PROVIDER_SOURCE_BOUND','PROVIDER_SOURCE_RECONNECTED')",
                (tenant_a, source_a),
            )
            assert cur.fetchone()[0] == 2
            with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                cur.execute(
                    "INSERT INTO keel_provider_sources(tenant_id,source_id,provider,verified_store_id,verified_store_domain,"
                    "identity_provenance,verified_at) VALUES(%s,%s,'shopify','gid://shopify/Shop/other','other.myshopify.com',"
                    "'shopify_authenticated_shop_query',now())", (tenant_a, source_a),
                )
        app_conn.rollback()
        app_conn.close()
        with admin.cursor() as cur:
            with pytest.raises(psycopg2.errors.ForeignKeyViolation):
                cur.execute("DELETE FROM companies WHERE tenant_id=%s", (tenant_a,))
        admin.rollback()
    finally:
        if not app_conn.closed:
            app_conn.close()


def test_duplicate_verified_store_cannot_bind_to_second_source(lifecycle_seed):
    admin, tenants = lifecycle_seed
    tenant_a, actor_a, source_a = tenants[0]
    conn = _tenant_app_connection(tenant_a, actor_a)
    try:
        _verified(conn, tenant_a, source_a)
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO data_sources(tenant_id,source_name,source_type,collector_key,collector_config,is_active) "
                "VALUES(%s,'second store row','OWN_SYSTEM_CONNECTOR','shopify','{}'::jsonb,TRUE) RETURNING source_id",
                (tenant_a,),
            )
            source_b = str(cur.fetchone()[0])
        conn.commit()
        _apply_context(conn, tenant_a, actor_a)
        with pytest.raises(psycopg2.errors.UniqueViolation):
            _verified(conn, tenant_a, source_b)
        conn.rollback()
    finally:
        conn.close()


def test_source_credential_or_configuration_change_invalidates_provider_binding(lifecycle_seed):
    admin, tenants = lifecycle_seed
    tenant_a, actor_a, source_a = tenants[0]
    conn = _tenant_app_connection(tenant_a, actor_a)
    try:
        _verified(conn, tenant_a, source_a)
        conn.commit()
        _apply_context(conn, tenant_a, actor_a)
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE data_sources SET collector_config=%s::jsonb WHERE tenant_id=%s::uuid AND source_id=%s::uuid",
                (json.dumps({"version": 2}), tenant_a, source_a),
            )
            cur.execute("SELECT connection_state,configuration_version FROM keel_provider_sources WHERE tenant_id=%s::uuid", (tenant_a,))
            assert cur.fetchone() == ("verification_required", 2)
        conn.rollback()
    finally:
        conn.close()


def test_checkpoint_is_job_complete_fenced_and_idempotent(lifecycle_seed):
    admin, tenants = lifecycle_seed
    tenant, actor, source = tenants[0]
    app_conn = _tenant_app_connection(tenant, actor)
    try:
        _verified(app_conn, tenant, source)
        app_conn.commit()
        _apply_context(app_conn, tenant, actor)
        job_id, receipt_id = str(uuid.uuid4()), str(uuid.uuid4())
        with admin.cursor() as cur:
            cur.execute(
                "INSERT INTO ingestion_jobs(job_id,tenant_id,source_id,job_status,rows_processed,rows_failed) "
                "VALUES(%s,%s,%s,'COMPLETED',2,0)",
                (job_id, tenant, source),
            )
            cur.execute(
                "INSERT INTO keel_operation_receipts(receipt_id,tenant_id,source_id,ingestion_job_id,operation_type,"
                "principal_kind,actor_user_id,period_start,request_fingerprint,state,lease_owner,lease_expires_at,"
                "lease_generation,provider_started_at,provider_outcome,target_kind,target_id) VALUES(%s,%s,%s,%s,"
                "'scheduled_connector_sync','service',%s,current_date,repeat('a',64),'provider_started','worker-a',"
                "now()+interval '5 minutes',1,now(),'unknown','source',%s)",
                (receipt_id, tenant, source, job_id, actor, source),
            )
        receipt = {
            "operation_type": "scheduled_connector_sync",
            "receipt_id": receipt_id,
            "lease_generation": 1,
        }
        arguments = dict(
            tenant_id=tenant, source_id=source, stream_key="products",
            continuation={"cursor": "synthetic-cursor-1"}, receipt=receipt,
            job_id=job_id, configuration_version=1, job_completed=True,
        )
        assert advance_completed_checkpoint(app_conn, **arguments) == 1
        app_conn.commit()
        _apply_context(app_conn, tenant, actor)
        assert advance_completed_checkpoint(app_conn, **arguments) == 1
        app_conn.commit()
        with admin.cursor() as cur:
            cur.execute("UPDATE data_sources SET collector_config=%s::jsonb WHERE tenant_id=%s AND source_id=%s",
                        (json.dumps({"rotated": True}), tenant, source))
        _apply_context(app_conn, tenant, actor)
        assert _verified(app_conn, tenant, source)["reconnected"] is True
        app_conn.commit()
        _apply_context(app_conn, tenant, actor)
        with admin.cursor() as cur:
            cur.execute(
                "UPDATE keel_operation_receipts SET state='completed',provider_outcome='completed',"
                "lease_owner=NULL,lease_expires_at=NULL,completed_at=now() WHERE receipt_id=%s",
                (receipt_id,),
            )
        next_job, next_receipt = str(uuid.uuid4()), str(uuid.uuid4())
        with admin.cursor() as cur:
            cur.execute(
                "INSERT INTO ingestion_jobs(job_id,tenant_id,source_id,job_status,rows_processed,rows_failed) "
                "VALUES(%s,%s,%s,'COMPLETED',1,0)", (next_job, tenant, source),
            )
            cur.execute(
                "INSERT INTO keel_operation_receipts(receipt_id,tenant_id,source_id,ingestion_job_id,operation_type,"
                "principal_kind,actor_user_id,period_start,request_fingerprint,state,lease_owner,lease_expires_at,"
                "lease_generation,provider_started_at,provider_outcome,target_kind,target_id) VALUES(%s,%s,%s,%s,"
                "'scheduled_connector_sync','service',%s,current_date,repeat('b',64),'provider_started','worker-b',"
                "now()+interval '5 minutes',2,now(),'unknown','source',%s)",
                (next_receipt, tenant, source, next_job, actor, source),
            )
        next_arguments = dict(
            tenant_id=tenant, source_id=source, stream_key="products",
            continuation={"cursor": "synthetic-cursor-2"},
            receipt={"operation_type": "scheduled_connector_sync", "receipt_id": next_receipt, "lease_generation": 2},
            job_id=next_job, configuration_version=3, job_completed=True,
        )
        assert advance_completed_checkpoint(app_conn, **next_arguments) == 2
        app_conn.commit()
        with admin.cursor() as cur:
            cur.execute("UPDATE keel_operation_receipts SET lease_expires_at=now()-interval '1 second' WHERE receipt_id=%s", (next_receipt,))
        _apply_context(app_conn, tenant, actor)
        with pytest.raises(psycopg2.errors.InsufficientPrivilege):
            advance_completed_checkpoint(app_conn, **next_arguments)
        app_conn.rollback()
    finally:
        app_conn.close()


def test_authenticated_delivery_identity_is_deduplicated_and_transitions_are_guarded(lifecycle_seed):
    _admin, tenants = lifecycle_seed
    tenant, actor, source = tenants[0]
    conn = _tenant_app_connection(tenant, actor)
    try:
        _verified(conn, tenant, source)
        with conn.cursor() as cur:
            arguments = (
                source, "shopify", "delivery-1", "products/update", "a" * 64,
                json.dumps({"topic": "products/update"}), "shopify_hmac_sha256", True,
            )
            cur.execute(
                "SELECT * FROM public.keel_provider_delivery_record(%s::uuid,%s,%s,%s,%s,%s::jsonb,%s,%s)",
                arguments,
            )
            first_id, duplicate = cur.fetchone()
            assert duplicate is False
            cur.execute(
                "SELECT * FROM public.keel_provider_delivery_record(%s::uuid,%s,%s,%s,%s,%s::jsonb,%s,%s)",
                arguments,
            )
            second_id, duplicate = cur.fetchone()
            assert second_id == first_id and duplicate is True
            cur.execute("SAVEPOINT before_conflicting_replay")
            with pytest.raises(psycopg2.errors.UniqueViolation):
                cur.execute(
                    "SELECT * FROM public.keel_provider_delivery_record(%s::uuid,%s,%s,%s,%s,%s::jsonb,%s,%s)",
                    (source, "shopify", "delivery-1", "products/update", "b" * 64,
                     json.dumps({"topic": "products/update"}), "shopify_hmac_sha256", True),
                )
            cur.execute("ROLLBACK TO SAVEPOINT before_conflicting_replay")
            cur.execute("SELECT public.keel_provider_delivery_transition(%s,'processed')", (first_id,))
            assert cur.fetchone()[0] is False
            cur.execute("SELECT public.keel_provider_delivery_transition(%s,'processing')", (first_id,))
            assert cur.fetchone()[0] is True
            cur.execute("SELECT public.keel_provider_delivery_transition(%s,'processed')", (first_id,))
            assert cur.fetchone()[0] is True
            with pytest.raises(psycopg2.errors.InvalidParameterValue):
                cur.execute(
                    "SELECT * FROM public.keel_provider_delivery_record(%s::uuid,%s,%s,%s,%s,%s::jsonb,%s,%s)",
                    (source, "shopify", "delivery-2", "products/update", "b" * 64,
                     json.dumps({"topic": "products/update"}), "shopify_hmac_sha256", False),
                )
        conn.rollback()
    finally:
        conn.close()


def test_shopify_webhook_is_hmac_and_source_bound_before_durable_receipt(lifecycle_seed):
    import base64
    import hashlib
    import hmac

    admin, tenants = lifecycle_seed
    tenant, actor, source = tenants[0]
    shop_id = f"gid://shopify/Shop/{int(uuid.UUID(tenant)) % 10**12}"
    domain = f"{tenant.replace('-', '')[:10]}.myshopify.com"
    conn = _tenant_app_connection(tenant, actor)
    raw = json.dumps({"shop_id": shop_id, "shop_domain": domain, "customer": {"email": "must-not-persist@example.test"}}).encode()
    secret = "synthetic-webhook-secret"
    signature = base64.b64encode(hmac.new(secret.encode(), raw, hashlib.sha256).digest()).decode()
    headers = {
        "X-Shopify-Hmac-Sha256": signature,
        "X-Shopify-Shop-Domain": domain,
        "X-Shopify-Topic": "products/update",
        "X-Shopify-Webhook-Id": "delivery-hmac-1",
    }
    try:
        _verified(conn, tenant, source)
        conn.commit()
        _apply_context(conn, tenant, actor)
        first = authenticate_and_record_shopify_delivery(
            conn, tenant_id=tenant, source_id=source, raw_body=raw, headers=headers, client_secret=secret,
        )
        conn.commit()
        _apply_context(conn, tenant, actor)
        duplicate = authenticate_and_record_shopify_delivery(
            conn, tenant_id=tenant, source_id=source, raw_body=raw, headers=headers, client_secret=secret,
        )
        assert first["duplicate"] is False
        assert duplicate == {"delivery_receipt_id": first["delivery_receipt_id"], "duplicate": True}
        with conn.cursor() as cur:
            cur.execute(
                "SELECT payload_sha256,sanitized_metadata::text FROM keel_provider_delivery_receipts "
                "WHERE tenant_id=%s::uuid AND delivery_receipt_id=%s::uuid",
                (tenant, first["delivery_receipt_id"]),
            )
            payload_hash, metadata = cur.fetchone()
            assert payload_hash == hashlib.sha256(raw).hexdigest()
            assert "customer" not in metadata and "must-not-persist" not in metadata
        conn.rollback()
        _apply_context(conn, tenant, actor)
        bad_headers = {**headers, "X-Shopify-Hmac-Sha256": base64.b64encode(b"x" * 32).decode()}
        with pytest.raises(ShopifyError, match="signature is invalid"):
            authenticate_and_record_shopify_delivery(
                conn, tenant_id=tenant, source_id=source, raw_body=raw, headers=bad_headers, client_secret=secret,
            )
        conn.rollback()
        with admin.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM keel_provider_delivery_receipts WHERE tenant_id=%s AND provider_delivery_id='delivery-hmac-1'",
                (tenant,),
            )
            assert cur.fetchone()[0] == 1
    finally:
        conn.close()
