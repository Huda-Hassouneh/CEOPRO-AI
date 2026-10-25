"""Native PostgreSQL checks for the Phase 2C quote lifecycle."""
import uuid
import hashlib
import json

import psycopg2
import pytest

from src.ai.billing import custom_offers


@pytest.fixture
def quote_actors(owner_db):
    tenant_a, user_a = str(uuid.uuid4()), str(uuid.uuid4())
    tenant_b, user_b = str(uuid.uuid4()), str(uuid.uuid4())
    created_platform = False
    created_platform_user = False
    with owner_db.cursor() as cur:
        cur.execute("SELECT tenant_id FROM keel_platform_workspace WHERE singleton=TRUE")
        workspace = cur.fetchone()
        if workspace:
            platform_tenant = str(workspace[0])
            cur.execute("SELECT user_id FROM keel_platform_members WHERE role_key='owner' AND status='active'")
            operator = cur.fetchone()
            if not operator:
                raise AssertionError("Disposable schema has a platform workspace but no active test owner")
            platform_user = str(operator[0])
            cur.execute("SELECT 1 FROM tenant_users WHERE tenant_id=%s AND user_id=%s AND removed_at IS NULL",
                        (platform_tenant, platform_user))
            if not cur.fetchone():
                cur.execute("INSERT INTO tenant_users(tenant_id,user_id,role_key) VALUES(%s,%s,'owner')",
                            (platform_tenant, platform_user))
                created_platform_user = True
        else:
            platform_tenant, platform_user = str(uuid.uuid4()), str(uuid.uuid4())
            cur.execute("INSERT INTO companies(tenant_id,business_name,country_code,primary_currency) VALUES(%s,'Quote Platform','JO','JOD')", (platform_tenant,))
            cur.execute("INSERT INTO users(user_id,email,password_hash) VALUES(%s,%s,'test-only')",
                        (platform_user, f"quote-platform-{platform_user}@example.test"))
            cur.execute("INSERT INTO tenant_users(tenant_id,user_id,role_key) VALUES(%s,%s,'owner')", (platform_tenant, platform_user))
            cur.execute("INSERT INTO keel_platform_workspace(singleton,tenant_id) VALUES(TRUE,%s)", (platform_tenant,))
            cur.execute("INSERT INTO keel_platform_members(user_id,role_key,status) VALUES(%s,'owner','active')", (platform_user,))
            created_platform = True
        for tid, name in ((tenant_a, "Quote Tenant A"), (tenant_b, "Quote Tenant B")):
            cur.execute("INSERT INTO companies(tenant_id,business_name,country_code,primary_currency) VALUES(%s,%s,'JO','JOD')", (tid, name))
        for uid, prefix in ((user_a, "quote-a"), (user_b, "quote-b")):
            cur.execute("INSERT INTO users(user_id,email,password_hash) VALUES(%s,%s,'test-only')", (uid, f"{prefix}-{uid}@example.test"))
        cur.execute("INSERT INTO tenant_users(tenant_id,user_id,role_key) VALUES(%s,%s,'owner')", (tenant_a, user_a))
        cur.execute("INSERT INTO tenant_users(tenant_id,user_id,role_key) VALUES(%s,%s,'owner')", (tenant_b, user_b))
    yield {"platform_tenant": platform_tenant, "platform_user": platform_user,
           "tenant_a": tenant_a, "user_a": user_a, "tenant_b": tenant_b, "user_b": user_b}
    with owner_db.cursor() as cur:
        cur.execute("DELETE FROM billing_webhook_events WHERE tenant_id = ANY(%s::uuid[])", ([tenant_a, tenant_b],))
        cur.execute("DELETE FROM companies WHERE tenant_id = ANY(%s::uuid[])", ([tenant_a, tenant_b],))
        cur.execute("DELETE FROM users WHERE user_id = ANY(%s::uuid[])", ([user_a, user_b],))
        if created_platform:
            cur.execute("DELETE FROM keel_platform_workspace WHERE tenant_id=%s", (platform_tenant,))
            cur.execute("DELETE FROM keel_platform_members WHERE user_id=%s", (platform_user,))
            cur.execute("DELETE FROM companies WHERE tenant_id=%s", (platform_tenant,))
            cur.execute("DELETE FROM users WHERE user_id=%s", (platform_user,))
        elif created_platform_user:
            cur.execute("DELETE FROM tenant_users WHERE tenant_id=%s AND user_id=%s", (platform_tenant, platform_user))


def _conn(billing_connections, actors, who="platform"):
    if who == "platform":
        return billing_connections(actors["platform_tenant"], actors["platform_user"])
    if who == "tenant_a":
        return billing_connections(actors["tenant_a"], actors["user_a"])
    return billing_connections(actors["tenant_b"], actors["user_b"])


def _draft(conn, actors, *, key=None, terms=None, economics=None):
    return custom_offers.create_draft(
        conn,
        tenant_id=actors["tenant_a"], customer_user_id=actors["user_a"],
        idempotency_key=key or "quote-" + uuid.uuid4().hex,
        configuration={"mode": "SYNTHETIC_TEST_ONLY"}, feature_quantities={"tracked_products": 1},
        commercial_terms=terms or {}, economic_inputs=economics or {}, fx_evidence={},
    )


def _active_synthetic_policy(platform_conn):
    policy = custom_offers.pricing_admin_command(platform_conn, "policy_create", {
        "target_gross_margin": "0.25", "enforce_vendor_cost_ratio_floor": False,
        "fixed_platform_fee_usd": "0", "upward_rounding_increment_usd": "0",
        "monthly_shared_infrastructure_cost_usd": "0", "active_paying_tenant_count": 1,
        "approval_evidence": "SYNTHETIC_TEST_ONLY: not a commercial policy",
    })
    custom_offers.pricing_admin_command(platform_conn, "policy_activate", {
        "policy_version_id": policy["policy_version_id"],
        "approval_evidence": "SYNTHETIC_TEST_ONLY: disposable database fixture",
    })
    return str(policy["policy_version_id"])


def _submit_and_price(platform_conn, quote, *, submit=True):
    if submit:
        custom_offers.transition(platform_conn, "submit", tenant_id=None, quote_id=str(quote["quote_id"]),
                                 expected_revision=int(quote.get("revision_number", 1)),
                                 idempotency_key="submit-" + uuid.uuid4().hex)
        platform_conn.commit()
    policy_id = _active_synthetic_policy(platform_conn)
    payload = {"pricingStatus": "calculated", "pricingPolicyVersionId": policy_id,
               "calculation": {"recommendedPrice": "12.00"}, "configuration": {"testFixture": "SYNTHETIC_TEST_ONLY"},
               "featureQuantities": {"tracked_products": 1}, "rates": []}
    payload["calculationHash"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    custom_offers.attach_pricing_snapshot(platform_conn, quote_id=str(quote["quote_id"]), snapshot=payload)
    platform_conn.commit()


def _approve_and_accept(platform_conn, customer_conn, actors, quote):
    _submit_and_price(platform_conn, quote)
    custom_offers.transition(platform_conn, "approve", tenant_id=None, quote_id=str(quote["quote_id"]),
                             expected_revision=1, idempotency_key="approve-" + uuid.uuid4().hex,
                             approval_reference="synthetic-test-approval")
    platform_conn.commit()
    return custom_offers.transition(customer_conn, "accept", tenant_id=actors["tenant_a"],
                                    quote_id=str(quote["quote_id"]), expected_revision=1,
                                    idempotency_key="accept-" + uuid.uuid4().hex)


def test_quote_lifecycle_is_tenant_scoped_immutable_and_non_activating(quote_actors, owner_db, billing_connections):
    actors = quote_actors
    before = {}
    with owner_db.cursor() as cur:
        for table in ("billing_subscriptions", "billing_payments", "tenant_plan_assignments", "usage_ledger", "tenant_credit_balances"):
            cur.execute(f"SELECT count(*) FROM {table} WHERE tenant_id=%s", (actors["tenant_a"],))
            before[table] = cur.fetchone()[0]
    platform_conn = _conn(billing_connections, actors)
    customer_conn = _conn(billing_connections, actors, "tenant_a")
    try:
        quote = _draft(platform_conn, actors, terms={"test_only": True}, economics={"test_fixture": "not a commercial rate"})
        platform_conn.commit()
        submitted = custom_offers.transition(platform_conn, "submit", tenant_id=None, quote_id=str(quote["quote_id"]),
                                               expected_revision=1, idempotency_key="submit-1")
        platform_conn.commit()
        assert submitted["state"] == "submitted"
        _submit_and_price(platform_conn, quote, submit=False)
        approved = custom_offers.transition(platform_conn, "approve", tenant_id=None, quote_id=str(quote["quote_id"]),
                                              expected_revision=1, idempotency_key="approve-1",
                                              approval_reference="synthetic-test-approval")
        platform_conn.commit()
        assert approved["state"] == "approved"
        with pytest.raises(psycopg2.Error):
            with owner_db.cursor() as cur:
                cur.execute("UPDATE billing_custom_quote_revisions SET feature_quantities=jsonb_build_object('tamper', true) WHERE revision_id=%s",
                            (quote["revision_id"],))
        owner_db.rollback()
        customer_view = custom_offers.quote_detail(customer_conn, str(quote["quote_id"]))
        assert customer_view and customer_view["state"] == "approved"
        assert "economic_inputs" not in customer_view and "fx_evidence" not in customer_view
        accepted = custom_offers.transition(customer_conn, "accept", tenant_id=actors["tenant_a"],
                                            quote_id=str(quote["quote_id"]), expected_revision=1,
                                            idempotency_key="accept-1")
        customer_conn.commit()
        accepted_again = custom_offers.transition(customer_conn, "accept", tenant_id=actors["tenant_a"],
                                                  quote_id=str(quote["quote_id"]), expected_revision=1,
                                                  idempotency_key="accept-replay")
        customer_conn.commit()
        assert accepted["state"] == "accepted" and accepted["access_activated"] is False
        assert accepted_again["idempotent"] is True and accepted_again["access_activated"] is False
        detail = custom_offers.quote_detail(owner_db, str(quote["quote_id"]), include_private=True)
        assert [event["action"] for event in detail["events"]] == ["draft_created", "submitted", "pricing_calculated", "approved", "accepted"]
        with owner_db.cursor() as cur:
            for table in before:
                cur.execute(f"SELECT count(*) FROM {table} WHERE tenant_id=%s", (actors["tenant_a"],))
                assert cur.fetchone()[0] == before[table]
    finally:
        platform_conn.close()
        customer_conn.close()


def test_quote_tenant_isolation_direct_writes_and_secret_rejection(quote_actors, billing_connections):
    actors = quote_actors
    platform_conn = _conn(billing_connections, actors)
    other_conn = _conn(billing_connections, actors, "tenant_b")
    try:
        quote = _draft(platform_conn, actors, terms={"test_only": True}, economics={"test_fixture": True})
        platform_conn.commit()
        assert custom_offers.quote_detail(other_conn, str(quote["quote_id"])) is None
        tenant_conn = _conn(billing_connections, actors, "tenant_a")
        try:
            _approve_and_accept(platform_conn, tenant_conn, actors, quote)
            tenant_conn.commit()
        finally:
            tenant_conn.close()
        platform_conn.commit()
        with pytest.raises(custom_offers.CustomOfferError) as cross_tenant:
            custom_offers.transition(other_conn, "accept", tenant_id=actors["tenant_b"],
                                     quote_id=str(quote["quote_id"]), expected_revision=1,
                                     idempotency_key="cross-tenant-accept")
        assert cross_tenant.value.status == 404
        other_conn.rollback()
        with other_conn.cursor() as cur, pytest.raises(psycopg2.errors.InsufficientPrivilege):
            cur.execute("INSERT INTO billing_custom_quotes(tenant_id,idempotency_key,request_fingerprint) VALUES(%s,%s,%s)",
                        (actors["tenant_b"], "direct", "0" * 64))
        other_conn.rollback()
        with pytest.raises(custom_offers.CustomOfferError):
            custom_offers.create_draft(
                platform_conn, tenant_id=actors["tenant_a"], customer_user_id=actors["user_a"],
                idempotency_key="secret-reject", configuration={"nested": [{"access_token": "forbidden"}]},
                feature_quantities={"tracked_products": 1}, commercial_terms={}, economic_inputs={}, fx_evidence={},
            )
        platform_conn.rollback()
    finally:
        platform_conn.close()
        other_conn.close()


def test_customer_request_operator_offer_revision_and_acceptance_are_non_activating(
    quote_actors, owner_db, billing_connections
):
    actors = quote_actors
    customer_conn = _conn(billing_connections, actors, "tenant_a")
    platform_conn = _conn(billing_connections, actors)
    try:
        before = {}
        with owner_db.cursor() as cur:
            for table in ("billing_subscriptions", "billing_payments", "tenant_plan_assignments", "usage_ledger", "tenant_credit_balances"):
                cur.execute(f"SELECT count(*) FROM {table} WHERE tenant_id=%s", (actors["tenant_a"],))
                before[table] = cur.fetchone()[0]

        request = custom_offers.request_quote(
            customer_conn, tenant_id=actors["tenant_a"], customer_user_id=actors["user_a"],
            idempotency_key="customer-request-1",
            configuration={"refreshFrequency": "daily", "enabledFeatures": ["competitor_management"]},
            feature_quantities={"tracked_competitors": 2},
        )
        customer_conn.commit()
        replay = custom_offers.request_quote(
            customer_conn, tenant_id=actors["tenant_a"], customer_user_id=actors["user_a"],
            idempotency_key="customer-request-1",
            configuration={"refreshFrequency": "daily", "enabledFeatures": ["competitor_management"]},
            feature_quantities={"tracked_competitors": 2},
        )
        customer_conn.commit()
        assert request["state"] == "submitted" and request["price_calculated"] is False
        assert replay["idempotent"] is True

        customer_view = custom_offers.quote_detail(customer_conn, str(request["quote_id"]))
        assert customer_view["state"] == "submitted"
        assert "economic_inputs" not in customer_view
        assert [str(row["quote_id"]) for row in custom_offers.quote_list(customer_conn, actors["tenant_a"])] == [request["quote_id"]]
        other_customer_conn = _conn(billing_connections, actors, "tenant_b")
        try:
            assert custom_offers.quote_list(other_customer_conn, actors["tenant_b"]) == []
        finally:
            other_customer_conn.close()

        queue = custom_offers.admin_quote_list(platform_conn, state="submitted")
        platform_conn.commit()
        assert any(row["quoteId"] == str(request["quote_id"]) for row in queue)

        revision = custom_offers.create_revision(
            platform_conn, quote_id=str(request["quote_id"]), expected_revision=1,
            idempotency_key="offer-revision-2",
            configuration={"refreshFrequency": "daily", "enabledFeatures": ["competitor_management"]},
            feature_quantities={"tracked_competitors": 2}, commercial_terms={"test_only": "SYNTHETIC_TEST_ONLY"},
            economic_inputs={"source": "synthetic-test-contract"}, fx_evidence={},
        )
        platform_conn.commit()
        assert revision["revision_number"] == 2
        _submit_and_price(platform_conn, {"quote_id": request["quote_id"], "revision_number": 2}, submit=False)
        approved = custom_offers.transition(
            platform_conn, "approve", tenant_id=None, quote_id=str(request["quote_id"]),
            expected_revision=2, idempotency_key="approve-request-2",
            approval_reference="synthetic-test-approval-only",
        )
        platform_conn.commit()
        assert approved["state"] == "approved"

        accepted = custom_offers.transition(
            customer_conn, "accept", tenant_id=actors["tenant_a"],
            quote_id=str(request["quote_id"]), expected_revision=2,
            idempotency_key="accept-request-2",
        )
        customer_conn.commit()
        assert accepted["state"] == "accepted" and accepted["access_activated"] is False

        detail = custom_offers.quote_detail(owner_db, str(request["quote_id"]), include_private=True)
        assert [event["action"] for event in detail["events"]] == ["submitted", "revision_created", "pricing_calculated", "approved", "accepted"]
        with owner_db.cursor() as cur:
            for table, count in before.items():
                cur.execute(f"SELECT count(*) FROM {table} WHERE tenant_id=%s", (actors["tenant_a"],))
                assert cur.fetchone()[0] == count

        staff_id = str(uuid.uuid4())
        with owner_db.cursor() as cur:
            cur.execute("INSERT INTO users(user_id,email,password_hash) VALUES(%s,%s,'test-only')",
                        (staff_id, f"quote-staff-{staff_id}@example.test"))
            cur.execute("INSERT INTO tenant_users(tenant_id,user_id,role_key) VALUES(%s,%s,'staff')",
                        (actors["tenant_a"], staff_id))
        owner_db.commit()
        staff_conn = billing_connections(actors["tenant_a"], staff_id)
        try:
            with pytest.raises(custom_offers.CustomOfferError) as error:
                custom_offers.request_quote(
                    staff_conn, tenant_id=actors["tenant_a"], customer_user_id=staff_id,
                    idempotency_key="staff-request-denied", configuration={}, feature_quantities={"tracked_products": 1},
                )
            assert error.value.status == 403
        finally:
            staff_conn.close()
            with owner_db.cursor() as cur:
                cur.execute("DELETE FROM tenant_users WHERE tenant_id=%s AND user_id=%s", (actors["tenant_a"], staff_id))
                cur.execute("DELETE FROM users WHERE user_id=%s", (staff_id,))
            owner_db.commit()
    finally:
        customer_conn.close()
        platform_conn.close()


def test_quote_idempotency_revision_conflicts_and_checkout_identity_only(quote_actors, billing_connections):
    actors = quote_actors
    platform_conn = _conn(billing_connections, actors)
    customer_conn = _conn(billing_connections, actors, "tenant_a")
    try:
        key = "stable-" + uuid.uuid4().hex
        quote = _draft(platform_conn, actors, key=key, terms={"test_only": True}, economics={"test_fixture": True})
        platform_conn.commit()
        replay = _draft(platform_conn, actors, key=key, terms={"test_only": True}, economics={"test_fixture": True})
        assert replay["quote_id"] == quote["quote_id"] and replay["idempotent"]
        platform_conn.commit()
        with pytest.raises(custom_offers.CustomOfferError):
            _draft(platform_conn, actors, key=key, terms={"different": True}, economics={"test_fixture": True})
        platform_conn.rollback()
        revision = custom_offers.create_revision(
            platform_conn, quote_id=str(quote["quote_id"]), expected_revision=1, idempotency_key="revision-1",
            configuration={"new": True}, feature_quantities={"tracked_products": 1}, commercial_terms={"test_only": True},
            economic_inputs={"test_fixture": True}, fx_evidence={},
        )
        platform_conn.commit()
        replay_revision = custom_offers.create_revision(
            platform_conn, quote_id=str(quote["quote_id"]), expected_revision=1, idempotency_key="revision-1",
            configuration={"new": True}, feature_quantities={"tracked_products": 1}, commercial_terms={"test_only": True},
            economic_inputs={"test_fixture": True}, fx_evidence={},
        )
        assert replay_revision["revision_id"] == revision["revision_id"] and replay_revision["idempotent"]
        platform_conn.commit()
        from concurrent.futures import ThreadPoolExecutor
        def create_same_revision_concurrently():
            conn = _conn(billing_connections, actors)
            try:
                result = custom_offers.create_revision(
                    conn, quote_id=str(quote["quote_id"]), expected_revision=2,
                    idempotency_key="revision-concurrent", configuration={"concurrent": True},
                    feature_quantities={"tracked_products": 1}, commercial_terms={"test_only": True},
                    economic_inputs={"test_fixture": True}, fx_evidence={},
                )
                conn.commit()
                return result
            finally:
                conn.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            revision_results = list(pool.map(lambda _: create_same_revision_concurrently(), range(2)))
        assert len({str(result["revision_id"]) for result in revision_results}) == 1
        assert sum(not result["idempotent"] for result in revision_results) == 1
        def replay_concurrently():
            conn = _conn(billing_connections, actors)
            try:
                result = custom_offers.create_draft(
                    conn, tenant_id=actors["tenant_a"], customer_user_id=actors["user_a"],
                    idempotency_key=key, configuration={"mode": "SYNTHETIC_TEST_ONLY"},
                    feature_quantities={"tracked_products": 1}, commercial_terms={"test_only": True},
                    economic_inputs={"test_fixture": True}, fx_evidence={},
                )
                conn.commit()
                return result
            finally:
                conn.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: replay_concurrently(), range(2)))
        assert {str(x["quote_id"]) for x in results} == {str(quote["quote_id"])}
        with pytest.raises(custom_offers.CustomOfferError):
            custom_offers.create_revision(
                platform_conn, quote_id=str(quote["quote_id"]), expected_revision=1, idempotency_key="revision-stale",
                configuration={}, feature_quantities={"tracked_products": 1}, commercial_terms={}, economic_inputs={}, fx_evidence={},
            )
        platform_conn.rollback()
        accepted_quote = _draft(platform_conn, actors, key="accepted-" + uuid.uuid4().hex,
                                terms={"test_only": True}, economics={"test_fixture": True})
        platform_conn.commit()
        accepted = _approve_and_accept(platform_conn, customer_conn, actors, accepted_quote)
        customer_conn.commit()
        assert accepted["access_activated"] is False
        checkout_key = "checkout-" + uuid.uuid4().hex
        attempt = custom_offers.prepare_checkout_attempt(
            customer_conn, tenant_id=actors["tenant_a"], quote_id=str(accepted_quote["quote_id"]),
            idempotency_key=checkout_key,
        )
        customer_conn.commit()
        replay_attempt = custom_offers.prepare_checkout_attempt(
            customer_conn, tenant_id=actors["tenant_a"], quote_id=str(accepted_quote["quote_id"]),
            idempotency_key=checkout_key,
        )
        customer_conn.commit()
        assert attempt["state"] == "prepared" and attempt["provider_called"] is False
        assert replay_attempt["provider_called"] is False and replay_attempt["idempotent"] is True
        assert replay_attempt["attempt_id"] == attempt["attempt_id"]
    finally:
        platform_conn.close()
        customer_conn.close()


def test_quote_rejection_and_owner_approval_enforces_fourteen_day_offer(quote_actors, billing_connections):
    from datetime import timedelta

    actors = quote_actors
    platform_conn = _conn(billing_connections, actors)
    customer_conn = _conn(billing_connections, actors, "tenant_a")
    try:
        rejected = _draft(platform_conn, actors, terms={"test_only": True}, economics={"test_fixture": True})
        platform_conn.commit()
        _submit_and_price(platform_conn, rejected)
        custom_offers.transition(platform_conn, "approve", tenant_id=None, quote_id=str(rejected["quote_id"]),
                                 expected_revision=1, idempotency_key="reject-approve",
                                 approval_reference="synthetic-test-approval")
        platform_conn.commit()
        rejected_result = custom_offers.transition(customer_conn, "reject", tenant_id=actors["tenant_a"],
            quote_id=str(rejected["quote_id"]), expected_revision=1, idempotency_key="reject-once")
        customer_conn.commit()
        replay = custom_offers.transition(customer_conn, "reject", tenant_id=actors["tenant_a"],
            quote_id=str(rejected["quote_id"]), expected_revision=1, idempotency_key="reject-replay")
        customer_conn.commit()
        assert rejected_result["state"] == "rejected" and replay["idempotent"] is True
        with pytest.raises(custom_offers.CustomOfferError):
            custom_offers.transition(customer_conn, "accept", tenant_id=actors["tenant_a"],
                quote_id=str(rejected["quote_id"]), expected_revision=1, idempotency_key="reject-accept")
        customer_conn.rollback()

        expiring = _draft(platform_conn, actors, key="expiry-" + uuid.uuid4().hex)
        platform_conn.commit()
        _submit_and_price(platform_conn, expiring)
        custom_offers.transition(platform_conn, "approve", tenant_id=None, quote_id=str(expiring["quote_id"]),
                                 expected_revision=1, idempotency_key="expiry-approve",
                                 approval_reference="synthetic-test-approval")
        platform_conn.commit()
        detail = custom_offers.quote_detail(customer_conn, str(expiring["quote_id"]))
        assert detail["valid_until"] - detail["approved_at"] == timedelta(days=14)
    finally:
        platform_conn.close()
        customer_conn.close()


def test_actor_deletion_preserves_event_and_tenant_delete_cascades(quote_actors, owner_db, billing_connections):
    actors = quote_actors
    platform_conn = _conn(billing_connections, actors)
    customer_conn = _conn(billing_connections, actors, "tenant_a")
    try:
        quote = _draft(platform_conn, actors, terms={"test_only": True}, economics={"test_fixture": True})
        platform_conn.commit()
        _approve_and_accept(platform_conn, customer_conn, actors, quote)
        customer_conn.commit()
        with owner_db.cursor() as cur:
            cur.execute("DELETE FROM keel_platform_members WHERE user_id=%s", (actors["platform_user"],))
            cur.execute("DELETE FROM users WHERE user_id=%s", (actors["platform_user"],))
            cur.execute("DELETE FROM users WHERE user_id=%s", (actors["user_a"],))
            cur.execute("SELECT actor_user_id FROM billing_custom_quote_events WHERE quote_id=%s ORDER BY created_at,event_id", (quote["quote_id"],))
            assert all(row[0] is None for row in cur.fetchall())
            cur.execute("SELECT state,approved_by_user_id,accepted_by_user_id,approved_at,accepted_at FROM billing_custom_quote_revisions WHERE quote_id=%s", (quote["quote_id"],))
            revision = cur.fetchone()
            assert revision[0] == "accepted" and revision[1] is None and revision[2] is None
            assert revision[3] is not None and revision[4] is not None
            cur.execute("DELETE FROM companies WHERE tenant_id=%s", (actors["tenant_a"],))
            cur.execute("SELECT count(*) FROM billing_custom_quotes WHERE quote_id=%s", (quote["quote_id"],))
            assert cur.fetchone()[0] == 0
            cur.execute("SELECT count(*) FROM billing_custom_quote_events WHERE quote_id=%s", (quote["quote_id"],))
            assert cur.fetchone()[0] == 0
        owner_db.commit()
    finally:
        platform_conn.close()
        customer_conn.close()


def test_checkout_identity_requires_verified_processed_event_and_billing_authority(quote_actors, owner_db, billing_connections):
    import json
    from datetime import datetime, timezone

    actors = quote_actors
    platform_conn = _conn(billing_connections, actors)
    customer_conn = _conn(billing_connections, actors, "tenant_a")
    service_conn = billing_connections(actors["tenant_a"], "00000000-0000-0000-0000-000000000000")
    try:
        quote = _draft(platform_conn, actors, terms={"test_only": True}, economics={"test_fixture": True})
        platform_conn.commit()
        _approve_and_accept(platform_conn, customer_conn, actors, quote)
        platform_conn.commit()
        customer_conn.commit()
        attempt = custom_offers.prepare_checkout_attempt(
            customer_conn, tenant_id=actors["tenant_a"], quote_id=str(quote["quote_id"]),
            idempotency_key="verified-checkout-" + uuid.uuid4().hex,
        )
        customer_conn.commit()
        with pytest.raises(custom_offers.CustomOfferError) as human_update:
            custom_offers.record_verified_checkout_event(
                platform_conn, attempt_id=str(attempt["attempt_id"]), provider_event_id="evt_fake123",
            )
        assert human_update.value.status == 403
        platform_conn.rollback()

        now = datetime.now(timezone.utc)
        session_event = "evt_session" + uuid.uuid4().hex
        invoice_event = "evt_invoice" + uuid.uuid4().hex
        session_id = "cs_test_" + uuid.uuid4().hex
        subscription_id = "sub_" + uuid.uuid4().hex
        invoice_id = "in_" + uuid.uuid4().hex
        with owner_db.cursor() as cur:
            session_payload = {"id": session_event, "type": "checkout.session.completed", "data": {"object": {
                "id": session_id, "mode": "subscription", "subscription": subscription_id,
                "client_reference_id": str(attempt["attempt_id"]),
                "metadata": {"quote_attempt_id": str(attempt["attempt_id"])},
            }}}
            cur.execute("INSERT INTO billing_webhook_events(stripe_event_id,event_type,event_created,tenant_id,processed_at,payload) VALUES(%s,'checkout.session.completed',%s,%s,%s,%s::jsonb)",
                        (session_event, now, actors["tenant_a"], now, json.dumps(session_payload)))
            invoice_payload = {"id": invoice_event, "type": "invoice.paid", "data": {"object": {
                "id": invoice_id, "billing_reason": "subscription_create", "subscription": subscription_id,
                    "subscription_details": {"subscription": {"id": subscription_id}, "metadata": {"quote_attempt_id": str(attempt["attempt_id"])}},
                "status": "paid", "paid": True,
            }}}
            cur.execute("INSERT INTO billing_webhook_events(stripe_event_id,event_type,event_created,tenant_id,processed_at,payload) VALUES(%s,'invoice.paid',%s,%s,%s,%s::jsonb)",
                        (invoice_event, now, actors["tenant_a"], now, json.dumps(invoice_payload)))
            cur.execute("INSERT INTO billing_payments(tenant_id,stripe_invoice_id,stripe_subscription_id,amount,currency,status,paid_at) VALUES(%s,%s,%s,0,'USD','succeeded',%s)",
                        (actors["tenant_a"], invoice_id, subscription_id, now))
        owner_db.commit()
        session = custom_offers.record_verified_checkout_event(
            service_conn, attempt_id=str(attempt["attempt_id"]), provider_event_id=session_event,
        )
        service_conn.commit()
        assert session["state"] == "session_created" and session["idempotent"] is False
        session_replay = custom_offers.record_verified_checkout_event(
            service_conn, attempt_id=str(attempt["attempt_id"]), provider_event_id=session_event,
        )
        service_conn.commit()
        assert session_replay["idempotent"] is True
        settled = custom_offers.record_verified_checkout_event(
            service_conn, attempt_id=str(attempt["attempt_id"]), provider_event_id=invoice_event,
        )
        service_conn.commit()
        assert settled["state"] == "settled" and settled["provider_outcome"] == "settled"
        quote_after = custom_offers.quote_detail(customer_conn, str(quote["quote_id"]))
        assert quote_after["state"] == "accepted"  # provider result does not activate access
        assert quote_after["revision_state"] == "accepted"
    finally:
        platform_conn.close()
        customer_conn.close()
        service_conn.close()

def test_quote_rejection_and_expiry_are_non_activating(quote_actors, billing_connections):
    from datetime import datetime, timedelta, timezone

    actors = quote_actors
    platform_conn = _conn(billing_connections, actors)
    customer_conn = _conn(billing_connections, actors, "tenant_a")
    try:
        rejected = _draft(platform_conn, actors, terms={"test_only": True}, economics={"test_fixture": True})
        platform_conn.commit()
        custom_offers.transition(platform_conn, "submit", tenant_id=None, quote_id=str(rejected["quote_id"]),
                                 expected_revision=1, idempotency_key="reject-submit")
        platform_conn.commit()
        custom_offers.transition(platform_conn, "approve", tenant_id=None, quote_id=str(rejected["quote_id"]),
                                 expected_revision=1, idempotency_key="reject-approve",
                                 approval_reference="synthetic-test-approval")
        platform_conn.commit()
        rejected_result = custom_offers.transition(customer_conn, "reject", tenant_id=actors["tenant_a"],
            quote_id=str(rejected["quote_id"]), expected_revision=1, idempotency_key="reject-once")
        customer_conn.commit()
        replay = custom_offers.transition(customer_conn, "reject", tenant_id=actors["tenant_a"],
            quote_id=str(rejected["quote_id"]), expected_revision=1, idempotency_key="reject-replay")
        customer_conn.commit()
        assert rejected_result["state"] == "rejected" and replay["idempotent"] is True
        with pytest.raises(custom_offers.CustomOfferError):
            custom_offers.transition(customer_conn, "accept", tenant_id=actors["tenant_a"],
                quote_id=str(rejected["quote_id"]), expected_revision=1, idempotency_key="reject-accept")
        customer_conn.rollback()

        expired = custom_offers.create_draft(
            platform_conn, tenant_id=actors["tenant_a"], customer_user_id=actors["user_a"],
            idempotency_key="expiry-" + uuid.uuid4().hex, configuration={"mode": "test_fixture"},
            feature_quantities={}, commercial_terms={"test_only": True},
            economic_inputs={"test_fixture": True}, fx_evidence={},
            valid_until=datetime.now(timezone.utc)-timedelta(seconds=1),
        )
        platform_conn.commit()
        custom_offers.transition(platform_conn, "submit", tenant_id=None, quote_id=str(expired["quote_id"]),
                                 expected_revision=1, idempotency_key="expiry-submit")
        platform_conn.commit()
        custom_offers.transition(platform_conn, "approve", tenant_id=None, quote_id=str(expired["quote_id"]),
                                 expected_revision=1, idempotency_key="expiry-approve",
                                 approval_reference="synthetic-test-approval")
        platform_conn.commit()
        result = custom_offers.transition(customer_conn, "accept", tenant_id=actors["tenant_a"],
            quote_id=str(expired["quote_id"]), expected_revision=1, idempotency_key="expiry-accept")
        customer_conn.commit()
        assert result["state"] == "expired" and result["access_activated"] is False
    finally:
        platform_conn.close()
        customer_conn.close()
