"""
Regression: stripe-python 15 objects are not dicts (no .get(), no dict()), but
the billing code reads Stripe data with .get() everywhere (webhooks, plan
changes). Tests that fake stripe_api with plain dicts never saw it; against the
real API every subscription webhook failed with AttributeError. stripe_api now
converts each response, and these tests use real SDK objects to prove it.
"""
import pytest

stripe = pytest.importorskip("stripe")

from src.ai.billing import store, stripe_api, webhooks  # noqa: E402


def test_stripe_isk_and_ugx_compatibility_amounts_are_two_decimal():
    assert store._minor_to_major(500, "isk") == 5.0
    assert store._minor_to_major(500, "UGX") == 5.0
    assert store._minor_to_major(500, "jpy") == 500.0


def _subscription():
    return stripe.Subscription.construct_from({
        "id": "sub_123", "object": "subscription", "status": "active", "customer": "cus_123",
        "metadata": {"tenant_id": "11111111-1111-4111-8111-111111111111"},
        "items": {"object": "list", "data": [{"id": "si_1", "price": {"id": "price_1"},
                                              "current_period_start": 1, "current_period_end": 2}]},
    }, "sk_test_x")


def test_sdk_objects_have_no_get_which_is_why_responses_are_converted():
    with pytest.raises(AttributeError):
        _subscription().get("customer")


def test_plain_gives_dicts_all_the_way_down():
    plain = stripe_api._plain(_subscription())
    assert type(plain) is dict and type(plain["metadata"]) is dict and type(plain["items"]) is dict
    assert plain.get("customer") == "cus_123" and plain["metadata"].get("tenant_id")
    assert store.subscription_price_id(plain) == "price_1"


def test_every_stripe_call_wrapper_returns_plain_dicts(monkeypatch):
    class Fake:
        class Subscription:
            retrieve = staticmethod(lambda sid: _subscription())
            modify = staticmethod(lambda sid, **kw: _subscription())

    monkeypatch.setattr(stripe_api, "_client", lambda: Fake)
    for result in (stripe_api.retrieve_subscription("sub_123"), stripe_api.modify_subscription("sub_123", x=1)):
        assert type(result) is dict and result.get("status") == "active"


def test_webhook_tenant_resolution_works_on_a_converted_sdk_object():
    class NoDb:  # tenant_for_subscription/customer are bypassed by patching below
        pass

    plain = stripe_api._plain(_subscription())
    original = (store.tenant_for_subscription, store.tenant_for_customer)
    store.tenant_for_subscription = lambda conn, sid: None
    store.tenant_for_customer = lambda conn, cid: None
    try:
        assert webhooks._resolve_tenant(NoDb(), plain) == "11111111-1111-4111-8111-111111111111"
    finally:
        store.tenant_for_subscription, store.tenant_for_customer = original
