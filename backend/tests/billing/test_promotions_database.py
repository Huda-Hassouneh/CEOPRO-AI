"""Native promotion lifecycle, restricted-role RLS and migration contracts."""
import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import psycopg2
import pytest

from src.ai.billing import promotions


def _terms(**overrides):
    result = {
        "discount_type": "percent", "discount_value": "100", "currency": "USD",
        "starts_at": None, "expires_at": None, "max_uses": 2,
        "max_uses_per_tenant": 1, "invoice_scope": "initial_subscription",
        "stripe_coupon_id": "coupon_native_test", "stripe_promotion_code_id": "promo_native_test",
    }
    result.update(overrides)
    return result


@pytest.fixture
def active_promotion(owner_db, tenant, test_price):
    promotion_id, code, approver_id = str(uuid.uuid4()), "NATIVE_" + uuid.uuid4().hex[:12].upper(), str(uuid.uuid4())
    values = _terms(stripe_coupon_id="coupon_" + uuid.uuid4().hex,
                    stripe_promotion_code_id="promo_" + uuid.uuid4().hex)
    with owner_db.cursor() as cur:
        cur.execute("INSERT INTO public.users(user_id,email,password_hash) VALUES(%s,%s,'not-a-login-password')",
                    (approver_id, f"promotion-approver-{approver_id}@example.test"))
        cur.execute(
            "INSERT INTO public.billing_promotions(promotion_id,code,name,status,terms,stripe_coupon_id,"
            "stripe_promotion_code_id,approval_reference,approved_by,approved_at) "
            "VALUES(%s,%s,'Synthetic native test','active',%s::jsonb,%s,%s,'test-only approval',%s,NOW());",
            (promotion_id, code, json.dumps(values), values["stripe_coupon_id"],
             values["stripe_promotion_code_id"], approver_id),
        )
        cur.execute("INSERT INTO public.billing_promotion_plans(promotion_id,plan_key) VALUES(%s,%s);",
                    (promotion_id, test_price[0]))
    owner_db.commit()
    yield {"id": promotion_id, "code": code, "plan_key": test_price[0]}
    owner_db.rollback()
    with owner_db.cursor() as cur:
        cur.execute("DELETE FROM public.billing_promotion_redemptions WHERE promotion_id=%s;", (promotion_id,))
        cur.execute("DELETE FROM public.billing_promotion_plans WHERE promotion_id=%s;", (promotion_id,))
        cur.execute("DELETE FROM public.billing_promotions WHERE promotion_id=%s;", (promotion_id,))
        cur.execute("DELETE FROM public.users WHERE user_id=%s;", (approver_id,))
    owner_db.commit()


def _make_tenant(conn):
    tenant_id, user_id = str(uuid.uuid4()), str(uuid.uuid4())
    with conn.cursor() as cur:
        cur.execute("INSERT INTO companies(tenant_id,business_name,country_code,primary_currency) VALUES(%s,'Promotion fixture','JO','JOD')", (tenant_id,))
        cur.execute("INSERT INTO users(user_id,email,password_hash) VALUES(%s,%s,'not-a-login-password')", (user_id, f"promo-{user_id}@example.test"))
        cur.execute("INSERT INTO tenant_users(tenant_id,user_id,role_key) VALUES(%s,%s,'owner')", (tenant_id, user_id))
    return tenant_id, user_id


def _system_connection():
    return psycopg2.connect(os.environ["BILLING_TEST_DATABASE_URL"], connect_timeout=5,
                            gssencmode="disable", sslmode="disable")


def test_active_promotion_read_is_tenant_scoped_and_app_role_is_read_only(
    owner_db, tenant, active_promotion, billing_connections, monkeypatch
):
    other = _make_tenant(owner_db)
    owner_db.commit()
    try:
        conn = _system_connection()
        try:
            monkeypatch.setenv("KEEL_MANAGED_PROMOTIONS_ENABLED", "true")
            reservation = promotions.reserve(
                conn, tenant_id=tenant[0], actor_user_id=tenant[1], code=active_promotion["code"],
                plan_key=active_promotion["plan_key"], period_code="monthly", request_key="native-r1",
            )
            conn.commit()
        finally:
            conn.close()
        assert reservation["reused"] is False
        assert reservation["redemption_id"]

        first = billing_connections(tenant[0], tenant[1])
        try:
            with first.cursor() as cur:
                cur.execute("SELECT count(*) FROM public.billing_promotion_redemptions")
                assert cur.fetchone()[0] == 1
                cur.execute("SELECT count(*) FROM public.billing_promotions WHERE status='active'")
                assert cur.fetchone()[0] == 1
                with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                    cur.execute("UPDATE public.billing_promotion_redemptions SET state='settled'")
                first.rollback()
        finally:
            first.close()

        second = billing_connections(*other)
        try:
            with second.cursor() as cur:
                cur.execute("SELECT count(*) FROM public.billing_promotion_redemptions")
                assert cur.fetchone()[0] == 0
        finally:
            second.close()
    finally:
        with owner_db.cursor() as cur:
            cur.execute("DELETE FROM companies WHERE tenant_id=%s", (other[0],))
            cur.execute("DELETE FROM users WHERE user_id=%s", (other[1],))
        owner_db.commit()


def test_zero_total_paid_initial_invoice_settles_once_and_renewal_does_not_consume(
    owner_db, tenant, active_promotion, monkeypatch
):
    monkeypatch.setenv("KEEL_MANAGED_PROMOTIONS_ENABLED", "true")
    conn = _system_connection()
    try:
        reservation = promotions.reserve(
            conn, tenant_id=tenant[0], actor_user_id=tenant[1], code=active_promotion["code"],
            plan_key=active_promotion["plan_key"], period_code="monthly", request_key="native-settle",
        )
        conn.commit()
        rid = reservation["redemption_id"]
        failed_invoice = {"id": "in_native_zero", "billing_reason": "subscription_create", "status": "open",
                          "paid": False, "metadata": {"keel_promotion_redemption_id": rid}}
        promotions.invoice_event(conn, tenant_id=tenant[0], invoice=failed_invoice, subscription_id="sub_native",
                                 stripe_event_id="evt_failed_native", payment_succeeded=False)
        conn.commit()
        with conn.cursor() as cur:
            cur.execute("SELECT state FROM public.billing_promotion_redemptions WHERE redemption_id=%s", (rid,))
            assert cur.fetchone()[0] == "pending"
        promotions.attach_checkout(conn, tenant_id=tenant[0], redemption_id=rid, session_id="cs_native")
        promotions.checkout_completed(
            conn, session={"id": "cs_native", "mode": "subscription", "subscription": "sub_native",
                           "metadata": {"keel_promotion_redemption_id": rid}},
            tenant_id=tenant[0], stripe_event_id="evt_checkout_native",
        )
        conn.commit()
        with owner_db.cursor() as cur:
            cur.execute(
                "INSERT INTO public.billing_payments(tenant_id,stripe_invoice_id,stripe_subscription_id,amount,currency,status,paid_at) "
                "VALUES(%s,'in_native_zero','sub_native',0,'USD','succeeded',NOW());", (tenant[0],)
            )
        owner_db.commit()

        promotions.invoice_event(
            conn, tenant_id=tenant[0], invoice={"id": "in_native_renewal", "billing_reason": "subscription_cycle",
                                                "status": "paid", "paid": True},
            subscription_id="sub_native", stripe_event_id="evt_renewal_native", payment_succeeded=True,
        )
        conn.commit()
        with conn.cursor() as cur:
            cur.execute("SELECT state FROM public.billing_promotion_redemptions WHERE redemption_id=%s", (rid,))
            assert cur.fetchone()[0] == "pending"

        invoice = {"id": "in_native_zero", "billing_reason": "subscription_create", "status": "paid",
                   "paid": True, "amount_paid": 0, "metadata": {"keel_promotion_redemption_id": rid}}
        missing_reason = {key: value for key, value in invoice.items() if key != "billing_reason"}
        promotions.invoice_event(conn, tenant_id=tenant[0], invoice=missing_reason, subscription_id="sub_native",
                                 stripe_event_id="evt_missing_reason_native", payment_succeeded=True)
        conn.commit()
        with conn.cursor() as cur:
            cur.execute("SELECT state FROM public.billing_promotion_redemptions WHERE redemption_id=%s", (rid,))
            assert cur.fetchone()[0] == "reconciliation_required"
        promotions.invoice_event(conn, tenant_id=tenant[0], invoice=invoice, subscription_id="sub_native",
                                 stripe_event_id="evt_paid_native", payment_succeeded=True)
        conn.commit()
        promotions.invoice_event(conn, tenant_id=tenant[0], invoice=invoice, subscription_id="sub_native",
                                 stripe_event_id="evt_paid_native_replay", payment_succeeded=True)
        conn.commit()
        with conn.cursor() as cur:
            cur.execute("SELECT state,stripe_initial_invoice_id,settled_at FROM public.billing_promotion_redemptions WHERE redemption_id=%s", (rid,))
            state, invoice_id, settled_at = cur.fetchone()
            assert (state, invoice_id) == ("settled", "in_native_zero")
            assert settled_at is not None
            cur.execute("SELECT count(*) FROM public.billing_promotion_events WHERE redemption_id=%s AND event_type='initial_invoice_settled'", (rid,))
            assert cur.fetchone()[0] == 1
        # The signed webhook may persist/settle before the checkout request
        # thread attaches its provider response.
        promotions.attach_checkout(conn, tenant_id=tenant[0], redemption_id=rid, session_id="cs_native")
        conn.commit()
        with pytest.raises(promotions.PromotionError) as exhausted:
            promotions.reserve(conn, tenant_id=tenant[0], actor_user_id=tenant[1], code=active_promotion["code"],
                               plan_key=active_promotion["plan_key"], period_code="monthly", request_key="native-after-limit")
        conn.rollback()
        assert exhausted.value.code == "promotion_tenant_limit"
    finally:
        conn.close()


def test_durable_checkout_claim_blocks_unknown_repeat_but_webhook_can_recover(
    tenant, active_promotion, monkeypatch
):
    monkeypatch.setenv("KEEL_MANAGED_PROMOTIONS_ENABLED", "true")
    conn = _system_connection()
    try:
        reservation = promotions.reserve(
            conn, tenant_id=tenant[0], actor_user_id=tenant[1], code=active_promotion["code"],
            plan_key=active_promotion["plan_key"], period_code="monthly", request_key="native-unknown",
        )
        conn.commit()
        rid = reservation["redemption_id"]
        promotions.begin_checkout_request(conn, tenant_id=tenant[0], redemption_id=rid)
        conn.commit()
        with pytest.raises(promotions.PromotionError) as exc:
            promotions.begin_checkout_request(conn, tenant_id=tenant[0], redemption_id=rid)
        conn.rollback()
        assert exc.value.code == "promotion_reconciliation_required"
        promotions.checkout_completed(
            conn, session={"id": "cs_recovered", "mode": "subscription", "subscription": "sub_recovered",
                           "metadata": {"keel_promotion_redemption_id": rid}},
            tenant_id=tenant[0], stripe_event_id="evt_recovery_native",
        )
        conn.commit()
        with conn.cursor() as cur:
            cur.execute("SELECT stripe_checkout_session_id,stripe_subscription_id FROM public.billing_promotion_redemptions WHERE redemption_id=%s", (rid,))
            assert cur.fetchone() == ("cs_recovered", "sub_recovered")
    finally:
        conn.close()


def test_actor_deletion_anonymizes_event_and_tenant_deletion_cascades_events(
    owner_db, tenant, active_promotion, monkeypatch
):
    monkeypatch.setenv("KEEL_MANAGED_PROMOTIONS_ENABLED", "true")
    conn = _system_connection()
    try:
        reservation = promotions.reserve(
            conn, tenant_id=tenant[0], actor_user_id=tenant[1], code=active_promotion["code"],
            plan_key=active_promotion["plan_key"], period_code="monthly", request_key="native-delete",
        )
        conn.commit()
        rid = reservation["redemption_id"]
        with owner_db.cursor() as cur:
            cur.execute("DELETE FROM public.users WHERE user_id=%s", (tenant[1],))
            cur.execute("SELECT actor_user_id FROM public.billing_promotion_events WHERE redemption_id=%s", (rid,))
            assert cur.fetchone()[0] is None
        owner_db.commit()
        with owner_db.cursor() as cur:
            cur.execute("DELETE FROM public.companies WHERE tenant_id=%s", (tenant[0],))
            cur.execute("SELECT count(*) FROM public.billing_promotion_events WHERE redemption_id=%s", (rid,))
            assert cur.fetchone()[0] == 0
        owner_db.commit()
    finally:
        conn.close()


def test_platform_owner_draft_management_is_audited_and_never_activates(
    owner_db, tenant, test_price
):
    code = "DRAFT_" + uuid.uuid4().hex[:12].upper()
    promotion_id = None
    conn = _system_connection()
    try:
        with owner_db.cursor() as cur:
            cur.execute("INSERT INTO public.keel_platform_members(user_id,role_key,status) VALUES(%s,'owner','active')",
                        (tenant[1],))
        owner_db.commit()
        created = promotions.save_draft(
            conn, actor_user_id=tenant[1], code=code, name="Synthetic draft", description="",
            terms={"discount_type": "percent", "discount_value": 10}, plan_keys=[test_price[0]],
            reason="native draft-only test",
        )
        conn.commit()
        promotion_id = created["promotion_id"]
        assert created["status"] == "draft"
        assert created["eligible"] is False
        assert {"max_uses", "starts_at", "stripe_promotion_code_id"} <= set(created["missing_terms"])
        updated = promotions.save_draft(
            conn, actor_user_id=tenant[1], promotion_id=created["promotion_id"], code=code,
            name="Updated synthetic draft", description="updated", terms={"currency": "USD"},
            plan_keys=[test_price[0]], reason="native update test",
        )
        conn.commit()
        assert updated["status"] == "draft"
        disabled = promotions.disable(conn, actor_user_id=tenant[1], promotion_id=created["promotion_id"],
                                      reason="synthetic disable test")
        conn.commit()
        assert disabled["status"] == "disabled"
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM public.keel_platform_audit WHERE subject=%s AND left(action,10)='promotion_'",
                        (created["promotion_id"],))
            assert cur.fetchone()[0] == 3
            cur.execute("SELECT status FROM public.billing_promotions WHERE promotion_id=%s", (created["promotion_id"],))
            assert cur.fetchone()[0] == "disabled"
            cur.execute("DELETE FROM public.billing_promotion_plans WHERE promotion_id=%s", (created["promotion_id"],))
            cur.execute("DELETE FROM public.billing_promotions WHERE promotion_id=%s", (created["promotion_id"],))
        conn.commit()
    finally:
        conn.close()
        with owner_db.cursor() as cur:
            cur.execute("DELETE FROM public.keel_platform_members WHERE user_id=%s", (tenant[1],))
            if promotion_id:
                cur.execute("DELETE FROM public.billing_promotion_plans WHERE promotion_id=%s", (promotion_id,))
                cur.execute("DELETE FROM public.billing_promotions WHERE promotion_id=%s", (promotion_id,))
        owner_db.commit()


def test_active_promotion_constraint_rejects_null_required_terms(owner_db, tenant):
    promotion_id = str(uuid.uuid4())
    code = "INVALID_" + uuid.uuid4().hex[:12].upper()
    terms = _terms(discount_type=None)
    with pytest.raises(psycopg2.errors.CheckViolation):
        with owner_db.cursor() as cur:
            cur.execute(
                "INSERT INTO public.billing_promotions(promotion_id,code,name,status,terms,stripe_coupon_id,"
                "stripe_promotion_code_id,approval_reference,approved_by,approved_at) "
                "VALUES(%s,%s,'Invalid synthetic','active',%s::jsonb,%s,%s,'test approval',%s,NOW());",
                (promotion_id, code, json.dumps(terms), terms["stripe_coupon_id"],
                 terms["stripe_promotion_code_id"], tenant[1]),
            )
    owner_db.rollback()
    with owner_db.cursor() as cur:
        cur.execute("SELECT count(*) FROM public.billing_promotions WHERE promotion_id=%s", (promotion_id,))
        assert cur.fetchone()[0] == 0


def test_concurrent_tenant_reservations_respect_global_limit(owner_db, tenant, active_promotion, monkeypatch):
    monkeypatch.setenv("KEEL_MANAGED_PROMOTIONS_ENABLED", "true")
    with owner_db.cursor() as cur:
        cur.execute("UPDATE public.billing_promotions SET terms=jsonb_set(terms,'{max_uses}','1'::jsonb) WHERE promotion_id=%s",
                    (active_promotion["id"],))
    owner_db.commit()
    other = _make_tenant(owner_db)
    owner_db.commit()
    def attempt(tid, uid, key):
        conn = _system_connection()
        try:
            try:
                row = promotions.reserve(
                    conn, tenant_id=tid, actor_user_id=uid, code=active_promotion["code"],
                    plan_key=active_promotion["plan_key"], period_code="monthly", request_key=key,
                )
                conn.commit()
                return "reserved"
            except promotions.PromotionError as exc:
                conn.rollback()
                return exc.code
        finally:
            conn.close()
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda args: attempt(*args), [(*tenant, "race-a"), (*other, "race-b")]))
        assert results.count("reserved") == 1
        assert len(results) == 2
    finally:
        with owner_db.cursor() as cur:
            cur.execute("DELETE FROM companies WHERE tenant_id=%s", (other[0],))
            cur.execute("DELETE FROM users WHERE user_id=%s", (other[1],))
        owner_db.commit()


def test_eligibility_checks_plan_date_currency_and_custom_contract(owner_db, tenant, active_promotion, test_price, monkeypatch):
    monkeypatch.setenv("KEEL_MANAGED_PROMOTIONS_ENABLED", "true")
    conn = _system_connection()
    try:
        def set_terms(**changes):
            with owner_db.cursor() as cur:
                cur.execute("SELECT terms FROM public.billing_promotions WHERE promotion_id=%s", (active_promotion["id"],))
                terms = cur.fetchone()[0]
                if isinstance(terms, str): terms = json.loads(terms)
                terms.update(changes)
                cur.execute("UPDATE public.billing_promotions SET terms=%s::jsonb WHERE promotion_id=%s",
                            (json.dumps(terms), active_promotion["id"]))
            owner_db.commit()

        assert promotions.validate(conn, tenant[0], active_promotion["code"], "pro", "monthly")["reason"] == "not_eligible"
        set_terms(starts_at=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat())
        assert promotions.validate(conn, tenant[0], active_promotion["code"], active_promotion["plan_key"], "monthly")["reason"] == "not_eligible"
        set_terms(starts_at=None, expires_at=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat())
        assert promotions.validate(conn, tenant[0], active_promotion["code"], active_promotion["plan_key"], "monthly")["reason"] == "not_eligible"
        set_terms(expires_at=None, currency="JOD")
        assert promotions.validate(conn, tenant[0], active_promotion["code"], active_promotion["plan_key"], "monthly")["reason"] == "not_eligible"
        set_terms(currency="USD")
        assert promotions.validate(conn, tenant[0], active_promotion["code"], active_promotion["plan_key"], "monthly")["valid"] is True
        with owner_db.cursor() as cur:
            cur.execute("INSERT INTO public.tenant_custom_contracts(tenant_id,contract_ref,approved_by,reason) VALUES(%s,'synthetic-private','test-owner','test only')", (tenant[0],))
        owner_db.commit()
        assert promotions.validate(conn, tenant[0], active_promotion["code"], active_promotion["plan_key"], "monthly")["reason"] == "custom_contract_review"
    finally:
        conn.close()


def test_expired_checkout_rejects_reservation_without_consuming_campaign(owner_db, tenant, active_promotion, monkeypatch):
    monkeypatch.setenv("KEEL_MANAGED_PROMOTIONS_ENABLED", "true")
    conn = _system_connection()
    try:
        reservation = promotions.reserve(
            conn, tenant_id=tenant[0], actor_user_id=tenant[1], code=active_promotion["code"],
            plan_key=active_promotion["plan_key"], period_code="monthly", request_key="native-expired",
        )
        conn.commit()
        rid = reservation["redemption_id"]
        promotions.attach_checkout(conn, tenant_id=tenant[0], redemption_id=rid, session_id="cs_expired")
        promotions.checkout_expired(conn, session={"id": "cs_expired", "metadata": {
            "keel_promotion_redemption_id": rid}}, stripe_event_id="evt_expired_native")
        conn.commit()
        with conn.cursor() as cur:
            cur.execute("SELECT state FROM public.billing_promotion_redemptions WHERE redemption_id=%s", (rid,))
            assert cur.fetchone()[0] == "rejected"
        second = promotions.reserve(
            conn, tenant_id=tenant[0], actor_user_id=tenant[1], code=active_promotion["code"],
            plan_key=active_promotion["plan_key"], period_code="monthly", request_key="native-after-expired",
        )
        conn.commit()
        assert second["reused"] is False
    finally:
        conn.close()
