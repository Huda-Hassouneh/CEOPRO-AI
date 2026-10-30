"""Native PostgreSQL/FORCE-RLS acceptance for the durable notification inbox."""
import os
import uuid

import psycopg2
import pytest
from fastapi.testclient import TestClient

from src.ai.tests.signup_helpers import create_verified_test_account

ADMIN_DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not ADMIN_DATABASE_URL or not os.getenv("APP_DB_PASSWORD"),
    reason="AI_TEST_DATABASE_URL and APP_DB_PASSWORD are required for PostgreSQL RLS tests",
)


def _admin(sql, params=(), *, commit=True):
    conn = psycopg2.connect(ADMIN_DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
        if commit:
            conn.commit()
        else:
            return conn
    except Exception:
        conn.rollback()
        raise
    finally:
        if commit:
            conn.close()


def _scalar(sql, params=()):
    conn = psycopg2.connect(ADMIN_DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()[0]
    finally:
        conn.close()


def _signup(client, label):
    safe_label = "".join(ch.lower() for ch in label if ch.isalnum())
    email = f"notify-{safe_label}+{uuid.uuid4().hex[:10]}@example.com"
    result = create_verified_test_account(client, {
        "full_name": label, "business_name": f"Notifications {label}",
        "email": email, "country_code": "JO", "primary_currency": "JOD",
        "password": "Notifications!Test2026",
    })
    return result, email


def _failed_job(tenant_id, *, rollback=False):
    source_id = str(uuid.uuid4())
    _admin("INSERT INTO data_sources (source_id,tenant_id,source_name,source_type) VALUES (%s,%s,'Notice test','FILE_UPLOAD')",
           (source_id, tenant_id))
    conn = psycopg2.connect(ADMIN_DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO ingestion_jobs (tenant_id,source_id,job_status,file_name) VALUES (%s,%s,'PROCESSING','notice.csv') RETURNING job_id",
                        (tenant_id, source_id))
            job_id = cur.fetchone()[0]
            cur.execute("UPDATE ingestion_jobs SET job_status='FAILED',ended_at=now() WHERE job_id=%s", (job_id,))
        if rollback:
            conn.rollback()
        else:
            conn.commit()
        return str(job_id), source_id
    finally:
        conn.close()


def _cleanup(tenant_ids, job_ids, source_ids, emails):
    for tenant_id in tenant_ids:
        _admin("DELETE FROM notification_outbox WHERE tenant_id=%s", (tenant_id,))
        _admin("DELETE FROM ingestion_jobs WHERE tenant_id=%s", (tenant_id,))
        _admin("DELETE FROM data_sources WHERE tenant_id=%s", (tenant_id,))
        _admin("DELETE FROM companies WHERE tenant_id=%s", (tenant_id,))
    for email in emails:
        _admin("DELETE FROM users WHERE email=%s", (email,))


def test_failed_import_notification_is_atomic_private_deduplicated_and_actionable():
    from src.ai.main import app

    client = TestClient(app)
    first, first_email = _signup(client, "Owner One")
    second, second_email = _signup(client, "Owner Two")
    tenant_a, tenant_b = first["tenant_id"], second["tenant_id"]
    auth_a = {"Authorization": f"Bearer {first['access_token']}"}
    auth_b = {"Authorization": f"Bearer {second['access_token']}"}
    job_id = source_id = rolled_job = rolled_source = None
    try:
        # A failed status transition inserts the notification in the same transaction.
        job_id, source_id = _failed_job(tenant_a)
        persisted = _scalar("SELECT count(*) FROM notification_outbox WHERE tenant_id=%s", (tenant_a,))
        response = client.get("/notifications", headers=auth_a)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] == 1 and body["unread_count"] == 1, f"database persisted {persisted} rows; inbox={body}"
        notice = body["items"][0]
        assert notice["event_key"] == f"import:failed:{job_id}"
        assert notice["payload"]["params"]["name"] == "notice.csv"
        assert notice["read_at"] is None and notice["dismissed_at"] is None
        smart_alerts = client.get("/alerts", headers=auth_a).json()
        assert "import_failed" not in {item["kind"] for item in smart_alerts["alerts"]}

        # Repeating the same transition and job identity cannot duplicate it.
        _admin("UPDATE ingestion_jobs SET job_status='PROCESSING' WHERE job_id=%s", (job_id,))
        _admin("UPDATE ingestion_jobs SET job_status='FAILED' WHERE job_id=%s", (job_id,))
        assert client.get("/notifications", headers=auth_a).json()["total"] == 1

        # Existing in-app category preferences govern producer fan-out.
        _admin("UPDATE users SET notification_preferences=%s::jsonb WHERE user_id=%s",
               ('{"in_app":{"data":false}}', first["user_id"]))
        _failed_job(tenant_a)
        assert client.get("/notifications", headers=auth_a).json()["total"] == 1

        # Other tenant and guessed IDs cannot read or mutate this recipient's row.
        assert client.get("/notifications", headers=auth_b).json()["total"] == 0
        assert client.post(f"/notifications/{notice['notification_id']}/read", headers=auth_b).status_code == 404

        assert client.post(f"/notifications/{notice['notification_id']}/read", headers=auth_a).json() == {"ok": True}
        assert client.get("/notifications", headers=auth_a).json()["unread_count"] == 0
        assert client.post(f"/notifications/{notice['notification_id']}/dismiss", headers=auth_a).json() == {"ok": True}
        active = client.get("/notifications", headers=auth_a).json()
        history = client.get("/notifications?include_dismissed=true", headers=auth_a).json()
        assert active["total"] == 0 and history["total"] == 1
        assert history["items"][0]["dismissed_at"] is not None

        # A notification written by a trigger is rolled back with its source event.
        rolled_job, rolled_source = _failed_job(tenant_a, rollback=True)
        assert client.get("/notifications?include_dismissed=true", headers=auth_a).json()["total"] == 1

        # ceopro_app cannot read diagnostic/raw table fields or write records directly.
        from src.ai import db
        app_conn = db.app_role_connection(tenant_a, first["user_id"])
        try:
            with app_conn.cursor() as cur:
                with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                    cur.execute("SELECT * FROM public.notification_outbox")
                app_conn.rollback()
                cur.execute("SELECT public.list_tenant_notifications(%s,20,NULL,NULL,true)", (tenant_a,))
                assert cur.fetchone()[0]["total"] == 1
            app_conn.commit()
        finally:
            app_conn.close()

        admin_conn = psycopg2.connect(ADMIN_DATABASE_URL)
        try:
            with admin_conn.cursor() as cur:
                cur.execute("SELECT rolsuper, rolbypassrls, rolcanlogin FROM pg_roles WHERE rolname='keel_notification_fn_owner'")
                assert cur.fetchone() == (False, False, False)
                cur.execute("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE oid='public.notification_outbox'::regclass")
                assert cur.fetchone() == (True, True)
                cur.execute("SELECT has_table_privilege('ceopro_app','public.notification_outbox','SELECT'), "
                            "has_function_privilege('ceopro_app','public.list_tenant_notifications(uuid,integer,timestamp with time zone,uuid,boolean)','EXECUTE')")
                assert cur.fetchone() == (False, True)
        finally:
            admin_conn.close()
    finally:
        _cleanup([tenant_a, tenant_b], [job_id, rolled_job], [source_id, rolled_source], [first_email, second_email])


def test_notification_enqueue_is_self_targeted_bounded_and_keyset_paginated():
    from src.ai.main import app
    from src.ai import db

    client = TestClient(app)
    first, first_email = _signup(client, "Page Owner")
    second, second_email = _signup(client, "Page Other")
    tenant_a, tenant_b = first["tenant_id"], second["tenant_id"]
    auth = {"Authorization": f"Bearer {first['access_token']}"}
    assert client.get("/notifications").status_code == 401
    try:
        conn = db.app_role_connection(tenant_a, first["user_id"])
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT public.enqueue_tenant_notification(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (tenant_a, first["user_id"], "test:page:stable", "import_failed", "data", "warning",
                     '{"params":{"name":"stable"}}', "test", "stable"),
                )
                original_id = cur.fetchone()[0]
                cur.execute(
                    "SELECT public.enqueue_tenant_notification(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (tenant_a, first["user_id"], "test:page:stable", "import_failed", "data", "warning",
                     '{"params":{"name":"changed"}}', "test", "stable"),
                )
                assert cur.fetchone()[0] == original_id, "same event key must return the original record"
                conn.commit()

                with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                    cur.execute(
                        "SELECT public.enqueue_tenant_notification(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (tenant_a, second["user_id"], "test:page:foreign", "import_failed", "data", "warning",
                         '{"params":{}}', "test", "foreign"),
                    )
                conn.rollback()
                with pytest.raises(psycopg2.errors.InvalidParameterValue):
                    cur.execute(
                        "SELECT public.enqueue_tenant_notification(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (tenant_a, first["user_id"], "test:page:oversized", "import_failed", "data", "warning",
                         '{"params":{"name":"' + ('x' * 17000) + '"}}', "test", "oversized"),
                    )
                conn.rollback()

                for index in range(22):
                    cur.execute(
                        "SELECT public.enqueue_tenant_notification(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (tenant_a, first["user_id"], f"test:page:{index:02d}", "import_failed", "data", "info",
                         '{"params":{"name":"page"}}', "test", str(index)),
                    )
                conn.commit()
        finally:
            conn.close()

        assert client.get("/notifications?limit=101", headers=auth).status_code == 422
        first_page = client.get("/notifications?limit=10", headers=auth).json()
        assert first_page["total"] == 23 and first_page["unread_count"] == 23
        ids = [item["notification_id"] for item in first_page["items"]]
        cursor = first_page["next_cursor"]
        while cursor:
            response = client.get("/notifications", params={
                "limit": 10, "before_created_at": cursor["created_at"],
                "before_notification_id": cursor["notification_id"],
            }, headers=auth)
            assert response.status_code == 200, response.text
            page = response.json()
            ids.extend(item["notification_id"] for item in page["items"])
            cursor = page["next_cursor"]
        assert len(ids) == len(set(ids)) == 23, "keyset pagination must not skip or repeat inbox rows"
        assert client.post("/notifications/read-all", headers=auth).json() == {"updated": 23}
        assert client.get("/notifications", headers=auth).json()["unread_count"] == 0

        # A removed membership loses inbox access immediately; restoring it is test cleanup.
        _admin("UPDATE tenant_users SET removed_at=now() WHERE tenant_id=%s AND user_id=%s", (tenant_a, first["user_id"]))
        assert client.get("/notifications", headers=auth).status_code == 403
        _admin("UPDATE tenant_users SET removed_at=NULL WHERE tenant_id=%s AND user_id=%s", (tenant_a, first["user_id"]))
    finally:
        _cleanup([tenant_a, tenant_b], [], [], [first_email, second_email])
