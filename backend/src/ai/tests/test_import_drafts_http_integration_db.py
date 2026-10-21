"""Authenticated HTTP M97 upload/preview/review test against disposable PostgreSQL."""
import os
import time
import uuid

import jwt
import psycopg2
import pytest
from fastapi.testclient import TestClient

DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")
APP_DB_PASSWORD = os.getenv("APP_DB_PASSWORD")
JWT_SECRET = os.getenv("JWT_SECRET", "test-jwt-secret-for-unit-tests")
pytestmark = pytest.mark.skipif(not DATABASE_URL or not APP_DB_PASSWORD,
                                reason="native M97 HTTP test requires disposable PostgreSQL credentials")


@pytest.fixture(autouse=True)
def _test_database_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL)
    monkeypatch.setenv("APP_DB_PASSWORD", APP_DB_PASSWORD)
    monkeypatch.setenv("JWT_SECRET", JWT_SECRET)
    # MinIO is optional for this API path; keep discovery's best-effort Redis
    # notification local and bounded without depending on a shared service.
    monkeypatch.delenv("MINIO_ENDPOINT", raising=False)
    monkeypatch.setenv("REDIS_HOST", "127.0.0.1")
    monkeypatch.setenv("REDIS_PORT", "1")
    monkeypatch.setenv("REDIS_SOCKET_CONNECT_TIMEOUT", "0.1")
    monkeypatch.setenv("FORECAST_AUTO_REFRESH", "0")


@pytest.fixture
def api():
    from src.ai.main import app
    return TestClient(app)


@pytest.fixture
def owner(admin_conn):
    tenant_id, user_id, staff_id = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    with admin_conn.cursor() as cur:
        cur.execute("INSERT INTO companies(tenant_id,business_name,country_code,primary_currency) VALUES(%s,'M97 API tenant','JO','JOD')", (tenant_id,))
        cur.execute("INSERT INTO users(user_id,email,password_hash,full_name) VALUES(%s,%s,'x','M97 owner')", (user_id, f"m97-api-{user_id}@example.test"))
        cur.execute("SELECT role_key FROM system_roles WHERE lower(role_key)='owner' LIMIT 1")
        role = cur.fetchone()
        if role is None:
            cur.execute("INSERT INTO system_roles(role_key,role_name) VALUES('OWNER','Owner')")
            role_key = "OWNER"
        else:
            role_key = role[0]
        cur.execute("INSERT INTO tenant_users(tenant_id,user_id,role_key) VALUES(%s,%s,%s)", (tenant_id,user_id,role_key))
        cur.execute("INSERT INTO users(user_id,email,password_hash,full_name) VALUES(%s,%s,'x','M97 staff')", (staff_id, f"m97-api-{staff_id}@example.test"))
        cur.execute("SELECT role_key FROM system_roles WHERE lower(role_key)='staff' LIMIT 1")
        staff_role = cur.fetchone()
        if staff_role is None:
            cur.execute("INSERT INTO system_roles(role_key,role_name) VALUES('STAFF','Staff')")
            staff_role_key = "STAFF"
        else:
            staff_role_key = staff_role[0]
        cur.execute("INSERT INTO tenant_users(tenant_id,user_id,role_key) VALUES(%s,%s,%s)", (tenant_id,staff_id,staff_role_key))
    token = jwt.encode({"tenant_id": tenant_id, "user_id": user_id, "exp": int(time.time()) + 3600}, JWT_SECRET, algorithm="HS256")
    staff_token = jwt.encode({"tenant_id": tenant_id, "user_id": staff_id, "exp": int(time.time()) + 3600}, JWT_SECRET, algorithm="HS256")
    return {"tenant": tenant_id, "user": user_id, "headers": {"Authorization": f"Bearer {token}"},
            "staff_headers": {"Authorization": f"Bearer {staff_token}"}}


@pytest.fixture
def admin_conn():
    c = psycopg2.connect(DATABASE_URL)
    c.autocommit = True
    try:
        yield c
    finally:
        c.close()


CSV = b"product_name,quantity,unit_price,currency,transaction_date\nM97 API Widget,2,4.25,JOD,2026-10-20\n"


def test_authenticated_upload_preview_and_review_are_separate_from_posting(api, admin_conn, owner):
    upload = api.post("/extraction/upload", files={"file": ("api.csv", CSV, "text/csv")}, headers=owner["headers"])
    assert upload.status_code == 200, upload.text
    created = upload.json()["import_draft"]
    assert created["review_only"] is True and created["canonical_write_performed_by_review"] is False
    batch_id, revision_id = created["batch_id"], created["revision_id"]

    listed = api.get("/extraction/import-drafts?category=sales", headers=owner["headers"])
    assert listed.status_code == 200 and any(item["batch_id"] == batch_id for item in listed.json()["items"])
    detail = api.get(f"/extraction/import-drafts/{batch_id}", headers=owner["headers"])
    assert detail.status_code == 200
    assert detail.json()["rows"][0]["validation_outcome"] == "valid"
    assert detail.json()["rows"][0]["canonical_posting_status"] == "committed"

    with admin_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM transactions WHERE tenant_id=%s", (owner["tenant"],))
        before_review = cur.fetchone()[0]
    review = {"revision_id": revision_id, "decision": "approve", "idempotency_key": "http-review-one",
              "reason_code": "owner_checked"}
    denied = api.post(f"/extraction/import-drafts/{batch_id}/reviews", json={**review, "idempotency_key": "staff-review"},
                      headers=owner["staff_headers"])
    assert denied.status_code == 403
    first = api.post(f"/extraction/import-drafts/{batch_id}/reviews", json=review, headers=owner["headers"])
    replay = api.post(f"/extraction/import-drafts/{batch_id}/reviews", json=review, headers=owner["headers"])
    assert first.status_code == 200 and replay.status_code == 200
    assert first.json()["canonical_write_performed"] is False
    assert replay.json()["duplicate"] is True and replay.json()["decision_id"] == first.json()["decision_id"]
    with admin_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM transactions WHERE tenant_id=%s", (owner["tenant"],))
        assert cur.fetchone()[0] == before_review

    revisions = api.get(f"/extraction/import-drafts/{batch_id}/revisions", headers=owner["headers"])
    history = api.get(f"/extraction/import-drafts/{batch_id}/reviews", headers=owner["headers"])
    assert revisions.status_code == history.status_code == 200
    assert len(revisions.json()["revisions"]) == 1 and len(history.json()["reviews"]) == 1


def test_import_preview_auth_and_tenant_isolation(api, admin_conn, owner):
    upload = api.post("/extraction/upload", files={"file": ("private.csv", CSV, "text/csv")}, headers=owner["headers"])
    batch_id = upload.json()["import_draft"]["batch_id"]
    assert api.get(f"/extraction/import-drafts/{batch_id}").status_code == 401

    tenant_id, user_id = str(uuid.uuid4()), str(uuid.uuid4())
    with admin_conn.cursor() as cur:
        cur.execute("INSERT INTO companies(tenant_id,business_name,country_code,primary_currency) VALUES(%s,'Other M97 tenant','JO','JOD')", (tenant_id,))
        cur.execute("INSERT INTO users(user_id,email,password_hash,full_name) VALUES(%s,%s,'x','Other owner')", (user_id, f"m97-api-{user_id}@example.test"))
        cur.execute("SELECT role_key FROM system_roles WHERE lower(role_key)='owner' LIMIT 1")
        role_key = cur.fetchone()[0]
        cur.execute("INSERT INTO tenant_users(tenant_id,user_id,role_key) VALUES(%s,%s,%s)", (tenant_id,user_id,role_key))
    token = jwt.encode({"tenant_id": tenant_id, "user_id": user_id, "exp": int(time.time()) + 3600}, JWT_SECRET, algorithm="HS256")
    response = api.get(f"/extraction/import-drafts/{batch_id}", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 404


def test_invoice_and_inventory_review_routes_remain_review_only(api, admin_conn, owner):
    from src.ai import db
    from src.ai.extraction.typed_imports import persist_import_draft

    source_id, job_id = str(uuid.uuid4()), str(uuid.uuid4())
    with admin_conn.cursor() as cur:
        cur.execute("INSERT INTO data_sources(source_id,tenant_id,source_name,source_type,collector_key,collector_config,is_active) VALUES(%s,%s,'typed fixture','CSV_UPLOAD','manual','{}',true)", (source_id,owner["tenant"]))
        cur.execute("INSERT INTO ingestion_jobs(job_id,tenant_id,source_id,job_status,file_name) VALUES(%s,%s,%s,'COMPLETED','typed.csv')", (job_id,owner["tenant"],source_id))
    writer = db.app_role_connection(owner["tenant"], owner["user"])
    try:
        invoice = persist_import_draft(writer, tenant_id=owner["tenant"], actor_id=owner["user"], source_id=source_id,
            job_id=job_id, category="invoice", rows=[{"source_row_key":"invoice-1","typed_values":{
                "invoice_id":"INV-1","invoice_date":"2026-10-20","currency":"JOD","product_name":"Widget",
                "quantity":"2","unit_price":"4.25"}}])
        writer.commit()
        inventory = persist_import_draft(writer, tenant_id=owner["tenant"], actor_id=owner["user"], source_id=source_id,
            job_id=job_id, category="inventory", rows=[{"source_row_key":"stock-1","typed_values":{
                "provider_product_id":"wc-product-1","quantity":"12","quantity_semantics":"stock_quantity"}}],
            idempotency_key="inventory-import")
        writer.commit()
    finally:
        writer.close()

    invoice_view = api.get(f"/extraction/import-drafts/{invoice['batch_id']}", headers=owner["headers"]).json()
    inventory_view = api.get(f"/extraction/import-drafts/{inventory['batch_id']}", headers=owner["headers"]).json()
    assert invoice_view["category"] == "invoice" and inventory_view["category"] == "inventory"
    assert inventory_view["rows"][0]["validation_outcome"] == "review_required"
    approved_invoice = api.post(f"/extraction/import-drafts/{invoice['batch_id']}/reviews", headers=owner["headers"], json={
        "revision_id": invoice["revision_id"], "decision":"approve", "idempotency_key":"invoice-review",
        "reason_code":"invoice_checked"})
    approved_inventory_row = api.post(f"/extraction/import-drafts/{inventory['batch_id']}/reviews", headers=owner["headers"], json={
        "revision_id": inventory["revision_id"], "row_id":inventory_view["rows"][0]["draft_row_id"],
        "decision":"approve", "idempotency_key":"inventory-row-review", "reason_code":"identity_held"})
    assert approved_invoice.status_code == approved_inventory_row.status_code == 200
    assert approved_invoice.json()["canonical_write_performed"] is False
    assert approved_inventory_row.json()["canonical_write_performed"] is False
    assert approved_inventory_row.json()["posting_status"] == "not_committed"


def test_repeated_upload_keeps_canonical_sales_idempotent_and_each_attempt_reviewable(api, admin_conn, owner):
    first = api.post("/extraction/upload", files={"file": ("repeat-a.csv", CSV, "text/csv")}, headers=owner["headers"])
    second = api.post("/extraction/upload", files={"file": ("repeat-b.csv", CSV, "text/csv")}, headers=owner["headers"])
    assert first.status_code == second.status_code == 200
    assert first.json()["import_draft"]["batch_id"] != second.json()["import_draft"]["batch_id"]
    assert second.json()["promotion"]["rows_duplicate"] == 1
    with admin_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM transactions WHERE tenant_id=%s", (owner["tenant"],))
        assert cur.fetchone()[0] == 1
    for response in (first, second):
        view = api.get(f"/extraction/import-drafts/{response.json()['import_draft']['batch_id']}", headers=owner["headers"])
        assert view.status_code == 200 and len(view.json()["rows"]) == 1


def test_large_multi_batch_upload_creates_complete_preview(api, owner):
    lines = ["product_name,quantity,unit_price,currency,transaction_date"]
    lines.extend(f"Bulk Widget,{i},1.00,JOD,2026-10-20" for i in range(1, 502))
    payload = ("\n".join(lines) + "\n").encode()
    uploaded = api.post("/extraction/upload", files={"file": ("bulk.csv", payload, "text/csv")}, headers=owner["headers"])
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["rows_processed"] == 501
    detail = api.get(f"/extraction/import-drafts/{uploaded.json()['import_draft']['batch_id']}", headers=owner["headers"])
    assert detail.status_code == 200
    assert len(detail.json()["rows"]) == 501
    assert detail.json()["ingestion_status"] == "COMPLETED"


def test_partial_validation_upload_is_visible_and_not_falsely_completed(api, owner):
    bad = b"product_name,quantity,unit_price,currency,transaction_date\nWidget,-3,1.00,JOD,2026-10-20\n"
    uploaded = api.post("/extraction/upload", files={"file": ("invalid-row.csv", bad, "text/csv")}, headers=owner["headers"])
    assert uploaded.status_code == 200
    body = uploaded.json()
    assert body["rows_partial"] == 1
    detail = api.get(f"/extraction/import-drafts/{body['import_draft']['batch_id']}", headers=owner["headers"])
    assert detail.status_code == 200 and detail.json()["ingestion_status"] == "FAILED"
    assert detail.json()["review_status"] == "review_required"
    assert detail.json()["rows"][0]["canonical_posting_status"] == "not_committed"
    assert detail.json()["rows"][0]["validation_findings"]
