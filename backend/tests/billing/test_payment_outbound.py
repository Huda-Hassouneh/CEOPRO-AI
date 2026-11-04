"""Outbound wiring: neutral application doubles and real durable-DB compatibility.

Provider transport is always offline. These tests never grant billing rights.
"""
from contextlib import closing
import ast
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.ai.billing import checkout_attempts, custom_offers, service, store, stripe_api
from src.ai.billing.payment_contracts import (
    CheckoutIntent, CheckoutSnapshot, CheckoutState, FrozenCheckoutRequest, Money,
    PaymentProviderError, PaymentState, ProviderOperationOutcome as Outcome,
    ProviderReference as Ref, ScheduledChange, SubscriptionChangeResult,
    SubscriptionSnapshot, SubscriptionState,
)
from src.ai.billing.stripe_gateway import StripeGateway
from .test_reconciliation_roles import restricted_runtime  # noqa: F401


NOW = datetime(2027, 1, 15, tzinfo=timezone.utc)


class OtherGateway:
    """Application double with no Stripe SDK classes, payloads or ID prefixes."""
    provider = "another"

    def __init__(self):
        self.prepared, self.sent, self.actions = [], [], []
        self.current = SubscriptionSnapshot(
            Ref(self.provider, "contract-alpha"), Ref(self.provider, "account-alpha"),
            SubscriptionState.ACTIVE, (), NOW - timedelta(days=5), NOW + timedelta(days=25),
            None, False, None, schedule=Ref(self.provider, "future-change-alpha"))

    def customer_time(self, customer, *, tenant_reference, require_clock=False):
        return None

    def create_customer(self, **fields):
        self.actions.append(("customer", fields))
        return Ref(self.provider, "account-alpha")

    def list_customer_subscriptions(self, customer):
        return ()

    def list_open_checkouts(self, customer):
        return ()

    def prepare_checkout(self, intent):
        self.prepared.append(intent)
        return FrozenCheckoutRequest(self.provider, intent.idempotency_key, {"opaque": "approved-contract"})

    def submit_checkout(self, request):
        self.sent.append(request)
        return CheckoutSnapshot(Ref(self.provider, "purchase-alpha"), CheckoutState.OPEN,
            PaymentState.UNPAID, url="https://payments.example.test/hosted")

    def create_checkout(self, intent):
        return self.submit_checkout(self.prepare_checkout(intent))

    def get_checkout(self, reference):
        return self.submit_checkout(None)

    def expire_checkout(self, reference):
        self.actions.append(("expire", reference))
        return CheckoutSnapshot(reference, CheckoutState.EXPIRED, PaymentState.UNPAID)

    def get_subscription(self, reference):
        assert reference == self.current.reference
        return self.current

    def change_subscription(self, intent, *, current, resolve_payment_url=True):
        assert current is self.current
        self.actions.append(("change", intent))
        return SubscriptionChangeResult(current, False)

    def schedule_change(self, intent, *, now, current):
        assert current is self.current
        self.actions.append(("schedule", intent, now))
        return ScheduledChange(Ref(self.provider, "future-change-alpha"), current.trial_end or current.period_end)

    def cancel_scheduled_change(self, schedule):
        self.actions.append(("release", schedule))
        return Outcome.SUCCESS

    def set_cancellation(self, reference, *, cancel_at_period_end):
        self.actions.append(("cancellation", reference, cancel_at_period_end))
        return replace(self.current, cancel_at_period_end=cancel_at_period_end)

    def create_portal(self, customer, *, return_url):
        self.actions.append(("portal", customer, return_url))
        return "https://payments.example.test/account"

    def get_invoice(self, reference):
        raise PaymentProviderError(Outcome.UNSUPPORTED_CAPABILITY)


@pytest.fixture
def application(monkeypatch, memory_checkout_reservations):
    gateway = OtherGateway()
    monkeypatch.setattr(service, "payment_gateway", lambda: gateway)
    monkeypatch.setattr(service.config, "payments_enabled", lambda: True)
    monkeypatch.setattr(service.config, "app_base_url", lambda: "https://keel.example.test")
    monkeypatch.setattr(service.config, "automatic_tax", lambda: False)
    monkeypatch.setattr(service.time, "time", lambda: NOW.timestamp())
    monkeypatch.setattr(store, "current_subscription", lambda *a: None)
    monkeypatch.setattr(store, "current_price", lambda *a: {
        "is_active": True, "self_serve": True, "stripe_price_id": "offer-alpha"})
    monkeypatch.setattr(store, "trial", lambda *a: None)
    monkeypatch.setattr(store, "save_customer", lambda *a: None)
    return gateway


@pytest.mark.parametrize("days,keeps_trial", [(1, False), (2, False), (3, True)])
def test_standard_application_uses_neutral_intent_and_original_trial_rule(application, monkeypatch, days, keeps_trial):
    cutoff = NOW + timedelta(days=days)
    monkeypatch.setattr(store, "trial", lambda *a: {"ends_at": cutoff})
    result = service.create_checkout(None, MagicMock(), "tenant-alpha", "owner@example.test", "Company", "growth", "monthly")
    intent = application.prepared[0]
    assert intent.customer == Ref("another", "account-alpha")
    assert intent.price == Ref("another", "offer-alpha")
    assert intent.trial_end == (cutoff if keeps_trial else None)
    assert intent.metadata == intent.subscription_metadata == {
        "tenant_id": "tenant-alpha", "plan_key": "growth", "period_code": "monthly"}
    assert intent.idempotency_key.startswith("apex-checkout-")
    assert application.sent[0].idempotency_key == intent.idempotency_key
    assert result == {"session_id": "purchase-alpha", "url": "https://payments.example.test/hosted"}


def test_customer_reuse_checks_mapping_and_does_not_create_again(application, monkeypatch):
    monkeypatch.setattr(store, "customer_id", lambda *a: "account-alpha")
    checks = []
    monkeypatch.setattr(application, "customer_time", lambda *a, **k: checks.append((a, k)))
    assert service._ensure_customer(None, None, "tenant-alpha", "e", "c") == "account-alpha"
    assert checks == [((Ref("another", "account-alpha"),), {"tenant_reference": "tenant-alpha", "require_clock": True})]
    assert not application.actions


@pytest.mark.parametrize('days',[14,7])
def test_selected_trial_business_request_is_provider_neutral(application,monkeypatch,days):
    from src.ai.billing import trial_checkouts
    monkeypatch.setattr(store,'trial_eligibility',lambda *a:None)
    monkeypatch.setattr(trial_checkouts,'reserve',lambda *a:{'trial_duration_days':days})
    result=service.create_checkout(None,MagicMock(),'tenant-alpha','owner@example.test','Company','selected-plan','monthly',actor_user_id='actor',trial_requested=True)
    intent=application.prepared[0]
    assert intent.trial_duration_days==days and intent.trial_end is None
    assert intent.require_payment_method_before_activation is True
    assert intent.price==Ref('another','offer-alpha')
    assert intent.subscription_metadata['keel_trial_attempt_id']
    assert result['url']=='https://payments.example.test/hosted'


def test_active_subscription_blocks_before_any_gateway_action(application, monkeypatch):
    monkeypatch.setattr(store, "current_subscription", lambda *a: {"status": "active"})
    with pytest.raises(service.BillingError) as error:
        service.create_checkout(None, None, "tenant-alpha", "e", "c", "growth", "monthly")
    assert error.value.code == "subscription_exists"
    assert not application.actions and not application.prepared and not application.sent


@pytest.mark.parametrize("months", [1, 3, 6])
def test_custom_application_intent_uses_only_frozen_approved_terms(application, monkeypatch, months):
    terms = {"currency": "JOD", "paymentCurrency": "USD", "paymentAmountUsd": "123.45",
             "amount": str(Decimal("123.45") * Decimal("0.709")),
             "fx": {"rate": "0.709", "sourceCurrency": "USD", "targetCurrency": "JOD"},
             "billingPeriodMonths": months, "periodCode": {1: "monthly", 3: "three-months", 6: "six-months"}[months]}
    prepared = {"attempt_id": "attempt-alpha", "revision_id": "revision-alpha", "commercial_terms": terms}
    monkeypatch.setattr(custom_offers, "custom_checkout_prepare", lambda *a, **k: deepcopy(prepared))
    recorded = []
    monkeypatch.setattr(custom_offers, "record_custom_checkout_session", lambda *a, **k: recorded.append(k))
    result = service._create_custom_quote_checkout(MagicMock(), MagicMock(), "tenant-alpha", "e", "c", "quote-alpha", "retry-alpha")
    intent = application.prepared[0]
    assert intent.recurring_amount == Money(Decimal("123.45"), "USD")
    assert intent.interval_months == months and not intent.allow_promotion_entry
    assert intent.metadata == intent.subscription_metadata == {
        "tenant_id": "tenant-alpha", "custom_quote_id": "quote-alpha", "custom_quote_revision_id": "revision-alpha",
        "quote_attempt_id": "attempt-alpha", "billing_kind": "custom_quote"}
    assert recorded == [{"attempt_id": "attempt-alpha", "session_id": "purchase-alpha"}]
    assert result["attempt_id"] == "attempt-alpha"


@pytest.mark.parametrize("upgrade", [False, True])
@pytest.mark.parametrize("trial", [False, True])
def test_application_owns_transition_decision_and_passes_validated_snapshot(application, monkeypatch, upgrade, trial):
    if trial:
        application.current = replace(application.current, state=SubscriptionState.TRIALING, trial_end=NOW + timedelta(days=7))
    remote = application.current
    local = {"stripe_subscription_id": remote.reference.opaque_id, "status": remote.state.value,
             "current_period_start": remote.period_start, "current_period_end": remote.period_end, "trial_end": remote.trial_end}
    monkeypatch.setattr(service, "_plan_change_context", lambda *a: (local, {"stripe_price_id": "offer-beta"}, upgrade, {}, {}))
    changes = []
    monkeypatch.setattr(store, "set_schedule", lambda *a: changes.append(a))
    result = service.change_plan(None, MagicMock(), "tenant-alpha", "growth", "monthly")
    action = application.actions[0]
    assert action[0] == ("change" if upgrade else "schedule")
    assert action[1].price == Ref("another", "offer-beta")
    assert action[1].trial_end == remote.trial_end
    assert changes[0][-2:] == ((None, None) if upgrade else ("growth", "monthly"))
    assert result["state"] == ("applied" if upgrade else "scheduled")


def test_stale_subscription_snapshot_blocks_provider_write(application, monkeypatch):
    local = {"stripe_subscription_id": "contract-alpha", "status": "active", "current_period_start": NOW,
             "current_period_end": NOW + timedelta(days=1), "trial_end": None}
    monkeypatch.setattr(service, "_plan_change_context", lambda *a: (local, {"stripe_price_id": "offer-beta"}, True, {}, {}))
    with pytest.raises(service.BillingError) as error:
        service.change_plan(None, MagicMock(), "tenant-alpha", "growth", "monthly")
    assert error.value.code == "billing_reconciling"
    assert not application.actions


@pytest.mark.parametrize("cancel", [False, True])
def test_cancellation_and_resume_do_not_write_local_subscription(application, monkeypatch, cancel):
    remote = application.current
    monkeypatch.setattr(store, "current_subscription", lambda *a: {
        "stripe_subscription_id": "contract-alpha", "cancel_at_period_end": not cancel, "current_period_end": remote.period_end})
    result = service.set_cancellation(None, "tenant-alpha", cancel)
    assert application.actions == [("cancellation", remote.reference, cancel)]
    assert result == {"state": "cancelling" if cancel else "resumed", "access_until": remote.period_end.isoformat()}


def test_cancel_scheduled_change_validates_snapshot_before_releasing(application, monkeypatch):
    remote = application.current
    monkeypatch.setattr(store, "current_subscription", lambda *a: {
        "stripe_subscription_id": "contract-alpha", "status": "active", "scheduled_plan_key": "starter",
        "current_period_start": remote.period_start, "current_period_end": remote.period_end, "trial_end": None})
    updates = []
    monkeypatch.setattr(store, "set_schedule", lambda *a: updates.append(a))
    assert service.cancel_scheduled_change(None, MagicMock(), "tenant-alpha") == {"state": "cancelled"}
    assert application.actions == [("release", remote.schedule)]
    assert updates[0][-2:] == (None, None)


def test_portal_keeps_return_origin_in_application(application, monkeypatch):
    monkeypatch.setattr(store, "customer_id", lambda *a: "account-alpha")
    assert service.create_portal(None, "tenant-alpha") == {"url": "https://payments.example.test/account"}
    assert application.actions == [("portal", Ref("another", "account-alpha"), "https://keel.example.test/billing")]


@pytest.mark.parametrize("outcome", [Outcome.REJECTED, Outcome.OUTCOME_UNKNOWN, Outcome.UNAVAILABLE,
                                    Outcome.NOT_FOUND, Outcome.UNSUPPORTED_CAPABILITY])
def test_checkout_outcomes_preserve_durable_retry_distinctions(application, monkeypatch, memory_checkout_reservations, outcome):
    def fail(request):
        raise PaymentProviderError(outcome)
    monkeypatch.setattr(application, "submit_checkout", fail)
    with pytest.raises(PaymentProviderError) as error:
        service.create_checkout(None, MagicMock(), "tenant-alpha", "e", "c", "growth", "monthly")
    assert error.value.outcome == outcome
    assert bool(memory_checkout_reservations) is (outcome != Outcome.REJECTED)


def test_freeze_failure_never_sends_checkout(application, monkeypatch):
    def fail(*a):
        raise RuntimeError("Synthetic persistence failure")
    monkeypatch.setattr(checkout_attempts, "freeze", fail)
    with pytest.raises(RuntimeError, match="persistence failure"):
        service.create_checkout(None, MagicMock(), "tenant-alpha", "e", "c", "growth", "monthly")
    assert not application.sent


def test_unknown_checkout_retry_uses_frozen_request_and_original_key(application, monkeypatch, memory_checkout_reservations):
    original_submit = application.submit_checkout
    sent = []
    def submit(request):
        assert memory_checkout_reservations["tenant-alpha"]["params"] == request.payload
        sent.append(request)
        if len(sent) == 1:
            raise PaymentProviderError(Outcome.OUTCOME_UNKNOWN)
        return original_submit(request)
    monkeypatch.setattr(application, "submit_checkout", submit)
    with pytest.raises(PaymentProviderError):
        service.create_checkout(None, MagicMock(), "tenant-alpha", "e", "c", "growth", "monthly")
    # This retry is within the idempotency window. The unit DB double uses
    # wall-clock creation time; align it with this test's simulated clock.
    memory_checkout_reservations["tenant-alpha"]["created_at"] = NOW
    monkeypatch.setattr(store, "current_price", lambda *a: {
        "is_active": True, "self_serve": True, "stripe_price_id": "offer-newer"})
    monkeypatch.setattr(application, "prepare_checkout", lambda *a: pytest.fail("Retry must not encode current catalog terms"))
    result = service.create_checkout(None, MagicMock(), "tenant-alpha", "e", "c", "growth", "monthly")
    assert result["session_id"] == "purchase-alpha"
    assert sent[0] == sent[1]
    assert len(application.prepared) == 1


@pytest.mark.parametrize("native", [False, True])
def test_legacy_frozen_request_never_runs_new_encoder(monkeypatch, native, request):
    if native:
        request.getfixturevalue("restricted_runtime")
        tid, uid = request.getfixturevalue("tenant")
        from src.ai import db
        setup = db.billing_setup_connection(tid, uid)
    else:
        request.getfixturevalue("memory_checkout_reservations")
        tid, uid, setup = "tenant-alpha", "owner-alpha", None
    gateway = StripeGateway()
    payload = {"customer": "cus_original", "line_items": [{"price": "price_retired", "quantity": 1}],
               "metadata": {"custom_quote_revision_id": "revision-original"},
               "subscription_data": {"trial_end": 12345}, "legacy_extension": {"untouched": [1, 2]}}
    before, calls = deepcopy(payload), []
    def create(params, idempotency_key):
        calls.append((deepcopy(params), idempotency_key))
        params["legacy_extension"].clear()
        return {"id": "cs_test_replayed", "status": "open", "url": "https://checkout.example.test"}
    monkeypatch.setattr(stripe_api, "create_checkout_session", create)
    monkeypatch.setattr(gateway, "prepare_checkout", lambda *a: pytest.fail("Frozen legacy request must bypass encoding"))
    try:
        attempt = checkout_attempts.reserve(setup, tid, "legacy-retry", "growth", "monthly")
        checkout_attempts.freeze(setup, attempt, payload)
        attempt = checkout_attempts.active(setup, tid)
        intent = CheckoutIntent(Ref("stripe", "cus_new"), "original-provider-key", "new-correlation",
            "https://keel.example.test", "https://keel.example.test", {}, {}, price=Ref("stripe", "price_new"))
        for _ in range(2):
            service._send_checkout(gateway, intent, setup, attempt, quote_revision="revision-original")
        assert calls == [(before, "original-provider-key")] * 2
        assert checkout_attempts.active(setup, tid)["params"] == before
        with pytest.raises(service.BillingError) as error:
            service._send_checkout(gateway, intent, setup, attempt, quote_revision="revision-new")
        assert error.value.code == "checkout_pending" and len(calls) == 2
        if native:
            with closing(db.app_role_connection(tid, uid)) as conn:
                assert store.current_subscription(conn, tid) is None
    finally:
        if setup is not None:
            setup.close()


@pytest.mark.parametrize("invoice_failure", [False, True])
def test_upgrade_payment_lookup_occurs_after_local_schedule_commit(monkeypatch, invoice_failure):
    from .test_payment_gateway import remote_subscription
    current = remote_subscription(pending=True)
    order = []
    monkeypatch.setattr(service, "_plan_change_context", lambda *a: (
        {"stripe_subscription_id": "sub_existing"}, {"stripe_price_id": "price_new"}, True, {}, {}))
    monkeypatch.setattr(service, "_validate_transition_snapshot", lambda *a: NOW.timestamp())
    monkeypatch.setattr(stripe_api, "retrieve_subscription", lambda *a: order.append("read") or deepcopy(current))
    monkeypatch.setattr(stripe_api, "release_schedule", lambda *a: order.append("release"))
    monkeypatch.setattr(stripe_api, "modify_subscription", lambda *a, **k: order.append("change") or deepcopy(current))
    monkeypatch.setattr(store, "set_schedule", lambda *a: order.append("local"))
    def invoice(*a):
        order.append("invoice")
        if invoice_failure:
            raise TimeoutError("Synthetic invoice lookup failure after successful change")
        return {"id": "in_existing", "hosted_invoice_url": "https://payments.example.test/recover"}
    monkeypatch.setattr(stripe_api, "retrieve_invoice", invoice)
    conn = MagicMock()
    conn.commit.side_effect = lambda: order.append("commit")
    if invoice_failure:
        with pytest.raises(PaymentProviderError) as error:
            service._change_plan_locked(None, conn, "tenant-alpha", "growth", "monthly")
        assert error.value.outcome == Outcome.OUTCOME_UNKNOWN
    else:
        result = service._change_plan_locked(None, conn, "tenant-alpha", "growth", "monthly")
        assert result == {"state": "payment_required", "timing": "immediate", "payment_url": "https://payments.example.test/recover"}
    assert order == ["read", "release", "change", "local", "commit", "invoice"]


@pytest.mark.parametrize("reason,status,code", [
    ("additional_invoice_items", 409, "plan_transition_unclassified"),
    ("trial_boundary_mismatch", 409, "billing_reconciling"),
    ("schedule_unavailable", 502, "schedule_unavailable"),
])
def test_schedule_review_errors_keep_existing_application_contract(application, monkeypatch, reason, status, code):
    remote = application.current
    local = {"stripe_subscription_id": remote.reference.opaque_id, "status": remote.state.value,
             "current_period_start": remote.period_start, "current_period_end": remote.period_end, "trial_end": remote.trial_end}
    monkeypatch.setattr(service, "_plan_change_context", lambda *a: (local, {"stripe_price_id": "offer-beta"}, False, {}, {}))
    def fail(*a, **k):
        raise PaymentProviderError(Outcome.OUTCOME_UNKNOWN, reason=reason)
    monkeypatch.setattr(application, "schedule_change", fail)
    with pytest.raises(service.BillingError) as error:
        service.change_plan(None, MagicMock(), "tenant-alpha", "starter", "monthly")
    assert (error.value.status, error.value.code) == (status, code)


def test_application_has_no_direct_transport_calls_or_request_encoding():
    tree = ast.parse(Path(service.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert not (isinstance(node.func.value, ast.Name) and node.func.value.id == "stripe_api")
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert node.value not in {"line_items", "subscription_data", "price_data", "proration_behavior", "pending_if_incomplete"}
