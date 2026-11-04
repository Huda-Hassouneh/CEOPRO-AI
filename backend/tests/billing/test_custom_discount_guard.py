"""Final discounted revenue, not the monthly list price, gates auto-approval."""
from contextlib import closing
from decimal import Decimal
from uuid import uuid4

import pytest

from src.ai import db
from src.ai.billing import custom_offers, self_service, service
from src.ai.core.security import TenantContext
from .test_custom_self_service import inputs, config
from .test_reconciliation_roles import restricted_runtime  # noqa: F401

REASON = "VENDOR_COST_RATIO_EXCEEDED"


def reproduction(period="six-months"):
    data = inputs()
    data["bindings"][0].update(feature_code="ai_credits", unit_cost_usd="0.004")
    data["policy"] = {
        "policy_version_id": str(uuid4()), "target_gross_margin": "0.25",
        "enforce_vendor_cost_ratio_floor": True, "max_vendor_cost_revenue_ratio": "0.05",
        "fixed_platform_fee_usd": "10", "upward_rounding_increment_usd": "2",
        "monthly_shared_infrastructure_cost_usd": "250", "active_paying_tenant_count": 50,
    }
    selection = {**config(), "limits": {"ai_credits": 1000}, "billingPeriod": period}
    return selection, data


@pytest.mark.parametrize("period,price,payment,review", [
    ("monthly", "63.81", "90.00", False),
    ("three-months", "172.29", "243.00", False),
    ("six-months", "306.29", "432.00", True),
])
def test_reported_discount_case_preserves_prices_and_changes_only_review(period, price, payment, review):
    selection, data = reproduction(period)
    actual = self_service.calculate(selection, data)
    assert actual["price"] == price and actual["paymentAmount"] == payment
    assert actual["reviewRequired"] is review and actual["checkoutAllowed"] is not review
    assert (REASON in actual["reasons"]) is review
    assert actual["pricingSnapshot"]["reviewDecision"]["required"] is review
    if review:
        assert Decimal("4") * 6 / Decimal(payment) > Decimal("0.05")


@pytest.mark.parametrize("period,fee", [("monthly", "0"), ("three-months", "6"), ("six-months", "13.5")])
@pytest.mark.parametrize("extra_fee", ["0", "1"])
def test_exact_threshold_and_below_are_allowed_for_every_term(period, fee, extra_fee):
    selection, data = reproduction(period)
    selection["limits"]["ai_credits"] = 1
    data["bindings"][0]["unit_cost_usd"] = "2.7"
    data["policy"]["self_service_policy"] = {
        "fixedPlatformFee": str(Decimal(fee) + Decimal(extra_fee)), "roundingIncrement": "0",
        "fxRate": "1", "fxVersion": "synthetic-1", "fxSource": "Synthetic test only",
    }
    actual = self_service.calculate(selection, data)
    assert not actual["reviewRequired"]
    ratio = Decimal("2.7") * actual["months"] / Decimal(actual["paymentAmount"])
    assert ratio == Decimal(".05") if extra_fee == "0" else ratio < Decimal(".05")


@pytest.mark.parametrize("period", ["three-months", "six-months"])
def test_each_term_discount_can_turn_monthly_eligibility_into_review(period):
    selection, data = reproduction("monthly")
    data["policy"]["self_service_policy"] = {"fixedPlatformFee": "0", "roundingIncrement": "0"}
    assert not self_service.calculate(selection, data)["reviewRequired"]
    selection["billingPeriod"] = period
    result = self_service.calculate(selection, data)
    assert result["reasons"] == [REASON] and not result["checkoutAllowed"]


def test_exact_cost_not_rounded_display_cost_is_compared_with_non_unit_fx():
    selection, data = reproduction("monthly")
    selection["limits"]["ai_credits"] = 1
    data["bindings"][0]["unit_cost_usd"] = "4"
    data["policy"]["self_service_policy"] = {"fixedPlatformFee": "0", "roundingIncrement": "0"}
    result = self_service.calculate(selection, data)
    assert result["price"] == "56.72" and result["paymentAmount"] == "80.00"
    assert result["pricingSnapshot"]["calculation"]["estimatedVendorCost"] == "2.84"
    assert not result["reviewRequired"]  # Exact cost is 2.836 JOD, precisely 5%.


@pytest.mark.parametrize("cost,review", [("0.011", False), ("0.013", True)])
def test_final_usd_cent_rounding_is_included(cost, review):
    selection, data = reproduction("monthly")
    selection["limits"]["ai_credits"] = 1
    data["bindings"][0]["unit_cost_usd"] = cost
    data["policy"]["monthly_shared_infrastructure_cost_usd"] = "0"
    data["policy"]["self_service_policy"] = {"fixedPlatformFee": "0", "roundingIncrement": "0"}
    result = self_service.calculate(selection, data)
    assert result["reviewRequired"] is review


def test_disabled_policy_and_unknown_cost_rules_remain_unchanged():
    selection, data = reproduction()
    data["policy"]["enforce_vendor_cost_ratio_floor"] = False
    assert not self_service.calculate(selection, data)["reviewRequired"]
    data["bindings"][0]["verified_at"] = None
    assert "UNVERIFIED_VENDOR_RATE" in self_service.calculate(selection, data)["reasons"]
    data["bindings"] = []
    assert not self_service.calculate(selection, data)["pricingAvailable"]


def test_zero_final_revenue_fails_closed_without_changing_the_price():
    selection, data = reproduction("monthly")
    data["bindings"][0]["unit_cost_usd"] = "0"
    data["policy"]["monthly_shared_infrastructure_cost_usd"] = "0"
    data["policy"]["self_service_policy"] = {"fixedPlatformFee": "0", "roundingIncrement": "0"}
    actual = self_service.calculate(selection, data)
    assert actual["price"] == actual["paymentAmount"] == "0.00"
    assert actual["reviewRequired"] and not actual["checkoutAllowed"]
    assert actual["reasons"] == ["VENDOR_COST_RATIO_UNVERIFIABLE"]


def freeze(setup, owner, period="six-months", *, legacy=False, malformed=False):
    selection, data = reproduction(period)
    rate = data["bindings"][0]
    with owner.cursor() as cur:
        cur.execute("UPDATE billing_custom_pricing_policies SET status='retired',effective_to=clock_timestamp() WHERE status='active'")
        cur.execute("""INSERT INTO billing_custom_pricing_policies(policy_version_id,target_gross_margin,
          enforce_vendor_cost_ratio_floor,max_vendor_cost_revenue_ratio,fixed_platform_fee_usd,
          upward_rounding_increment_usd,monthly_shared_infrastructure_cost_usd,active_paying_tenant_count,
          approved_by,approval_evidence) VALUES(%s,.25,true,.05,10,2,250,50,'test','SYNTHETIC_TEST_ONLY')""",
          (data["policy"]["policy_version_id"],))
        cur.execute("""INSERT INTO billing_custom_cost_rates(cost_rate_id,budget_kind,provider,operation,unit,unit_cost_usd,
          source,verified_at,effective_from,verified_by,verification_evidence)
          VALUES(%s,'ai','synthetic','source-month','request',.004,'synthetic test',CURRENT_DATE,
                 now()-interval '1 day','test','test')""", (rate["rate_id"],))
        cur.execute("SELECT unit_cost_usd::text FROM billing_custom_cost_rates WHERE cost_rate_id=%s", (rate["rate_id"],))
        rate["unit_cost_usd"] = cur.fetchone()[0]
        cur.execute("""INSERT INTO billing_custom_cost_bindings(policy_version_id,feature_code,cost_category,budget_kind,
          provider,operation,unit,usage_basis,units_per_feature_unit,operational_multiplier,variability_reserve,
          effective_from,source,created_by,cost_rate_id)
          VALUES(%s,'ai_credits','vendor','ai','synthetic','source-month','request','limit_value',1,1,1,now(),'test','test',%s)""",
          (data["policy"]["policy_version_id"], rate["rate_id"]))
        cur.execute("UPDATE billing_custom_pricing_policies SET status='active',effective_from=now() WHERE policy_version_id=%s",
                    (data["policy"]["policy_version_id"],))
    snapshot = self_service.calculate(selection, data)["pricingSnapshot"]
    if legacy:
        # Represent an old server-frozen preview, NOT customer-supplied evidence.
        snapshot["reviewDecision"] = {"required": False, "reasons": []}
    if malformed:
        del snapshot["calculation"]["vendorBreakdown"][0]["normalizedUnitCost"]
    result = self_service.command(setup, "freeze", {"snapshot": snapshot, "idempotency_key": str(uuid4())})
    setup.commit()
    return result["quote_id"], snapshot


@pytest.mark.parametrize("legacy,malformed", [(False, False), (True, False), (True, True)])
def test_native_review_guard_blocks_direct_checkout_without_provider_or_access(
    client, owner_db, tenant, restricted_runtime, monkeypatch, legacy, malformed,
):
    from src.ai.routers import billing
    tid, uid = tenant
    with closing(db.billing_setup_connection(tid, uid)) as setup:
        quote, _ = freeze(setup, owner_db, legacy=legacy, malformed=malformed)
        if legacy:
            import psycopg2
            from psycopg2.extras import Json
            with pytest.raises(psycopg2.errors.ObjectNotInPrerequisiteState) as error, setup.cursor() as cur:
                cur.execute("SELECT billing_custom_self_service('checkout',%s)", (Json({"preview_id": quote}),))
            assert ("valid frozen vendor-cost evidence" if malformed else "final vendor-cost ratio") in str(error.value)
            setup.rollback()
    client.app.dependency_overrides[billing.get_tenant_context] = lambda: TenantContext(tid, uid)
    monkeypatch.setattr(service.config, "payments_enabled", lambda: True)
    monkeypatch.setattr(service, "create_custom_quote_checkout", lambda *a, **k: pytest.fail("Review bypass reached gateway"))
    response = client.post("/billing/custom-offers/checkout", json={"preview_id": quote, "idempotency_key": str(uuid4())})
    assert response.status_code == 409 and response.json()["detail"]["reason"] == "preview_not_checkoutable"
    # The alternate accepted-quote endpoint cannot promote a draft either.
    with closing(db.app_role_connection(tid, uid)) as conn:
        with pytest.raises(custom_offers.CustomOfferError):
            custom_offers.custom_checkout_prepare(conn, quote_id=quote, idempotency_key=str(uuid4()))
    with owner_db.cursor() as cur:
        cur.execute("SELECT state FROM billing_custom_quote_revisions WHERE quote_id=%s", (quote,))
        assert cur.fetchone()[0] == "draft"
        for table in ("tenant_plan_assignments", "billing_subscriptions", "billing_checkout_attempts"):
            cur.execute(f"SELECT count(*) FROM {table} WHERE tenant_id=%s", (tid,))
            assert cur.fetchone()[0] == 0


def test_native_owner_review_acceptance_preserves_terms_and_does_not_grant_access(
    owner_db, tenant, restricted_runtime, platform_owner_context, billing_connections,
):
    tid, uid = tenant
    with closing(db.billing_setup_connection(tid, uid)) as setup:
        quote, snapshot = freeze(setup, owner_db)
        self_service.command(setup, "review", {"preview_id": quote})
        setup.commit()
    with closing(billing_connections(*platform_owner_context)) as operator:
        custom_offers.transition(operator, "approve", tenant_id=None, quote_id=quote, expected_revision=1,
            idempotency_key=str(uuid4()), approval_reference="SYNTHETIC explicit owner approval")
        operator.commit()
    with closing(billing_connections(tid, uid)) as customer:
        custom_offers.transition(customer, "accept", tenant_id=tid, quote_id=quote, expected_revision=1, idempotency_key=str(uuid4()))
        customer.commit()
        accepted = custom_offers.quote_detail(customer, quote)
        assert accepted["commercial_terms"]["amount"] == snapshot["commercial"]["amount"]
        assert accepted["commercial_terms"]["paymentAmountUsd"] == snapshot["payment"]["amount"]
    with owner_db.cursor() as cur:
        cur.execute("SELECT pricing_snapshot FROM billing_custom_quote_revisions WHERE quote_id=%s", (quote,))
        assert cur.fetchone()[0] == snapshot
        cur.execute("SELECT count(*) FROM tenant_plan_assignments WHERE tenant_id=%s", (tid,))
        assert cur.fetchone()[0] == 0


def test_native_frozen_monthly_terms_and_repeat_checkout_remain_accepted(owner_db, tenant, restricted_runtime):
    tid, uid = tenant
    with closing(db.billing_setup_connection(tid, uid)) as setup:
        quote, snapshot = freeze(setup, owner_db, "monthly")
        first = self_service.command(setup, "checkout", {"preview_id": quote})
        setup.commit()
        assert self_service.command(setup, "checkout", {"preview_id": quote}) == first
        setup.commit()
    with owner_db.cursor() as cur:
        cur.execute("SELECT pricing_snapshot,commercial_terms FROM billing_custom_quote_revisions WHERE quote_id=%s", (quote,))
        saved, terms = cur.fetchone()
        assert saved == snapshot and terms["paymentAmountUsd"] == "90.00"
        assert self_service.checkout_terms(terms) == (Decimal("90.00"), 1, "monthly")
