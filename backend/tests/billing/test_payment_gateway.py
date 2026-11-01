"""Offline parity against existing application transport; no runtime switch."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
import stripe

from src.ai.billing import config, service, store, stripe_api, promotions, custom_offers, self_service
from src.ai.billing.payment_contracts import (
    CheckoutIntent, CheckoutSnapshot, CheckoutState, Money, PaymentProviderError,
    PaymentState, ProviderOperationOutcome as Outcome, ProviderReference as Ref,
    SubscriptionChangeIntent, SubscriptionPaymentGateway, SubscriptionSnapshot, SubscriptionState,
)
from src.ai.billing.stripe_gateway import StripeGateway


NOW = datetime.fromtimestamp(1800000000, timezone.utc)
CUTOFF = datetime.fromtimestamp(1800600000, timezone.utc)


def checkout_intent(**changes):
    return replace(CheckoutIntent(
        customer=Ref("stripe", "cus_existing"), price=Ref("stripe", "price_existing"),
        idempotency_key="original-durable-request", client_reference="tenant-A",
        success_url="https://keel.example.test/billing?checkout=success&session_id={checkout_reference}",
        cancel_url="https://keel.example.test/billing?checkout=cancelled",
        metadata={"tenant_id": "tenant-A", "plan_key": "growth", "period_code": "monthly"},
        subscription_metadata={"tenant_id": "tenant-A", "plan_key": "growth", "period_code": "monthly"},
    ), **changes)


def remote_subscription(*, trial=False, pending=False, schedule="sched_existing", item_period=True):
    data = {"id": "sub_existing", "customer": "cus_existing", "status": "trialing" if trial else "active",
            "trial_end": int(CUTOFF.timestamp()) if trial else None,
            "schedule": schedule, "latest_invoice": {"id": "in_existing"},
            "pending_update": {"expires_at": 1800700000} if pending else None,
            "current_period_start": 1799990000, "current_period_end": 1802700000,
            "items": {"data": [{"id": "si_existing", "price": {"id": "price_old"}, "quantity": 2}]}}
    if item_period:
        data["items"]["data"][0].update(current_period_start=1799990000, current_period_end=1802700000)
    return data


@pytest.mark.parametrize("trial", [False, True])
@pytest.mark.parametrize("promotion", [False, True])
@pytest.mark.parametrize("tax", [False, True])
def test_standard_checkout_request_is_identical_to_existing_service(monkeypatch, trial, promotion, tax):
    conn = MagicMock()
    monkeypatch.setattr(config, "payments_enabled", lambda: True)
    monkeypatch.setattr(config, "app_base_url", lambda: "https://keel.example.test")
    monkeypatch.setattr(config, "automatic_tax", lambda: tax)
    monkeypatch.setattr(store, "current_subscription", lambda *a: None)
    monkeypatch.setattr(store, "current_price", lambda *a: {"is_active": True, "self_serve": True, "stripe_price_id": "price_existing"})
    monkeypatch.setattr(store, "trial", lambda *a: {"ends_at": CUTOFF} if trial else None)
    monkeypatch.setattr(service, "_ensure_customer", lambda *a: "cus_existing")
    monkeypatch.setattr(stripe_api, "customer_clock_time", lambda *a: None)
    monkeypatch.setattr(service.time, "time", lambda: NOW.timestamp())
    monkeypatch.setattr(promotions, "require_checkout_eligibility", lambda *a: {
        "promotion_id": "campaign", "stripe_promotion_code_id": "promo_bound"})
    monkeypatch.setattr(promotions, "reserve", lambda *a, **k: {"redemption_id": "redemption"})
    monkeypatch.setattr(promotions, "begin_checkout_request", lambda *a, **k: None)
    monkeypatch.setattr(promotions, "attach_checkout", lambda *a, **k: None)
    calls = []

    def create(params, idempotency_key):
        calls.append((deepcopy(params), idempotency_key))
        return {"id": "cs_test_existing", "url": "https://checkout.example.test", "status": "open"}
    monkeypatch.setattr(stripe_api, "create_checkout_session", create)
    service._create_checkout(None, conn, "tenant-A", "owner@example.test", "Company", "growth", "monthly",
                             "APPROVED" if promotion else None, "actor")
    expected, key = calls.pop()
    metadata = checkout_intent().metadata | ({"keel_promotion_redemption_id": "redemption"} if promotion else {})
    result = StripeGateway().create_checkout(checkout_intent(
        idempotency_key=key,
        trial_end=CUTOFF if trial else None,
        promotion=Ref("stripe", "promo_bound") if promotion else None,
        automatic_tax=tax, metadata=metadata, subscription_metadata=metadata))
    assert calls == [(expected, key)]
    assert result.state == CheckoutState.OPEN and result.reference == Ref("stripe", "cs_test_existing")
    assert ("allow_promotion_codes" not in expected) if promotion else expected["allow_promotion_codes"] is True


@pytest.mark.parametrize("months,currency", [(1, "USD"), (1, "JOD"), (3, "JOD"), (6, "JOD")])
def test_custom_checkout_matches_existing_frozen_quote_transport(monkeypatch, months, currency):
    amount = Decimal("105.78")
    period = {1: "monthly", 3: "three-months", 6: "six-months"}[months]
    terms = ({"currency": "USD", "monthlyPriceUsd": str(amount), "billingPeriodMonths": 1}
             if currency == "USD" else {"currency": "JOD", "paymentCurrency": "USD", "paymentAmountUsd": str(amount),
                "amount": str(amount * Decimal("0.709")), "periodCode": period, "billingPeriodMonths": months,
                "fx": {"rate": "0.709", "sourceCurrency": "USD", "targetCurrency": "JOD"}})
    frozen = {"commercial_terms": terms, "attempt_id": "attempt-A", "revision_id": "revision-A"}
    before = deepcopy(frozen)
    monkeypatch.setattr(config, "payments_enabled", lambda: True)
    monkeypatch.setattr(config, "app_base_url", lambda: "https://keel.example.test")
    monkeypatch.setattr(store, "current_subscription", lambda *a: None)
    monkeypatch.setattr(custom_offers, "custom_checkout_prepare", lambda *a, **k: frozen)
    monkeypatch.setattr(custom_offers, "record_custom_checkout_session", lambda *a, **k: None)
    monkeypatch.setattr(service, "_ensure_customer", lambda *a: "cus_existing")
    calls = []

    def create(params, idempotency_key):
        calls.append((deepcopy(params), idempotency_key))
        return {"id": "cs_test_custom", "url": "https://checkout.example.test"}
    monkeypatch.setattr(stripe_api, "create_checkout_session", create)
    service._create_custom_quote_checkout(MagicMock(), MagicMock(), "tenant-A", "e", "c", "quote-A", "retry-A")
    expected, key = calls.pop()
    payment, interval, _ = self_service.checkout_terms(terms)
    StripeGateway().create_checkout(checkout_intent(
        price=None, recurring_amount=Money(payment, "USD"), interval_months=interval, product_name="KEEL Custom Plan",
        idempotency_key=key, client_reference="attempt-A", allow_promotion_entry=False,
        metadata=expected["metadata"], subscription_metadata=expected["subscription_data"]["metadata"]))
    assert calls == [(expected, key)]
    assert frozen == before


def test_legacy_frozen_request_replays_unchanged_even_if_sdk_mutates_input(monkeypatch):
    params = {"customer": "cus_old", "line_items": [{"price": "price_retired", "quantity": 1}],
              "subscription_data": {"trial_end": 12345678, "metadata": {"quote": "old-revision"}},
              "unknown_legacy_field": {"preserve": [1, 2, 3]}}
    original, calls = deepcopy(params), []

    def create(request, idempotency_key):
        calls.append((deepcopy(request), idempotency_key))
        request["subscription_data"]["metadata"].clear()
        return {"id": "cs_test_old", "status": "open"}
    monkeypatch.setattr(stripe_api, "create_checkout_session", create)
    for _ in range(2):
        StripeGateway().replay_frozen_checkout(params, idempotency_key="original-provider-key")
    assert calls == [(original, "original-provider-key")] * 2
    assert params == original


@pytest.mark.parametrize("trial", [False, True])
@pytest.mark.parametrize("upgrade", [False, True])
@pytest.mark.parametrize("pending", [False, True])
def test_subscription_change_requests_match_current_service(monkeypatch, trial, upgrade, pending):
    current = remote_subscription(trial=trial, pending=pending)
    phase = {"start_date": 1799990000, "end_date": 1802700000,
             "items": [{"price": {"id": "price_old"}, "quantity": 2, "metadata": {"keep": "yes"}, "tax_rates": ["txr"]}],
             "automatic_tax": {"enabled": True}, "discounts": [{"coupon": "coupon"}],
             "invoice_settings": {"days_until_due": 7}, "metadata": {"legacy": "kept"},
             "default_payment_method": "pm_keep", "currency": "usd"}
    schedule = {"current_phase": {"start_date": phase["start_date"], "end_date": phase["end_date"]}, "phases": [phase]}
    local = {"stripe_subscription_id": "sub_existing"}
    calls = []
    monkeypatch.setattr(service, "_plan_change_context", lambda *a: (local, {"stripe_price_id": "price_new"}, upgrade, {}, {}))
    monkeypatch.setattr(service, "_validate_transition_snapshot", lambda *a: NOW.timestamp())
    monkeypatch.setattr(store, "set_schedule", lambda *a: None)
    monkeypatch.setattr(stripe_api, "retrieve_subscription", lambda *a: deepcopy(current))
    monkeypatch.setattr(stripe_api, "retrieve_schedule", lambda *a: deepcopy(schedule))
    monkeypatch.setattr(stripe_api, "retrieve_invoice", lambda *a: {"hosted_invoice_url": "https://invoice.example.test"})
    monkeypatch.setattr(stripe_api, "release_schedule", lambda *a: calls.append(("release", a)))

    def modify(identifier, **params):
        calls.append(("modify", identifier, deepcopy(params)))
        return deepcopy(current)
    monkeypatch.setattr(stripe_api, "modify_subscription", modify)
    monkeypatch.setattr(stripe_api, "modify_schedule", lambda identifier, **p: calls.append(("schedule", identifier, deepcopy(p))))
    before = deepcopy(phase)
    service._change_plan_locked(None, MagicMock(), "tenant-A", "growth", "monthly")
    expected, calls[:] = calls[:], []
    intent = SubscriptionChangeIntent(Ref("stripe", "sub_existing"), Ref("stripe", "price_new"), CUTOFF if trial else None)
    if upgrade:
        result = StripeGateway().change_subscription(intent)
        assert result.payment_required is pending
        assert result.payment_url == ("https://invoice.example.test" if pending else None)
    else:
        result = StripeGateway().schedule_change(intent, now=NOW)
        assert result.effective_at == (CUTOFF if trial else datetime.fromtimestamp(1802700000, timezone.utc))
    assert calls == expected
    assert phase == before


@pytest.mark.parametrize("error,outcome", [
    (stripe.InvalidRequestError("private", "price", http_status=400), Outcome.REJECTED),
    (TimeoutError("private"), Outcome.OUTCOME_UNKNOWN),
    (stripe.APIConnectionError("private"), Outcome.OUTCOME_UNKNOWN),
    (stripe.APIError("private", http_status=500), Outcome.OUTCOME_UNKNOWN),
    (stripe.InvalidRequestError("private", "id", http_status=404), Outcome.NOT_FOUND),
    (stripe_api.PaymentsNotConfigured("private"), Outcome.UNAVAILABLE),
])
def test_checkout_error_classification_preserves_uncertain_outcomes(monkeypatch, error, outcome):
    def fail(*a, **k):
        raise error
    monkeypatch.setattr(stripe_api, "create_checkout_session", fail)
    with pytest.raises(PaymentProviderError) as caught:
        StripeGateway().create_checkout(checkout_intent())
    assert caught.value.outcome == outcome
    assert "private" not in str(caught.value)


def test_partial_change_is_unknown_even_if_later_write_is_rejected(monkeypatch):
    monkeypatch.setattr(stripe_api, "retrieve_subscription", lambda *a: remote_subscription())
    released = []
    monkeypatch.setattr(stripe_api, "release_schedule", lambda *a: released.append(a))
    def reject(*a, **k):
        raise stripe.InvalidRequestError("rejected", "price", http_status=400)
    monkeypatch.setattr(stripe_api, "modify_subscription", reject)
    with pytest.raises(PaymentProviderError) as caught:
        StripeGateway().change_subscription(SubscriptionChangeIntent(Ref("stripe", "sub_existing"), Ref("stripe", "price_new")))
    assert released and caught.value.outcome == Outcome.OUTCOME_UNKNOWN


def test_schedule_creation_preserves_trial_and_failed_later_write_is_not_a_definite_rejection(monkeypatch):
    monkeypatch.setattr(stripe_api, "retrieve_subscription", lambda *a: remote_subscription(trial=True, schedule=None))
    calls = []
    monkeypatch.setattr(stripe_api, "create_schedule_from_subscription", lambda *a: calls.append(("create", a)) or {"id": "sched_new"})
    monkeypatch.setattr(stripe_api, "retrieve_schedule", lambda *a: {"phases": [{
        "start_date": 1799990000, "end_date": 1802700000, "items": [{"price": "price_old"}]}]})
    monkeypatch.setattr(stripe_api, "modify_schedule", lambda *a, **k: calls.append(("update", a, k)))
    intent = SubscriptionChangeIntent(Ref("stripe", "sub_existing"), Ref("stripe", "price_new"), CUTOFF)
    result = StripeGateway().schedule_change(intent, now=NOW)
    assert result.schedule == Ref("stripe", "sched_new") and result.effective_at == CUTOFF
    assert calls[0] == ("create", ("sub_existing",))
    assert calls[1][2]["phases"][0] == {"start_date": 1799990000, "end_date": int(CUTOFF.timestamp()),
                                             "trial_end": int(CUTOFF.timestamp()), "items": [{"price": "price_old", "quantity": 1}]}
    def reject(*a, **k):
        raise stripe.InvalidRequestError("private", "phases", http_status=400)
    monkeypatch.setattr(stripe_api, "modify_schedule", reject)
    with pytest.raises(PaymentProviderError) as caught:
        StripeGateway().schedule_change(intent, now=NOW)
    assert caught.value.outcome == Outcome.OUTCOME_UNKNOWN


def test_schedule_one_time_invoice_items_are_not_repeated_or_dropped(monkeypatch):
    monkeypatch.setattr(stripe_api, "retrieve_subscription", lambda *a: remote_subscription())
    monkeypatch.setattr(stripe_api, "retrieve_schedule", lambda *a: {"phases": [{
        "start_date": 1799990000, "end_date": 1802700000, "items": [{"price": "price_old"}],
        "add_invoice_items": [{"price": "price_one_time"}]}]})
    with pytest.raises(PaymentProviderError) as caught:
        StripeGateway().schedule_change(SubscriptionChangeIntent(Ref("stripe", "sub_existing"), Ref("stripe", "price_new")), now=NOW)
    assert caught.value.outcome == Outcome.UNSUPPORTED_CAPABILITY


def test_trial_cutoff_conflict_is_rejected_before_provider_mutation(monkeypatch):
    monkeypatch.setattr(stripe_api, "retrieve_subscription", lambda *a: remote_subscription(trial=True))
    with pytest.raises(PaymentProviderError) as caught:
        StripeGateway().change_subscription(SubscriptionChangeIntent(Ref("stripe", "sub_existing"), Ref("stripe", "price_new")))
    assert caught.value.outcome == Outcome.REJECTED


def test_failed_read_is_unavailable_rather_than_unknown_write(monkeypatch):
    def fail(*a, **k):
        raise TimeoutError("private details")
    monkeypatch.setattr(stripe_api, "retrieve_invoice", fail)
    with pytest.raises(PaymentProviderError) as caught:
        StripeGateway().get_invoice(Ref("stripe", "in_existing"))
    assert caught.value.outcome == Outcome.UNAVAILABLE


def test_successful_change_followed_by_failed_invoice_read_stays_unknown(monkeypatch):
    current = remote_subscription(pending=True, schedule=None)
    monkeypatch.setattr(stripe_api, "retrieve_subscription", lambda *a: current)
    monkeypatch.setattr(stripe_api, "modify_subscription", lambda *a, **k: current)
    def fail(*a, **k):
        raise stripe.InvalidRequestError("missing", "invoice", http_status=404)
    monkeypatch.setattr(stripe_api, "retrieve_invoice", fail)
    with pytest.raises(PaymentProviderError) as caught:
        StripeGateway().change_subscription(SubscriptionChangeIntent(Ref("stripe", "sub_existing"), Ref("stripe", "price_new")))
    assert caught.value.outcome == Outcome.OUTCOME_UNKNOWN


def test_malformed_response_cannot_become_a_successful_snapshot(monkeypatch):
    monkeypatch.setattr(stripe_api, "retrieve_subscription", lambda *a: {"id": "sub_existing", "customer": None})
    with pytest.raises(PaymentProviderError) as caught:
        StripeGateway().get_subscription(Ref("stripe", "sub_existing"))
    assert caught.value.outcome == Outcome.UNAVAILABLE


@pytest.mark.parametrize("mode,is_subscription", [("subscription", True), ("payment", False)])
def test_open_checkout_preserves_subscription_mode_for_overlap_checks(monkeypatch, mode, is_subscription):
    monkeypatch.setattr(stripe_api, "open_customer_checkouts", lambda *a: [{"id": "cs_test_one", "mode": mode, "status": "open"}])
    assert StripeGateway().list_open_checkouts(Ref("stripe", "cus_existing"))[0].is_subscription is is_subscription


@pytest.mark.parametrize("value", [0.1, Decimal("NaN"), Decimal("Infinity"), Decimal("-1")])
def test_money_rejects_float_and_invalid_values(value):
    with pytest.raises(ValueError):
        Money(value, "USD")


def test_gateway_refuses_foreign_references_and_lossy_inline_money_before_network():
    with pytest.raises(PaymentProviderError) as caught:
        StripeGateway().get_subscription(Ref("other", "subscription-alpha"))
    assert caught.value.outcome == Outcome.UNSUPPORTED_CAPABILITY
    for amount in (Money(Decimal("1.001"), "USD"), Money(Decimal("1"), "JOD")):
        with pytest.raises(PaymentProviderError) as caught:
            StripeGateway().create_checkout(checkout_intent(price=None, recurring_amount=amount, product_name="Approved"))
        assert caught.value.outcome == Outcome.UNSUPPORTED_CAPABILITY


@pytest.mark.parametrize("state,expected", [(s.value, s) for s in SubscriptionState if s != SubscriptionState.UNKNOWN]
                         + [("incomplete", SubscriptionState.PENDING), ("unpaid", SubscriptionState.PAYMENT_FAILED),
                            ("incomplete_expired", SubscriptionState.EXPIRED), ("canceled", SubscriptionState.CANCELLED),
                            ("future_status", SubscriptionState.UNKNOWN)])
@pytest.mark.parametrize("item_period", [False, True])
def test_subscription_snapshots_normalize_states_expansion_and_period_versions(monkeypatch, state, expected, item_period):
    raw = remote_subscription(item_period=item_period)
    raw.update(status=state, customer={"id": "cus_existing"})
    monkeypatch.setattr(stripe_api, "retrieve_subscription", lambda *a: raw)
    result = StripeGateway().get_subscription(Ref("stripe", "sub_existing"))
    assert result.state == expected and result.customer == Ref("stripe", "cus_existing")
    assert result.items[0].quantity == 2
    assert result.period_start == datetime.fromtimestamp(1799990000, timezone.utc)
    assert result.period_end == datetime.fromtimestamp(1802700000, timezone.utc)


def test_gateway_consumes_real_sdk_objects_through_existing_plain_wrapper(monkeypatch):
    class Client:
        class Subscription:
            retrieve = staticmethod(lambda identifier: stripe.Subscription.construct_from(
                remote_subscription(), "sk_test_offline"))
    monkeypatch.setattr(stripe_api, "_client", lambda: Client)
    result = StripeGateway().get_subscription(Ref("stripe", "sub_existing"))
    assert result.reference == Ref("stripe", "sub_existing")
    assert result.items[0].price == Ref("stripe", "price_old")


@pytest.mark.parametrize("currency,amount", [("ISK", "5"), ("UGX", "5"), ("JPY", "500")])
def test_invoice_money_preserves_existing_currency_representation(monkeypatch, currency, amount):
    monkeypatch.setattr(stripe_api, "retrieve_invoice", lambda *a: {
        "id": "in_existing", "currency": currency, "amount_paid": 500, "status": "paid"})
    result = StripeGateway().get_invoice(Ref("stripe", "in_existing"))
    assert result.amount_paid == Money(Decimal(amount), currency)


@pytest.mark.parametrize("shape", ["parent", "subscription_details", "subscription"])
@pytest.mark.parametrize("paid", [False, True])
def test_invoice_evidence_preserves_zero_payment_and_period_coverage(monkeypatch, shape, paid):
    raw = {"id": "in_existing", "customer": {"id": "cus_existing"}, "currency": "usd", "amount_paid": 0,
           "amount_due": 2900, "status": "paid" if paid else "draft", "billing_reason": "subscription_create",
           "lines": {"data": [{"period": {"start": 1800000000, "end": 1802700000}}]}}
    if shape == "parent":
        raw["parent"] = {"subscription_details": {"subscription": {"id": "sub_existing"}}}
    elif shape == "subscription_details":
        raw[shape] = {"subscription": "sub_existing"}
    else:
        raw[shape] = "sub_existing"
    monkeypatch.setattr(stripe_api, "retrieve_invoice", lambda *a: raw)
    result = StripeGateway().get_invoice(Ref("stripe", "in_existing"))
    assert result.subscription == Ref("stripe", "sub_existing")
    assert result.amount_paid == Money(Decimal("0"), "USD")
    assert result.amount_due == Money(Decimal("29"), "USD")
    assert result.payment_state == (PaymentState.PAID if paid else PaymentState.UNPAID)
    assert result.coverage == ((NOW, datetime.fromtimestamp(1802700000, timezone.utc)),)


def test_customer_lists_checkout_expiry_cancellation_resume_portal_and_schedule_release(monkeypatch):
    gateway, calls = StripeGateway(), []
    monkeypatch.setattr(stripe_api, "create_customer", lambda *a: calls.append(a) or {"id": "cus_existing"})
    assert gateway.create_customer(email="e", company_name="c", tenant_reference="tenant-A", idempotency_key="key") == Ref("stripe", "cus_existing")
    assert calls.pop() == ("e", "c", "tenant-A", "key")
    monkeypatch.setattr(stripe_api, "customer_subscriptions", lambda *a: [remote_subscription()])
    monkeypatch.setattr(stripe_api, "open_customer_checkouts", lambda *a: [{"id": "cs_test_one", "status": "open"}])
    assert len(gateway.list_customer_subscriptions(Ref("stripe", "cus_existing"))) == 1
    assert gateway.list_open_checkouts(Ref("stripe", "cus_existing"))[0].state == CheckoutState.OPEN
    monkeypatch.setattr(stripe_api, "retrieve_checkout_session", lambda *a: {"id": "cs_test_one", "status": "complete", "payment_status": "no_payment_required"})
    assert gateway.get_checkout(Ref("stripe", "cs_test_one")).payment_state == PaymentState.NOT_REQUIRED
    monkeypatch.setattr(stripe_api, "expire_checkout_session", lambda *a: {"id": "cs_test_one", "status": "expired"})
    assert gateway.expire_checkout(Ref("stripe", "cs_test_one")).state == CheckoutState.EXPIRED
    monkeypatch.setattr(stripe_api, "retrieve_subscription", lambda *a: remote_subscription())
    monkeypatch.setattr(stripe_api, "release_schedule", lambda *a: calls.append(("release", a)))
    monkeypatch.setattr(stripe_api, "modify_subscription", lambda *a, **k: calls.append(("modify", a, k)) or remote_subscription())
    gateway.set_cancellation(Ref("stripe", "sub_existing"), cancel_at_period_end=True)
    gateway.set_cancellation(Ref("stripe", "sub_existing"), cancel_at_period_end=False)
    assert calls == [("release", ("sched_existing",)), ("modify", ("sub_existing",), {"cancel_at_period_end": True}),
                     ("modify", ("sub_existing",), {"cancel_at_period_end": False})]
    assert gateway.cancel_scheduled_change(Ref("stripe", "sched_existing")) == Outcome.SUCCESS
    monkeypatch.setattr(stripe_api, "create_portal_session", lambda *a: {"url": "https://portal.example.test"})
    assert gateway.create_portal(Ref("stripe", "cus_existing"), return_url="https://keel.example.test/billing") == "https://portal.example.test"


def test_provider_independent_fake_exercises_application_contract():
    class FakeGateway:
        """No SDK classes, provider dictionaries, prefix parsing or event names."""
        def create_checkout(self, intent):
            self.intent = intent
            return CheckoutSnapshot(Ref("another", "purchase-alpha"), CheckoutState.OPEN, PaymentState.UNPAID,
                                    customer=intent.customer, url="https://payments.example.test")

        def get_subscription(self, reference):
            return SubscriptionSnapshot(reference, Ref("another", "account-alpha"), SubscriptionState.PENDING,
                                        (), None, None, None, False, None)

        def unsupported(self, *args, **kwargs):
            raise PaymentProviderError(Outcome.UNSUPPORTED_CAPABILITY)

        create_customer = list_customer_subscriptions = list_open_checkouts = unsupported
        get_checkout = expire_checkout = change_subscription = schedule_change = unsupported
        cancel_scheduled_change = set_cancellation = get_invoice = create_portal = unsupported

    def prepare(gateway: SubscriptionPaymentGateway, intent: CheckoutIntent):
        return gateway.create_checkout(intent)

    fake = FakeGateway()
    intent = checkout_intent(customer=Ref("another", "account-alpha"), price=Ref("another", "offer-alpha"))
    result = prepare(fake, intent)
    assert result.reference == Ref("another", "purchase-alpha")
    assert fake.get_subscription(Ref("another", "contract-alpha")).state == SubscriptionState.PENDING
    assert result.payment_state == PaymentState.UNPAID  # a hosted redirect grants nothing
