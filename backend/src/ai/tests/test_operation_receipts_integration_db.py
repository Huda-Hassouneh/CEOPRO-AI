"""Native PostgreSQL/RLS verification for ENT-008 Stage 1 receipts."""

import os
import uuid
from datetime import date, timedelta

import psycopg2
import pytest
import redis

from src.ai import db
from src.ai.core import operation_receipts
from src.ai.tests.test_rls_integration_db import _ensure_role_key, _insert_user
from src.market_scraper import data_access, enqueue, worker

ADMIN_DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")
APP_DB_PASSWORD = os.getenv("APP_DB_PASSWORD")

pytestmark = pytest.mark.skipif(
    not ADMIN_DATABASE_URL or not APP_DB_PASSWORD,
    reason="AI_TEST_DATABASE_URL and APP_DB_PASSWORD are required for native receipt verification",
)


@pytest.fixture
def admin_conn():
    conn = psycopg2.connect(ADMIN_DATABASE_URL)
    conn.autocommit = True
    yield conn
    conn.close()


@pytest.fixture
def tenant_users_source(admin_conn):
    tenant_a, tenant_b = str(uuid.uuid4()), str(uuid.uuid4())
    cursor = admin_conn.cursor()
    for tenant_id in (tenant_a, tenant_b):
        cursor.execute(
            "INSERT INTO companies (tenant_id,business_name,country_code,primary_currency) "
            "VALUES (%s,%s,'JO','JOD');",
            (tenant_id, f"Receipt test {tenant_id[:8]}"),
        )
    role = _ensure_role_key(cursor)
    actor_a, service_a, actor_b = (_insert_user(cursor, f"receipt-{n}") for n in ("a", "service", "b"))
    cursor.execute("INSERT INTO tenant_users (tenant_id,user_id,role_key) VALUES (%s,%s,%s),(%s,%s,%s),(%s,%s,%s);",
                   (tenant_a, actor_a, role, tenant_a, service_a, role, tenant_b, actor_b, role))
    today = date.today()
    current_start = today.replace(day=1)
    current_end = (current_start + timedelta(days=35)).replace(day=1) - timedelta(days=1)
    prior_start = current_start - timedelta(days=1)
    cursor.execute(
        "INSERT INTO tenant_plan_assignments "
        "(tenant_id,plan_key,status,current_period_start,current_period_end) VALUES (%s,'enterprise','active',%s,%s),"
        "(%s,'enterprise','active',%s,%s);",
        (tenant_a, prior_start, current_end, tenant_b, prior_start, current_end),
    )
    source_a, source_b = str(uuid.uuid4()), str(uuid.uuid4())
    for tenant_id, source_id, actor in ((tenant_a, source_a, actor_a), (tenant_b, source_b, actor_b)):
        cursor.execute(
            "INSERT INTO data_sources "
            "(source_id,tenant_id,source_name,source_type,source_url,collection_method,policy_status,"
            "approval_reference,approved_by,approved_at,privacy_reviewed_at) "
            "VALUES (%s,%s,'Receipt source','WEB_SCRAPE','https://example.invalid/p','WEB_SCRAPE','ALLOWED',"
            "'fixture approval',%s,NOW(),NOW());",
            (source_id, tenant_id, actor),
        )
    return {"tenant_a": tenant_a, "tenant_b": tenant_b, "actor_a": actor_a,
            "service_a": service_a, "actor_b": actor_b, "source_a": source_a, "source_b": source_b,
            "period_start": prior_start}


def _app_conn(tenant_id, actor_id):
    return db.app_role_connection(tenant_id, actor_id)


def test_receipt_is_idempotent_tenant_scoped_and_restricted_role(tenant_users_source):
    f = tenant_users_source
    conn = _app_conn(f["tenant_a"], f["actor_a"])
    try:
        first = operation_receipts.create_or_get_collection(conn, f["tenant_a"], f["source_a"], f["actor_a"])
        second = operation_receipts.create_or_get_collection(conn, f["tenant_a"], f["source_a"], f["actor_a"])
        assert first["receipt_id"] == second["receipt_id"]
        with conn.cursor() as cursor:
            cursor.execute("SELECT current_user, r.rolsuper, r.rolbypassrls FROM pg_roles r WHERE r.rolname=current_user;")
            role = cursor.fetchone()
            cursor.execute(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE oid='public.keel_operation_receipts'::regclass;"
            )
            rls = cursor.fetchone()
            cursor.execute(
                "SELECT has_table_privilege(current_user,'public.keel_operation_receipts','DELETE');"
            )
            can_delete = cursor.fetchone()[0]
        assert role == ("ceopro_app", False, False)
        assert rls == (True, True)
        assert can_delete is False
    finally:
        conn.close()

    other = _app_conn(f["tenant_b"], f["actor_b"])
    try:
        with other.cursor() as cursor:
            cursor.execute("SELECT 1 FROM public.keel_operation_receipts WHERE receipt_id=%s::uuid;",
                           (first["receipt_id"],))
            assert cursor.fetchone() is None
    finally:
        other.close()


def test_source_hard_delete_is_restricted_while_receipt_exists(tenant_users_source, admin_conn):
    f = tenant_users_source
    conn = _app_conn(f["tenant_a"], f["actor_a"])
    try:
        receipt = operation_receipts.create_or_get_collection(
            conn, f["tenant_a"], f["source_a"], f["actor_a"],
        )
    finally:
        conn.close()

    # The supported disconnect operation is a soft update; it must preserve
    # the source and its receipt. A hard delete must then fail at the FK.
    with admin_conn.cursor() as cursor:
        cursor.execute(
            "UPDATE public.data_sources SET is_active=FALSE, connection_credentials_vault=NULL "
            "WHERE tenant_id=%s::uuid AND source_id=%s::uuid;",
            (f["tenant_a"], f["source_a"]),
        )
        with pytest.raises(psycopg2.IntegrityError) as exc_info:
            cursor.execute(
                "DELETE FROM public.data_sources WHERE tenant_id=%s::uuid AND source_id=%s::uuid;",
                (f["tenant_a"], f["source_a"]),
            )
        assert exc_info.value.diag.constraint_name == "fk_keel_operation_receipt_source"

    with admin_conn.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM public.data_sources WHERE tenant_id=%s::uuid AND source_id=%s::uuid;",
            (f["tenant_a"], f["source_a"]),
        )
        assert cursor.fetchone()[0] == 1
        cursor.execute(
            "SELECT count(*) FROM public.keel_operation_receipts "
            "WHERE tenant_id=%s::uuid AND receipt_id=%s::uuid;",
            (f["tenant_a"], receipt["receipt_id"]),
        )
        assert cursor.fetchone()[0] == 1


def test_revoked_actor_is_denied_by_worker_before_provider(tenant_users_source, admin_conn):
    f = tenant_users_source
    conn = _app_conn(f["tenant_a"], f["actor_a"])
    receipt = operation_receipts.create_or_get_collection(conn, f["tenant_a"], f["source_a"], f["actor_a"])
    conn.close()
    admin_conn.cursor().execute(
        "UPDATE tenant_users SET removed_at=NOW() WHERE tenant_id=%s AND user_id=%s;",
        (f["tenant_a"], f["actor_a"]),
    )
    worker = _app_conn(f["tenant_a"], f["service_a"])
    try:
        with pytest.raises(operation_receipts.ReceiptAuthorizationError):
            operation_receipts.claim(worker, f["tenant_a"], receipt["receipt_id"], "worker-a")
        with worker.cursor() as cursor:
            cursor.execute("SELECT state,provider_started_at FROM public.keel_operation_receipts WHERE receipt_id=%s::uuid;",
                           (receipt["receipt_id"],))
            assert cursor.fetchone() == ("denied", None)
    finally:
        worker.close()


def test_period_change_denies_old_receipt_before_provider(tenant_users_source, admin_conn):
    f = tenant_users_source
    conn = _app_conn(f["tenant_a"], f["actor_a"])
    receipt = operation_receipts.create_or_get_collection(conn, f["tenant_a"], f["source_a"], f["actor_a"])
    conn.close()
    today_start = date.today().replace(day=1)
    admin_conn.cursor().execute(
        "UPDATE tenant_plan_assignments SET current_period_start=%s WHERE tenant_id=%s;",
        (today_start, f["tenant_a"]),
    )
    worker = _app_conn(f["tenant_a"], f["service_a"])
    try:
        with pytest.raises(operation_receipts.ReceiptAuthorizationError, match="period changed"):
            operation_receipts.claim(worker, f["tenant_a"], receipt["receipt_id"], "worker-period")
        with worker.cursor() as cursor:
            cursor.execute("SELECT state,provider_started_at FROM public.keel_operation_receipts WHERE receipt_id=%s::uuid;",
                           (receipt["receipt_id"],))
            assert cursor.fetchone() == ("denied", None)
    finally:
        worker.close()


def test_cancelled_subscription_denies_old_receipt_before_provider(tenant_users_source, admin_conn):
    f = tenant_users_source
    conn = _app_conn(f["tenant_a"], f["actor_a"])
    receipt = operation_receipts.create_or_get_collection(conn, f["tenant_a"], f["source_a"], f["actor_a"])
    conn.close()
    admin_conn.cursor().execute(
        "UPDATE tenant_plan_assignments SET status='cancelled' WHERE tenant_id=%s;",
        (f["tenant_a"],),
    )
    worker = _app_conn(f["tenant_a"], f["service_a"])
    try:
        with pytest.raises(operation_receipts.ReceiptAuthorizationError, match="not currently authorized"):
            operation_receipts.claim(worker, f["tenant_a"], receipt["receipt_id"], "worker-cancelled")
        with worker.cursor() as cursor:
            cursor.execute(
                "SELECT state,provider_started_at FROM public.keel_operation_receipts "
                "WHERE receipt_id=%s::uuid;",
                (receipt["receipt_id"],),
            )
            assert cursor.fetchone() == ("denied", None)
    finally:
        worker.close()


def test_no_target_completion_uses_authorized_fence_without_provider_start(
    tenant_users_source, admin_conn,
):
    f = tenant_users_source
    conn = _app_conn(f["tenant_a"], f["actor_a"])
    receipt = operation_receipts.create_or_get_collection(
        conn, f["tenant_a"], f["source_a"], f["actor_a"],
    )
    claimed = operation_receipts.claim(
        conn, f["tenant_a"], receipt["receipt_id"], "worker-no-targets",
    )
    job_id = data_access.create_ingestion_job(
        conn, f["tenant_a"], f["source_a"], receipt=claimed,
    )
    data_access.finish_ingestion_job(
        conn, f["tenant_a"], job_id, "COMPLETED", 0, 0,
        "No active product mappings were allocated.", receipt=claimed,
        receipt_allow_pre_provider=True,
    )
    operation_receipts.finish(conn, claimed, "completed")
    conn.close()

    with admin_conn.cursor() as cursor:
        cursor.execute(
            "SELECT state,provider_started_at,provider_outcome FROM public.keel_operation_receipts "
            "WHERE receipt_id=%s::uuid;",
            (receipt["receipt_id"],),
        )
        assert cursor.fetchone() == ("completed", None, "not_started")
        cursor.execute(
            "SELECT job_status FROM public.ingestion_jobs WHERE tenant_id=%s::uuid AND job_id=%s::uuid;",
            (f["tenant_a"], job_id),
        )
        assert cursor.fetchone() == ("COMPLETED",)


def test_concurrent_claim_has_one_winner_and_fencing_rejects_stale_generation(tenant_users_source, admin_conn):
    f = tenant_users_source
    conn = _app_conn(f["tenant_a"], f["actor_a"])
    receipt = operation_receipts.create_or_get_collection(conn, f["tenant_a"], f["source_a"], f["actor_a"])
    conn.close()
    results, errors = [], []

    def claim(worker_id):
        worker = _app_conn(f["tenant_a"], f["service_a"])
        try:
            results.append(operation_receipts.claim(worker, f["tenant_a"], receipt["receipt_id"], worker_id))
        except operation_receipts.ReceiptError as exc:
            errors.append(exc)
        finally:
            worker.close()

    import threading
    threads = [threading.Thread(target=claim, args=(f"worker-{i}",)) for i in range(2)]
    for thread in threads: thread.start()
    for thread in threads: thread.join()
    assert len(results) == 1
    assert len(errors) == 1

    active = results[0]
    active.update(source_id=f["source_a"], actor_user_id=f["actor_a"])
    conn = _app_conn(f["tenant_a"], f["service_a"])
    operation_receipts.begin_provider(conn, active)
    conn.close()
    admin_conn.cursor().execute(
        "UPDATE keel_operation_receipts SET lease_generation=lease_generation+1, lease_owner='replacement' "
        "WHERE receipt_id=%s;",
        (receipt["receipt_id"],),
    )
    conn = _app_conn(f["tenant_a"], f["service_a"])
    try:
        with pytest.raises(operation_receipts.ReceiptLeaseLost):
            operation_receipts.assert_fence(conn, active)
    finally:
        conn.close()


def test_expired_provider_send_becomes_reconciliation_required_not_retryable(tenant_users_source, admin_conn):
    f = tenant_users_source
    conn = _app_conn(f["tenant_a"], f["actor_a"])
    receipt = operation_receipts.create_or_get_collection(conn, f["tenant_a"], f["source_a"], f["actor_a"])
    claimed = operation_receipts.claim(conn, f["tenant_a"], receipt["receipt_id"], "worker-uncertain")
    operation_receipts.begin_provider(conn, claimed)
    conn.close()
    admin_conn.cursor().execute(
        "UPDATE keel_operation_receipts SET lease_expires_at=NOW()-INTERVAL '1 second' WHERE receipt_id=%s;",
        (receipt["receipt_id"],),
    )
    conn = _app_conn(f["tenant_a"], f["service_a"])
    try:
        result = operation_receipts.recover_expired(conn, f["tenant_a"])
        assert result == {"retryable": 0, "reconciliation_required": 1}
        with pytest.raises(operation_receipts.ReceiptError, match="reconciliation"):
            operation_receipts.claim(conn, f["tenant_a"], receipt["receipt_id"], "worker-retry")
        with conn.cursor() as cursor:
            cursor.execute("SELECT state,provider_outcome,lease_generation FROM keel_operation_receipts WHERE receipt_id=%s::uuid;",
                           (receipt["receipt_id"],))
            state, outcome, generation = cursor.fetchone()
        assert state == "reconciliation_required" and outcome == "unknown"
        assert generation == claimed["lease_generation"]
    finally:
        conn.close()


def test_expired_pre_provider_lease_is_requeued_and_claimable(
    tenant_users_source, admin_conn, monkeypatch,
):
    f = tenant_users_source
    conn = _app_conn(f["tenant_a"], f["actor_a"])
    receipt = operation_receipts.create_or_get_collection(
        conn, f["tenant_a"], f["source_a"], f["actor_a"],
    )
    first_claim = operation_receipts.claim(
        conn, f["tenant_a"], receipt["receipt_id"], "worker-before-provider",
    )
    conn.close()
    with admin_conn.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM public.keel_operation_receipts WHERE state IN ('dispatch_pending','retryable');"
        )
        pending_before = cursor.fetchone()[0]
    admin_conn.cursor().execute(
        "UPDATE keel_operation_receipts SET lease_expires_at=NOW()-INTERVAL '1 second' "
        "WHERE receipt_id=%s::uuid;",
        (receipt["receipt_id"],),
    )
    monkeypatch.setenv("SCRAPER_ACTOR_USER_ID", f["service_a"])

    class RecoveredDelivery:
        messages = []

        def xadd(self, stream, message):
            self.messages.append((stream, message))
            return "3-0"

    redis_client = RecoveredDelivery()
    assert worker.dispatch_pending_receipts(redis_client) == pending_before + 1
    recovered = [pair for pair in redis_client.messages if pair[1].get("receipt_id") == receipt["receipt_id"]]
    assert recovered == [(
        enqueue.RECEIPT_STREAM,
        {"tenant_id": f["tenant_a"], "receipt_id": receipt["receipt_id"], "source_id": f["source_a"]},
    )]

    retry = _app_conn(f["tenant_a"], f["service_a"])
    try:
        second_claim = operation_receipts.claim(
            retry, f["tenant_a"], receipt["receipt_id"], "worker-before-provider-retry",
        )
        assert second_claim["lease_generation"] == first_claim["lease_generation"] + 1
        with retry.cursor() as cursor:
            cursor.execute(
                "SELECT state,attempt_count,provider_started_at FROM public.keel_operation_receipts "
                "WHERE receipt_id=%s::uuid;",
                (receipt["receipt_id"],),
            )
            assert cursor.fetchone() == ("authorized", 2, None)
    finally:
        retry.close()


def test_enqueue_commits_receipt_before_redis_and_outbox_recovers_delivery(
    tenant_users_source, admin_conn, monkeypatch,
):
    f = tenant_users_source
    monkeypatch.setenv("SCRAPER_ACTOR_USER_ID", f["service_a"])
    with admin_conn.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM public.keel_operation_receipts WHERE state IN ('dispatch_pending','retryable');"
        )
        pending_before = cursor.fetchone()[0]

    class LostDelivery:
        def xadd(self, _stream, message):
            with admin_conn.cursor() as cursor:
                cursor.execute(
                    "SELECT state, actor_user_id FROM public.keel_operation_receipts "
                    "WHERE receipt_id=%s::uuid;",
                    (message["receipt_id"],),
                )
                row = cursor.fetchone()
            assert row == ("dispatch_pending", f["actor_a"])
            raise redis.RedisError("simulated Redis delivery failure")

    with pytest.raises(redis.RedisError, match="simulated Redis"):
        enqueue.enqueue_collection(
            f["tenant_a"], f["source_a"], redis_client=LostDelivery(),
            actor_user_id=f["actor_a"],
        )
    with admin_conn.cursor() as cursor:
        cursor.execute(
            "SELECT receipt_id FROM public.keel_operation_receipts "
            "WHERE tenant_id=%s::uuid AND source_id=%s::uuid AND state='dispatch_pending';",
            (f["tenant_a"], f["source_a"]),
        )
        receipt_id = str(cursor.fetchone()[0])

    class RecoveredDelivery:
        messages = []

        def xadd(self, stream, message):
            assert stream == enqueue.RECEIPT_STREAM
            self.messages.append((stream, message))
            return "2-0"

    redis_client = RecoveredDelivery()
    assert worker.dispatch_pending_receipts(redis_client) == pending_before + 1
    recovered = [pair for pair in redis_client.messages if pair[1].get("receipt_id") == receipt_id]
    assert len(recovered) == 1
    stream, message = recovered[0]
    assert stream == enqueue.RECEIPT_STREAM
    assert set(message) == {"tenant_id", "source_id", "receipt_id"}
    assert message["tenant_id"] == f["tenant_a"]
    assert message["source_id"] == f["source_a"]
    with admin_conn.cursor() as cursor:
        cursor.execute(
            "SELECT state FROM public.keel_operation_receipts WHERE receipt_id=%s::uuid;",
            (message["receipt_id"],),
        )
        assert cursor.fetchone() == ("queued",)
