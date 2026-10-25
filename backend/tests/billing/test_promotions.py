from datetime import datetime, timezone

import pytest

from src.ai.billing import promotions, service, store, stripe_api


def _complete_terms(**overrides):
    terms = {
        "discount_type": "percent",
        "discount_value": 100,
        "currency": "USD",
        "starts_at": None,
        "expires_at": None,
        "max_uses": 1,
        "max_uses_per_tenant": 1,
        "invoice_scope": "initial_subscription",
        "stripe_coupon_id": "coupon_test_only",
        "stripe_promotion_code_id": "promo_test_only",
    }
    terms.update(overrides)
    return terms


def test_managed_promotions_are_disabled_by_default(monkeypatch):
    monkeypatch.delenv("KEEL_MANAGED_PROMOTIONS_ENABLED", raising=False)
    monkeypatch.setattr(promotions, "_eligibility", lambda *a, **k: pytest.fail("disabled path queried a campaign"))
    assert promotions.enabled() is False
    assert promotions.validate(None, "tenant", "SAVE", "starter", "monthly") == {
        "valid": False, "reason": "promotions_unavailable"
    }


def test_open_ended_limits_must_be_explicit_in_complete_terms():
    terms = _complete_terms(max_uses=None, max_uses_per_tenant=None, starts_at=None, expires_at=None)
    normalized, missing = promotions._validate_terms(terms)
    assert missing == []
    assert normalized["max_uses"] is None
    assert normalized["max_uses_per_tenant"] is None

    normalized, missing = promotions._validate_terms({"discount_type": "percent", "discount_value": 10})
    assert normalized["discount_value"] == "10"
    assert {"max_uses", "max_uses_per_tenant", "starts_at", "expires_at"} <= set(missing)


def test_promotion_terms_reject_naive_dates():
    with pytest.raises(promotions.PromotionError) as error:
        promotions._validate_terms(_complete_terms(starts_at="2026-10-21T12:00:00"))
    assert error.value.code == "invalid_promotion_terms"


def test_promotion_terms_reject_unknown_invoice_scope():
    with pytest.raises(promotions.PromotionError):
        promotions._validate_terms(_complete_terms(invoice_scope="renewal"))


def test_percentage_provider_objects_are_verified_against_owner_terms():
    terms = {**_complete_terms(), "discount_value": "10", "stripe_coupon_id": "coupon_test_only",
             "stripe_promotion_code_id": "promo_test_only"}
    coupon = {"id": "coupon_test_only", "duration": "once", "percent_off": 10}
    code = {"id": "promo_test_only", "code": "SAVE", "active": True, "max_redemptions": 1,
            "promotion": {"coupon": "coupon_test_only"}}
    promotions._verify_provider_objects(terms, coupon, code, "SAVE")
    with pytest.raises(promotions.PromotionError) as error:
        promotions._verify_provider_objects(terms, {**coupon, "percent_off": 15}, code, "SAVE")
    assert error.value.code == "promotion_coupon_mismatch"


def test_fixed_amount_provider_coupon_checks_minor_units_and_currency():
    terms = {**_complete_terms(discount_type="fixed_amount", discount_value="12.50", currency="USD"),
             "stripe_coupon_id": "coupon_test_only", "stripe_promotion_code_id": "promo_test_only"}
    coupon = {"id": "coupon_test_only", "duration": "once", "amount_off": 1250, "currency": "usd"}
    code = {"id": "promo_test_only", "code": "SAVE", "active": True, "max_redemptions": 1,
            "promotion": {"coupon": "coupon_test_only"}}
    promotions._verify_provider_objects(terms, coupon, code, "SAVE")
    with pytest.raises(promotions.PromotionError):
        promotions._verify_provider_objects(terms, {**coupon, "amount_off": 1251}, code, "SAVE")


def test_promotion_provider_mutations_are_test_mode_only(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_live_test_placeholder")
    assert promotions._provider_mutations_allowed() is False
    monkeypatch.setenv("KEEL_ALLOW_LIVE_PROMOTION_PROVIDER_MUTATIONS", "true")
    assert promotions._provider_mutations_allowed() is False
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_offline")
    assert promotions._provider_mutations_allowed() is True


def test_percentage_promotion_is_currency_agnostic_but_fixed_amount_requires_currency():
    percent, missing = promotions._validate_terms(_complete_terms(currency=None))
    assert "currency" not in percent
    assert not missing
    fixed, missing = promotions._validate_terms(_complete_terms(discount_type="fixed_amount", currency=None))
    assert "currency" not in fixed
    assert not missing  # provider activation adds the explicit refusal for fixed amount


def test_managed_checkout_uses_stripe_discount_without_hosted_code_stacking(monkeypatch, memory_checkout_reservations):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_offline")
    monkeypatch.setenv("APP_BASE_URL", "https://keel.example.test")
    monkeypatch.setenv("KEEL_MANAGED_PROMOTIONS_ENABLED", "true")
    monkeypatch.setattr(store, "current_subscription", lambda *args: None)
    monkeypatch.setattr(store, "current_price", lambda *args: {
        "is_active": True, "self_serve": True, "stripe_price_id": "price_test",
        "currency": "USD", "amount": 50, "tier_level": 1,
    })
    monkeypatch.setattr(store, "customer_id", lambda *args: "cus_test")
    monkeypatch.setattr(store, "trial", lambda *args: None)
    monkeypatch.setattr(promotions, "require_checkout_eligibility", lambda *args: {
        "promotion_id": "f35a2d2c-eaf9-48a9-9b6a-e24747a20d27",
        "stripe_promotion_code_id": "promo_test_only",
    })
    reserved = []
    monkeypatch.setattr(promotions, "reserve", lambda *a, **kw: (
        reserved.append(kw) or {"redemption_id": "1c6125e7-352e-49cf-9f93-7f095f8d5e3e"}
    ))
    started = []
    monkeypatch.setattr(promotions, "begin_checkout_request", lambda *a, **kw: started.append(kw))
    attached = []
    monkeypatch.setattr(promotions, "attach_checkout", lambda *a, **kw: attached.append(kw))
    calls = []
    monkeypatch.setattr(stripe_api, "create_checkout_session", lambda params, idempotency_key: (
        calls.append((params, idempotency_key)) or {"id": "cs_test", "url": "https://checkout.stripe.test"}
    ))

    class Connection:
        commits = 0
        rollbacks = 0

        def commit(self):
            self.commits += 1

        def rollback(self):
            self.rollbacks += 1

    sys_conn = Connection()
    result = service.create_checkout(None, sys_conn, "tenant", "a@example.test", "Store",
                                     "starter", "monthly", "SAVE", "user-id")

    params = calls[0][0]
    assert result["session_id"] == "cs_test"
    assert params["discounts"] == [{"promotion_code": "promo_test_only"}]
    assert params["allow_promotion_codes"] is False
    assert params["metadata"]["keel_promotion_redemption_id"] == "1c6125e7-352e-49cf-9f93-7f095f8d5e3e"
    assert params["subscription_data"]["metadata"]["keel_promotion_redemption_id"] == params["metadata"]["keel_promotion_redemption_id"]
    assert reserved[0]["actor_user_id"] == "user-id"
    assert attached[0]["session_id"] == "cs_test"
    assert started[0]["redemption_id"] == "1c6125e7-352e-49cf-9f93-7f095f8d5e3e"
    assert calls[0][1] == "apex-promo-checkout-1c6125e7-352e-49cf-9f93-7f095f8d5e3e"


def test_uncertain_stripe_outcome_is_quarantined_without_retry(monkeypatch, memory_checkout_reservations):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_offline")
    monkeypatch.setenv("KEEL_MANAGED_PROMOTIONS_ENABLED", "true")
    monkeypatch.setattr(store, "current_subscription", lambda *args: None)
    monkeypatch.setattr(store, "current_price", lambda *args: {
        "is_active": True, "self_serve": True, "stripe_price_id": "price_test", "currency": "USD",
    })
    monkeypatch.setattr(store, "customer_id", lambda *args: "cus_test")
    monkeypatch.setattr(store, "trial", lambda *args: None)
    monkeypatch.setattr(promotions, "require_checkout_eligibility", lambda *args: {
        "promotion_id": "f35a2d2c-eaf9-48a9-9b6a-e24747a20d27", "stripe_promotion_code_id": "promo_test_only",
    })
    monkeypatch.setattr(promotions, "reserve", lambda *a, **kw: {"redemption_id": "1c6125e7-352e-49cf-9f93-7f095f8d5e3e"})
    monkeypatch.setattr(promotions, "begin_checkout_request", lambda *a, **kw: None)
    unknown = []
    monkeypatch.setattr(promotions, "provider_outcome_unknown", lambda *a, **kw: unknown.append(kw))
    calls = []
    def lost_response(*args, **kwargs):
        calls.append(1)
        raise TimeoutError("synthetic uncertain outcome")
    monkeypatch.setattr(stripe_api, "create_checkout_session", lost_response)

    class Connection:
        def commit(self):
            pass
        def rollback(self):
            pass

    with pytest.raises(TimeoutError):
        service.create_checkout(None, Connection(), "tenant", "a@example.test", "Store",
                                "starter", "monthly", "SAVE", "user-id")
    assert len(calls) == 1
    assert unknown == [{"tenant_id": "tenant", "redemption_id": "1c6125e7-352e-49cf-9f93-7f095f8d5e3e"}]


def test_retried_managed_checkout_reuses_existing_session_without_creating_another(monkeypatch, memory_checkout_reservations):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_offline")
    monkeypatch.setenv("KEEL_MANAGED_PROMOTIONS_ENABLED", "true")
    monkeypatch.setattr(store, "current_subscription", lambda *args: None)
    monkeypatch.setattr(store, "current_price", lambda *args: {
        "is_active": True, "self_serve": True, "stripe_price_id": "price_test", "currency": "USD",
    })
    monkeypatch.setattr(store, "customer_id", lambda *args: "cus_test")
    monkeypatch.setattr(store, "trial", lambda *args: None)
    monkeypatch.setattr(promotions, "require_checkout_eligibility", lambda *args: {
        "promotion_id": "f35a2d2c-eaf9-48a9-9b6a-e24747a20d27", "stripe_promotion_code_id": "promo_test_only",
    })
    monkeypatch.setattr(promotions, "reserve", lambda *a, **kw: {
        "redemption_id": "1c6125e7-352e-49cf-9f93-7f095f8d5e3e", "session_id": "cs_existing",
    })
    monkeypatch.setattr(stripe_api, "retrieve_checkout_session", lambda session_id: {
        "id": session_id, "status": "open", "url": "https://checkout.stripe.test/existing",
    })
    monkeypatch.setattr(stripe_api, "create_checkout_session", lambda *a, **kw: pytest.fail("duplicate checkout"))
    monkeypatch.setattr(promotions, "begin_checkout_request", lambda *a, **kw: pytest.fail("existing session must not be re-claimed"))

    class Connection:
        def commit(self):
            pass
        def rollback(self):
            pass

    result = service.create_checkout(None, Connection(), "tenant", "a@example.test", "Store",
                                     "starter", "monthly", "SAVE", "user-id")
    assert result == {"url": "https://checkout.stripe.test/existing", "session_id": "cs_existing"}


def test_platform_admin_cannot_manage_promotions():
    from src.ai.core.authorization import require_platform_permission
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as error:
        require_platform_permission("admin", "promotion_management")
    assert error.value.status_code == 403
    require_platform_permission("owner", "promotion_management")


def test_promotion_customer_and_operator_apis_require_authentication(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from src.ai.core.exceptions import register_exception_handlers
    from src.ai.routers import billing as billing_router, platform as platform_router

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(billing_router.router)
    app.include_router(platform_router.router)
    with TestClient(app) as client:
        customer = client.post("/billing/promotions/validate", json={"code": "SAVE", "plan_key": "starter"})
        operator = client.post("/platform/billing/promotions", json={
            "code": "SAVE", "name": "Draft", "terms": {}, "plan_keys": [], "reason": "test",
        })
    assert customer.status_code == 401
    assert operator.status_code == 401
