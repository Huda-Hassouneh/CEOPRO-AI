"""Restricted-role native M97 tests; run only against disposable PostgreSQL."""
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse, urlunparse

import psycopg2
import pytest

from src.ai.extraction.typed_imports import create_import_revision, decide_import_review, get_import_draft, persist_import_draft
from src.ai.extraction.ingestion_pipeline import IngestionRowOutcome, IngestionSummary
from src.ai.extraction.row_parsing import RowParseResult
from src.ai.extraction.typed_imports import record_sales_extraction_draft

ADMIN_URL = os.getenv("AI_TEST_DATABASE_URL")
APP_PASSWORD = os.getenv("APP_DB_PASSWORD")
pytestmark = pytest.mark.skipif(not ADMIN_URL or not APP_PASSWORD, reason="native M97 DB vars not configured")


def _seed():
    admin = psycopg2.connect(ADMIN_URL)
    admin.autocommit = True
    tenant, owner, staff, source, job, product = [str(uuid.uuid4()) for _ in range(6)]
    with admin.cursor() as cur:
        cur.execute("ALTER ROLE ceopro_app WITH PASSWORD %s", (APP_PASSWORD,))
        cur.execute("INSERT INTO companies(tenant_id,business_name,country_code,primary_currency) VALUES(%s,'M97 fixture','JO','JOD')", (tenant,))
        cur.execute("INSERT INTO users(user_id,email,password_hash,full_name) VALUES(%s,%s,'x','owner'),(%s,%s,'x','staff')",
                    (owner,f'm97-{owner}@example.test',staff,f'm97-{staff}@example.test'))
        cur.execute("INSERT INTO tenant_users(tenant_id,user_id,role_key) VALUES(%s,%s,'owner'),(%s,%s,'staff')", (tenant,owner,tenant,staff))
        cur.execute("INSERT INTO data_sources(source_id,tenant_id,source_name,source_type,collector_key,collector_config,is_active) VALUES(%s,%s,'manual','CSV_UPLOAD','manual','{}',true)", (source,tenant))
        cur.execute("INSERT INTO ingestion_jobs(job_id,tenant_id,source_id,job_status,file_name) VALUES(%s,%s,%s,'COMPLETED','fixture.csv')", (job,tenant,source))
        cur.execute("INSERT INTO products(product_id,tenant_id,product_name,current_price,currency) VALUES(%s,%s,'{\"en\":\"Canonical\"}'::jsonb,4,'JOD')", (product,tenant))
        cur.execute("INSERT INTO inventory(tenant_id,product_id,stock_quantity) VALUES(%s,%s,37)", (tenant,product))
        cur.execute("INSERT INTO import_staging_rows(tenant_id,job_id,raw_payload_json,validation_status) VALUES(%s,%s,'{\"line\":1}'::jsonb,'VALID') RETURNING staging_row_id", (tenant,job))
        staging = cur.fetchone()[0]
    admin.close()
    parsed = urlparse(ADMIN_URL)
    app_url = urlunparse(parsed._replace(netloc=f'ceopro_app:{APP_PASSWORD}@{parsed.hostname}:{parsed.port}'))
    return {"tenant":tenant,"owner":owner,"staff":staff,"source":source,"job":job,"product":product,"staging":staging,"app_url":app_url}


def _app(seed, actor=None):
    conn=psycopg2.connect(seed["app_url"])
    with conn.cursor() as cur:
        cur.execute("SELECT set_config('app.current_tenant_id',%s,false)",(seed["tenant"],))
        cur.execute("SELECT set_config('app.current_user_id',%s,false)",(actor or seed["owner"],))
    conn.commit()
    return conn


def _row(seed, key="1"):
    return {"source_row_key":key,"staging_row_id":seed["staging"],"row_number":0,
        "typed_values":{"product_name":"Canonical","quantity":"2","unit_price":"4","currency":"JOD","transaction_date":"2026-10-20"}}


def _create(seed, conn, rows=None):
    return persist_import_draft(conn,tenant_id=seed["tenant"],actor_id=seed["owner"],source_id=seed["source"],job_id=seed["job"],
                                category="sales",rows=rows or [_row(seed)])


def test_batch_idempotency_tenant_rls_and_safe_read_view():
    s=_seed(); c=_app(s)
    try:
        first=_create(s,c); c.commit(); retry=_create(s,c)
        assert retry["duplicate"] and retry["batch_id"]==first["batch_id"]
        draft=get_import_draft(c,first["batch_id"])
        assert draft["rows"][0]["typed_values"]["quantity"]=="2" and "raw_payload_json" not in draft["rows"][0]
        with c.cursor() as q:
            q.execute("SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid='public.keel_import_draft_rows'::regclass")
            assert q.fetchone()==(True,True)
            q.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user")
            assert q.fetchone()==(False,False)
            q.execute("SELECT count(*) FROM keel_import_batches WHERE tenant_id=%s",(str(uuid.uuid4()),))
            assert q.fetchone()[0]==0
    finally: c.close()


def test_review_authorization_idempotency_and_no_canonical_posting():
    s=_seed(); c=_app(s); batch=_create(s,c); c.commit(); draft=get_import_draft(c,batch["batch_id"]); c.commit()
    d=decide_import_review(c,batch_id=batch["batch_id"],revision_id=draft["revision_id"],decision="approve",idempotency_key="approve-1",reason_code="validated")
    c.commit(); again=decide_import_review(c,batch_id=batch["batch_id"],revision_id=draft["revision_id"],decision="approve",idempotency_key="approve-1",reason_code="validated")
    assert d["decision_id"]==again["decision_id"] and again["duplicate"] and not d["canonical_write_performed"]
    with c.cursor() as q:
        q.execute("SELECT current_price FROM products WHERE tenant_id=%s AND product_id=%s",(s["tenant"],s["product"]))
        assert str(q.fetchone()[0])=="4.0000"
        with pytest.raises(psycopg2.errors.InsufficientPrivilege):
            q.execute("INSERT INTO keel_import_review_decisions(tenant_id) VALUES(%s)",(s["tenant"],))
    c.rollback(); c.close()
    staff=_app(s,s["staff"])
    try:
        with pytest.raises(psycopg2.errors.InsufficientPrivilege):
            decide_import_review(staff,batch_id=batch["batch_id"],revision_id=draft["revision_id"],decision="reject",idempotency_key="staff",reason_code="denied")
    finally: staff.rollback(); staff.close()


def test_invalid_rows_need_row_review_before_batch_approval():
    s=_seed(); c=_app(s); batch=_create(s,c,[{"source_row_key":"bad","staging_row_id":s["staging"],"typed_values":{"product_name":"x","quantity":0}}])
    c.commit(); draft=get_import_draft(c,batch["batch_id"]); c.commit(); row=draft["rows"][0]
    with pytest.raises(psycopg2.errors.CheckViolation):
        decide_import_review(c,batch_id=batch["batch_id"],revision_id=draft["revision_id"],decision="approve",idempotency_key="batch",reason_code="review")
    c.rollback()
    decide_import_review(c,batch_id=batch["batch_id"],revision_id=draft["revision_id"],row_id=row["draft_row_id"],decision="approve",idempotency_key="row",reason_code="explicit_review")
    c.commit()
    decide_import_review(c,batch_id=batch["batch_id"],revision_id=draft["revision_id"],decision="approve",idempotency_key="batch",reason_code="row-reviewed")
    c.commit(); c.close()


def test_invoice_and_inventory_persist_as_reviewable_drafts_without_canonical_writes():
    s=_seed(); c=_app(s)
    try:
        invoice=persist_import_draft(c,tenant_id=s["tenant"],actor_id=s["owner"],source_id=s["source"],job_id=s["job"],
            category="invoice",idempotency_key="invoice-draft",rows=[{"source_row_key":"inv:1:line:1",
                "typed_values":{"invoice_id":"INV-1","invoice_date":"2026-10-20","currency":"JOD",
                    "provider_product_id":"provider-product-9","quantity":"2","unit_price":"4"}}])
        inventory=persist_import_draft(c,tenant_id=s["tenant"],actor_id=s["owner"],source_id=s["source"],job_id=s["job"],
            category="inventory",idempotency_key="inventory-draft",rows=[{"source_row_key":"stock:1",
                "typed_values":{"provider_product_id":"provider-variant-2","provider_location_id":"location-1",
                    "quantity":"12","quantity_semantics":"on_hand","observed_at":"2026-10-20T12:00:00Z"}}])
        c.commit()
        invoice_view=get_import_draft(c,invoice["batch_id"]); inventory_view=get_import_draft(c,inventory["batch_id"])
        assert invoice_view["category"]=="invoice" and invoice_view["rows"][0]["validation_outcome"]=="review_required"
        assert inventory_view["category"]=="inventory" and inventory_view["rows"][0]["validation_outcome"]=="review_required"
        assert {f["code"] for f in invoice_view["rows"][0]["validation_findings"]}=={"provider_identity_requires_review"}
        assert {f["code"] for f in inventory_view["rows"][0]["validation_findings"]}=={
            "provider_identity_requires_review","provider_location_requires_review"}
        with c.cursor() as q:
            q.execute("SELECT count(*) FROM invoices WHERE tenant_id=%s",(s["tenant"],))
            assert q.fetchone()[0]==0
            q.execute("SELECT stock_quantity FROM inventory WHERE tenant_id=%s AND product_id=%s",(s["tenant"],s["product"]))
            assert q.fetchone()[0]==37
    finally:
        c.rollback(); c.close()


def test_existing_extraction_summary_is_persisted_as_sales_draft():
    s=_seed(); c=_app(s)
    summary=IngestionSummary(tenant_id=s["tenant"],job_id=s["job"],source_name="fixture.csv",
        template_mode="TEMPLATE_COMPLIANT",header_coverage_ratio=1.0,
        row_outcomes=[IngestionRowOutcome(row_index=0,staging_row_id=s["staging"],mode="TEMPLATE_COMPLIANT",
            parse_result=RowParseResult(tenant_id=s["tenant"],typed_fields={"product_name":"Canonical",
                "quantity":"2","unit_price":"4","currency":"JOD","transaction_date":"2026-10-20"}))])
    try:
        created=record_sales_extraction_draft(c,tenant_id=s["tenant"],actor_id=s["owner"],job_id=s["job"],summary=summary)
        c.commit(); view=get_import_draft(c,created["batch_id"])
        assert view["category"]=="sales" and view["rows"][0]["staging_row_id"]==s["staging"]
        assert view["rows"][0]["validation_outcome"]=="valid"
    finally:
        c.rollback(); c.close()


def test_revision_is_append_only_and_tenant_source_deletion_is_restricted():
    s=_seed(); c=_app(s); batch=_create(s,c); c.commit()
    changed=[_row(s)]; changed[0]["typed_values"]["quantity"]="3"
    first=create_import_revision(c,batch_id=batch["batch_id"],category="sales",rows=changed,idempotency_key="amend-1")
    c.commit(); second=create_import_revision(c,batch_id=batch["batch_id"],category="sales",rows=changed,idempotency_key="amend-1")
    assert first["revision_id"]==second["revision_id"] and second["duplicate"]
    with pytest.raises(psycopg2.errors.InsufficientPrivilege):
        with c.cursor() as q: q.execute("DELETE FROM keel_import_revisions WHERE tenant_id=%s",(s["tenant"],))
    c.rollback(); c.close()
    admin=psycopg2.connect(ADMIN_URL)
    try:
        with admin.cursor() as q:
            with pytest.raises(psycopg2.errors.ForeignKeyViolation): q.execute("DELETE FROM companies WHERE tenant_id=%s",(s["tenant"],))
        admin.rollback()
        with admin.cursor() as q:
            with pytest.raises(psycopg2.errors.ForeignKeyViolation): q.execute("DELETE FROM data_sources WHERE tenant_id=%s AND source_id=%s",(s["tenant"],s["source"]))
        admin.rollback()
    finally: admin.close()


def test_concurrent_duplicate_submission_creates_one_batch():
    s=_seed()
    def run():
        c=_app(s)
        try:
            result=_create(s,c); c.commit(); return result
        finally: c.close()
    with ThreadPoolExecutor(max_workers=4) as pool: results=list(pool.map(lambda _:run(),range(4)))
    assert len({x["batch_id"] for x in results})==1
    assert sum(not x["duplicate"] for x in results)==1
