from src.ai.billing import custom_offers, service, store, stripe_api


def test_custom_quote_checkout_uses_database_terms_and_stable_provider_identity(monkeypatch, memory_checkout_reservations):
    captured = {}
    monkeypatch.setattr(service.config, "payments_enabled", lambda: True)
    monkeypatch.setattr(service.config, "app_base_url", lambda: "https://local.test")
    monkeypatch.setattr(store, "current_subscription", lambda *_: None)
    monkeypatch.setattr(service, "_ensure_customer", lambda *_: "cus_disposable")
    monkeypatch.setattr(custom_offers, "custom_checkout_prepare", lambda *_, **__: {
        "attempt_id": "11111111-1111-4111-8111-111111111111",
        "revision_id": "22222222-2222-4222-8222-222222222222",
        "commercial_terms": {"currency": "USD", "monthlyPriceUsd": "57.25", "billingPeriodMonths": 1},
    })

    def create(params, idempotency_key):
        captured["params"] = params
        captured["key"] = idempotency_key
        return {"id": "cs_test_contract", "url": "https://checkout.stripe.test/session"}

    monkeypatch.setattr(stripe_api, "create_checkout_session", create)
    monkeypatch.setattr(custom_offers, "record_custom_checkout_session", lambda *_, **__: {"state": "session_created"})
    result = service.create_custom_quote_checkout(object(), object(), "tenant", "owner@example.test", "Test Co",
                                                  "quote", "client-retry-key")
    assert captured["params"]["line_items"][0]["price_data"]["unit_amount"] == 5725
    assert captured["params"]["line_items"][0]["price_data"]["currency"] == "usd"
    assert captured["params"]["metadata"]["quote_attempt_id"] == result["attempt_id"]
    assert captured["params"]["subscription_data"]["metadata"]["custom_quote_revision_id"] == "22222222-2222-4222-8222-222222222222"
    assert captured["key"] == "keel-custom-checkout-11111111-1111-4111-8111-111111111111"
    assert result["session_id"] == "cs_test_contract"


def test_custom_quote_checkout_refuses_non_usd_or_invalid_terms_before_provider(monkeypatch, memory_checkout_reservations):
    monkeypatch.setattr(service.config, "payments_enabled", lambda: True)
    monkeypatch.setattr(store, "current_subscription", lambda *_: None)
    monkeypatch.setattr(custom_offers, "custom_checkout_prepare", lambda *_, **__: {
        "attempt_id": "attempt", "revision_id": "revision",
        "commercial_terms": {"currency": "JOD", "monthlyPriceUsd": "10", "billingPeriodMonths": 1},
    })
    monkeypatch.setattr(stripe_api, "create_checkout_session", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("provider called")))
    import pytest
    with pytest.raises(service.BillingError) as exc:
        service.create_custom_quote_checkout(object(), object(), "tenant", "owner@example.test", "Test Co", "quote", "retry")
    assert exc.value.code == "custom_terms_unsupported"
