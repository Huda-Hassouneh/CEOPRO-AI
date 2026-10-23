"""Native restricted-role coverage for connector staging/promotion and source rotation."""
import os
import uuid
from datetime import date, timedelta

import psycopg2
import pytest
from cryptography.fernet import Fernet

from src.ai import db
from src.ai.core import operation_receipts
from src.ai.extraction import ingestion_pipeline, promotion
from src.market_scraper import data_access
from src.ai.tests.test_rls_integration_db import _ensure_role_key, _insert_user

ADMIN_DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")
APP_DB_PASSWORD = os.getenv("APP_DB_PASSWORD")
pytestmark = pytest.mark.skipif(
    not ADMIN_DATABASE_URL or not APP_DB_PASSWORD,
    reason="AI_TEST_DATABASE_URL and APP_DB_PASSWORD are required for restricted-role connector verification",
)


@pytest.fixture(autouse=True)
def _vault_key(monkeypatch):
    monkeypatch.setenv("CREDENTIAL_VAULT_MASTER_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("KEEL_ENT008_STAGE2_ENABLED", "true")


@pytest.fixture
def admin_conn():
    conn = psycopg2.connect(ADMIN_DATABASE_URL)
    conn.autocommit = True
    yield conn
    conn.close()


def _seed_tenant(admin_conn, label, collector_key="api_connector"):
    tenant_id, actor_id, source_id = str(uuid.uuid4()), None, str(uuid.uuid4())
    with admin_conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO companies (tenant_id,business_name,country_code,primary_currency) VALUES (%s,%s,'JO','JOD');",
            (tenant_id, f"Phase 3B {label} {tenant_id[:8]}"),
        )
        role = _ensure_role_key(cursor)
        actor_id = _insert_user(cursor, f"phase3b-{label}")
        cursor.execute("INSERT INTO tenant_users (tenant_id,user_id,role_key) VALUES (%s,%s,%s);",
                       (tenant_id, actor_id, role))
        today = date.today()
        period_start = today.replace(day=1)
        period_end = (period_start + timedelta(days=35)).replace(day=1) - timedelta(days=1)
        cursor.execute(
            "INSERT INTO tenant_plan_assignments (tenant_id,plan_key,status,current_period_start,current_period_end) "
            "VALUES (%s,'enterprise','active',%s,%s);", (tenant_id, period_start, period_end),
        )
        cursor.execute(
            "INSERT INTO data_sources (source_id,tenant_id,source_name,source_type,collector_key,collector_config,"
            "policy_status,is_active,approval_reference,approved_by,approved_at,privacy_reviewed_at) "
            "VALUES (%s,%s,%s,'OWN_SYSTEM_CONNECTOR',%s,%s::jsonb,'ALLOWED',TRUE,'test self-service approval',%s,NOW(),NOW());",
            (source_id, tenant_id, f"{label} connector", collector_key,
             '{"base_url":"https://pos.example.invalid/sales","field_mapping":{"product_name":"product_name","quantity":"quantity","unit_price":"unit_price","currency":"currency","transaction_date":"transaction_date"}}', actor_id),
        )
    data_access.set_source_credentials(admin_conn, tenant_id, source_id, {"api_key": f"synthetic-{label}"})
    return {"tenant_id": tenant_id, "actor_id": actor_id, "source_id": source_id}


def _cleanup(admin_conn, tenants):
    ids = [tenant["tenant_id"] for tenant in tenants]
    if not ids:
        return
    with admin_conn.cursor() as cursor:
        # Failed connector operations may now emit durable M103 notifications.
        cursor.execute("DELETE FROM public.notification_outbox WHERE tenant_id=ANY(%s::uuid[]);", (ids,))
        cursor.execute("DELETE FROM public.keel_operation_receipts WHERE tenant_id=ANY(%s::uuid[]);", (ids,))
        cursor.execute("DELETE FROM public.invoice_items WHERE tenant_id=ANY(%s::uuid[]);", (ids,))
        cursor.execute("DELETE FROM public.invoices WHERE tenant_id=ANY(%s::uuid[]);", (ids,))
        cursor.execute("DELETE FROM public.transactions WHERE tenant_id=ANY(%s::uuid[]);", (ids,))
        cursor.execute("DELETE FROM public.products WHERE tenant_id=ANY(%s::uuid[]);", (ids,))
        cursor.execute("DELETE FROM public.import_staging_rows WHERE tenant_id=ANY(%s::uuid[]);", (ids,))
        cursor.execute("DELETE FROM public.ingestion_jobs WHERE tenant_id=ANY(%s::uuid[]);", (ids,))
        cursor.execute("DELETE FROM public.companies WHERE tenant_id=ANY(%s::uuid[]);", (ids,))


def test_restricted_role_stages_and_promotes_only_its_tenant(admin_conn):
    tenant_a = _seed_tenant(admin_conn, "a")
    tenant_b = _seed_tenant(admin_conn, "b")
    try:
        with admin_conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO products (tenant_id,product_name,current_price,currency,source) "
                "VALUES (%s,%s,5,'JOD','IMPORTED') RETURNING product_id;",
                (tenant_b["tenant_id"], '{"en":"Shared Item"}'),
            )
            product_b = str(cursor.fetchone()[0])
        conn = db.app_role_connection(tenant_a["tenant_id"], tenant_a["actor_id"])
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT current_user,rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user;")
                assert cursor.fetchone() == ("ceopro_app", False, False)
                cursor.execute("SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid='public.import_staging_rows'::regclass;")
                assert cursor.fetchone() == (True, True)
                cursor.execute("SELECT 1 FROM products WHERE tenant_id=%s::uuid AND product_id=%s::uuid;",
                               (tenant_b["tenant_id"], product_b))
                assert cursor.fetchone() is None
                cursor.execute("SELECT 1 FROM data_sources WHERE tenant_id=%s::uuid AND source_id=%s::uuid;",
                               (tenant_b["tenant_id"], tenant_b["source_id"]))
                assert cursor.fetchone() is None

            job_id = data_access.create_ingestion_job(conn, tenant_a["tenant_id"], tenant_a["source_id"])
            headers = ["product_name", "quantity", "unit_price", "currency", "transaction_date"]
            rows = [{"product_name": "Shared Item", "quantity": "2", "unit_price": "3.50",
                     "currency": "JOD", "transaction_date": "2026-10-20"}]
            summary = ingestion_pipeline.process_records(
                tenant_a["tenant_id"], job_id, "restricted-role connector", headers, rows,
                trusted_field_mapping={header: header for header in headers}, conn=conn,
            )
            assert summary.rows_processed == 1
            result = promotion.promote_ingested_rows(conn, tenant_a["tenant_id"], job_id, summary, user_id=tenant_a["actor_id"])
            conn.commit()
            assert result.products_created == 1
            assert result.rows_promoted == 1
        finally:
            conn.close()
        with admin_conn.cursor() as cursor:
            cursor.execute("SELECT tenant_id,product_name->>'en' FROM products WHERE tenant_id=ANY(%s::uuid[]) ",
                           ([tenant_a["tenant_id"], tenant_b["tenant_id"]],))
            products = cursor.fetchall()
            assert (tenant_b["tenant_id"], "Shared Item") in products
            assert sum(1 for row in products if row[0] == tenant_a["tenant_id"] and row[1] == "Shared Item") == 1
    finally:
        _cleanup(admin_conn, [tenant_a, tenant_b])


@pytest.mark.parametrize("source_change", ["credential_rotation", "disconnect"])
def test_source_change_fences_stale_connector_stage_commit(admin_conn, source_change):
    tenant = _seed_tenant(admin_conn, "rotation")
    conn = db.app_role_connection(tenant["tenant_id"], tenant["actor_id"])
    try:
        intent = operation_receipts.create_or_get_operation(
            conn, operation_receipts.SCHEDULED_CONNECTOR_SYNC, tenant["tenant_id"], "source",
            tenant["source_id"], tenant["actor_id"], "service", {},
        )
        receipt = operation_receipts.claim(conn, tenant["tenant_id"], intent["receipt_id"], "phase3b-test-worker")
        job_id = data_access.create_or_reuse_receipt_ingestion_job(conn, tenant["tenant_id"], tenant["source_id"], receipt)
        assert receipt["ingestion_job_id"] == job_id
        loaded = data_access.load_source(conn, tenant["tenant_id"], tenant["source_id"])
        receipt["source_execution_fingerprint"] = loaded["source_execution_fingerprint"]
        operation_receipts.begin_provider(conn, receipt)
        if source_change == "credential_rotation":
            data_access.set_source_credentials(admin_conn, tenant["tenant_id"], tenant["source_id"], {"api_key":"rotated-synthetic"})
        else:
            with admin_conn.cursor() as cursor:
                cursor.execute("UPDATE data_sources SET is_active=FALSE WHERE tenant_id=%s::uuid AND source_id=%s::uuid;",
                               (tenant["tenant_id"], tenant["source_id"]))


        headers = ["product_name", "quantity", "unit_price", "currency", "transaction_date"]
        rows = [{"product_name":"Must Not Stage", "quantity":"1", "unit_price":"2.00",
                 "currency":"JOD", "transaction_date":"2026-10-20"}]
        with pytest.raises(operation_receipts.ReceiptSourceChanged):
            ingestion_pipeline.process_records(
                tenant["tenant_id"], job_id, "stale connector", headers, rows,
                trusted_field_mapping={header: header for header in headers},
                conn=operation_receipts.FencedConnection(conn, receipt), commit_every=1,
            )
        with conn.cursor() as cursor:
            cursor.execute("SELECT state,lease_owner,lease_generation,(lease_expires_at > NOW()) FROM public.keel_operation_receipts WHERE tenant_id=%s::uuid AND receipt_id=%s::uuid;", (tenant["tenant_id"], receipt["receipt_id"]))
            owned_state = cursor.fetchone()
        assert owned_state == ("provider_started", receipt["worker_id"], receipt["lease_generation"], True)
        assert data_access.fail_source_changed_ingestion_job(conn, tenant["tenant_id"], receipt) is True
        operation_receipts.finish(conn, receipt, "failed", "SOURCE_CONFIGURATION_CHANGED")
        with admin_conn.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM import_staging_rows WHERE tenant_id=%s::uuid AND job_id=%s::uuid;",
                           (tenant["tenant_id"], job_id))
            assert cursor.fetchone()[0] == 0
            cursor.execute("SELECT job_status FROM ingestion_jobs WHERE tenant_id=%s::uuid AND job_id=%s::uuid;",
                           (tenant["tenant_id"], job_id))
            assert cursor.fetchone()[0] == "FAILED"
    finally:
        conn.close()
        _cleanup(admin_conn, [tenant])

def test_disconnected_source_is_not_sent_to_provider(admin_conn):
    tenant = _seed_tenant(admin_conn, "pre-provider-disconnect")
    conn = db.app_role_connection(tenant["tenant_id"], tenant["actor_id"])
    try:
        intent = operation_receipts.create_or_get_operation(
            conn, operation_receipts.SCHEDULED_CONNECTOR_SYNC, tenant["tenant_id"], "source",
            tenant["source_id"], tenant["actor_id"], "service", {},
        )
        receipt = operation_receipts.claim(conn, tenant["tenant_id"], intent["receipt_id"], "phase3b-pre-provider-worker")
        job_id = data_access.create_or_reuse_receipt_ingestion_job(conn, tenant["tenant_id"], tenant["source_id"], receipt)
        loaded = data_access.load_source(conn, tenant["tenant_id"], tenant["source_id"])
        receipt["source_execution_fingerprint"] = loaded["source_execution_fingerprint"]
        with admin_conn.cursor() as cursor:
            cursor.execute("UPDATE data_sources SET is_active=FALSE WHERE tenant_id=%s::uuid AND source_id=%s::uuid;",
                           (tenant["tenant_id"], tenant["source_id"]))
        with pytest.raises(operation_receipts.ReceiptSourceChanged):
            operation_receipts.begin_provider(conn, receipt)
        assert data_access.fail_source_changed_ingestion_job(conn, tenant["tenant_id"], receipt) is True
        operation_receipts.finish(conn, receipt, "failed", "SOURCE_CONFIGURATION_CHANGED")
        with admin_conn.cursor() as cursor:
            cursor.execute("SELECT job_status FROM ingestion_jobs WHERE tenant_id=%s::uuid AND job_id=%s::uuid;",
                           (tenant["tenant_id"], job_id))
            assert cursor.fetchone()[0] == "FAILED"
            cursor.execute("SELECT state,provider_outcome FROM public.keel_operation_receipts WHERE tenant_id=%s::uuid AND receipt_id=%s::uuid;",
                           (tenant["tenant_id"], receipt["receipt_id"]))
            assert cursor.fetchone() == ("failed", "not_started")
    finally:
        conn.close()
        _cleanup(admin_conn, [tenant])
