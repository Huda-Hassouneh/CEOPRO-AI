"""Contract-only foundations; no provider calls, persistence or access grants."""
from dataclasses import FrozenInstanceError, fields, replace
from datetime import datetime, timezone

import pytest

from src.ai.billing.payment_contracts import (
    ApprovedTrialTerms, CapabilityState, GatewayBinding, GatewayCapabilities,
    GatewayEnvironment, PaymentEventKind, PaymentMethodEvidence, PaymentMethodReadiness,
    ProviderReference, SubscriptionSnapshot, SubscriptionState, VerifiedPaymentEvent,
    CheckoutSnapshot, CheckoutState, PaymentState,
)


NOW = datetime(2026, 11, 7, tzinfo=timezone.utc)
BINDING = GatewayBinding("stripe", GatewayEnvironment.TEST, "merchant-A", "binding-A")


def reference(identifier, binding=BINDING):
    return ProviderReference(binding.provider, identifier, binding=binding)


def terms(**changes):
    return replace(ApprovedTrialTerms(
        "tenant-A", "growth", "catalog-revision-A", 1, "USD", 14, BINDING,
    ), **changes)


def evidence(**changes):
    return replace(PaymentMethodEvidence(
        reference("customer-A"), reference("setup-A"), NOW,
    ), **changes)


def snapshot(**changes):
    return replace(SubscriptionSnapshot(
        reference("subscription-A"), reference("customer-A"), SubscriptionState.TRIALING,
        (), None, None, None, False, None,
    ), **changes)


def event(**changes):
    return replace(VerifiedPaymentEvent(
        "stripe", "event-A", PaymentEventKind.SUBSCRIPTION_CHANGED, NOW,
        None, None, None, None, None, b"original", {"original": True},
    ), **changes)


@pytest.mark.parametrize("changes", [
    {"provider": "another"}, {"environment": GatewayEnvironment.LIVE},
    {"merchant_account_id": "merchant-B"}, {"binding_id": "binding-B"},
])
def test_same_opaque_identifier_is_distinct_across_gateway_bindings(changes):
    other = replace(BINDING, **changes)
    first, second = reference("identical-object-id"), reference("identical-object-id", other)
    assert first != second
    assert len({first, second}) == 2


def test_legacy_reference_constructor_and_equality_remain_valid_but_unscoped():
    legacy = ProviderReference("stripe", "identical-object-id")
    assert legacy == ProviderReference(provider="stripe", opaque_id="identical-object-id")
    assert legacy.binding is None
    assert legacy != reference("identical-object-id")


@pytest.mark.parametrize("changes", [
    {"provider": ""}, {"merchant_account_id": " "}, {"binding_id": None},
    {"binding_id": " binding-A "}, {"environment": "test"}, {"environment": None},
])
def test_binding_requires_explicit_nonempty_identity_and_typed_environment(changes):
    with pytest.raises(ValueError):
        replace(BINDING, **changes)


@pytest.mark.parametrize("binding", [BINDING, "binding-A"])
def test_reference_rejects_mismatched_provider_or_untyped_binding(binding):
    with pytest.raises(ValueError):
        ProviderReference("another", "same-id", binding=binding)


def test_undeclared_capabilities_do_not_qualify():
    assert not GatewayCapabilities().supports_card_backed_trial()
    assert all(getattr(GatewayCapabilities(), item.name) is CapabilityState.UNKNOWN
               for item in fields(GatewayCapabilities))


@pytest.mark.parametrize("requirement", [
    "hosted_checkout", "reusable_payment_method", "setup_without_charge", "off_session_recurring",
    "trial_subscription_setup", "authenticated_webhooks", "authoritative_reconciliation",
    "idempotent_submission", "cancellation",
])
@pytest.mark.parametrize("state", [CapabilityState.UNSUPPORTED, CapabilityState.UNKNOWN,
                                   CapabilityState.REQUIRES_APPROVAL])
def test_every_card_backed_trial_requirement_must_be_explicitly_supported(requirement, state):
    supported = GatewayCapabilities(**{item.name: CapabilityState.SUPPORTED for item in fields(GatewayCapabilities)})
    assert supported.supports_card_backed_trial()
    assert not replace(supported, **{requirement: state}).supports_card_backed_trial()


@pytest.mark.parametrize("invalid", [None, True, "supported"])
def test_capabilities_cannot_accept_truthy_or_untyped_shortcuts(invalid):
    with pytest.raises(ValueError):
        GatewayCapabilities(hosted_checkout=invalid)


@pytest.mark.parametrize("name", [item.name for item in fields(ApprovedTrialTerms)])
def test_approved_trial_terms_are_frozen(name):
    approved = terms()
    with pytest.raises(FrozenInstanceError):
        setattr(approved, name, "changed")
    with pytest.raises(FrozenInstanceError):
        approved.binding.environment = GatewayEnvironment.LIVE


def test_terms_normalize_currency_without_changing_money_or_policy():
    assert terms(currency="jod").currency == "JOD"
    assert terms(interval_months=12).interval_months == 12


@pytest.mark.parametrize("changes", [
    {"tenant_id": ""}, {"plan_key": None}, {"catalog_revision_id": []},
    {"interval_months": 0}, {"interval_months": True}, {"trial_duration_days": -1},
    {"trial_duration_days": True}, {"currency": "US"}, {"currency": "123"}, {"binding": None},
])
def test_terms_reject_missing_or_invalid_approved_inputs(changes):
    with pytest.raises(ValueError):
        terms(**changes)


def test_readiness_states_are_distinct_and_no_legacy_value_implies_authority():
    observations = [evidence(readiness=state, payment_method=reference("method-A"))
                    for state in PaymentMethodReadiness]
    assert len(set(observations)) == 5
    assert evidence().readiness is PaymentMethodReadiness.UNKNOWN
    assert {item.readiness for item in observations} == {
        PaymentMethodReadiness.ATTACHED, PaymentMethodReadiness.PENDING_SETUP,
        PaymentMethodReadiness.REUSABLE_AUTHORITY_CONFIRMED, PaymentMethodReadiness.REJECTED,
        PaymentMethodReadiness.UNKNOWN,
    }
    assert snapshot().payment_method_evidence is None
    assert snapshot().trial_start is None


def test_confirmed_readiness_keeps_customer_method_and_observation_provenance():
    observed = evidence(readiness=PaymentMethodReadiness.REUSABLE_AUTHORITY_CONFIRMED,
                        payment_method=reference("method-A"))
    reconciled = snapshot(trial_start=NOW, payment_method_evidence=observed)
    assert reconciled.payment_method_evidence == observed
    assert observed.source == reference("setup-A")
    assert observed.customer == reconciled.customer
    assert observed.observed_at == NOW
    with pytest.raises(FrozenInstanceError):
        observed.readiness = PaymentMethodReadiness.ATTACHED


@pytest.mark.parametrize("changes", [
    {"readiness": True}, {"readiness": "reusable_authority_confirmed"},
    {"readiness": PaymentMethodReadiness.REUSABLE_AUTHORITY_CONFIRMED},
    {"observed_at": NOW.replace(tzinfo=None)}, {"customer": None}, {"source": None},
    {"customer": ProviderReference("stripe", "customer-A")},
    {"source": ProviderReference("stripe", "setup-A")},
    {"source": reference("setup-A", replace(BINDING, environment=GatewayEnvironment.LIVE))},
    {"payment_method": reference("method-A", replace(BINDING, merchant_account_id="merchant-B"))},
])
def test_readiness_evidence_fails_closed_on_missing_provenance_or_scope(changes):
    with pytest.raises(ValueError):
        evidence(**changes)


@pytest.mark.parametrize("changes", [
    {"customer": reference("another-customer")},
    {"reference": reference("subscription-A", replace(BINDING, environment=GatewayEnvironment.LIVE))},
    {"reference": ProviderReference("stripe", "subscription-A")}, {"reference": None},
    {"payment_method_evidence": True}, {"trial_start": NOW.replace(tzinfo=None)},
])
def test_new_subscription_evidence_must_match_customer_and_binding(changes):
    with pytest.raises(ValueError):
        snapshot(**({"payment_method_evidence": evidence()} | changes))


def test_existing_snapshot_and_event_constructors_have_safe_optional_defaults():
    legacy = SubscriptionSnapshot(ProviderReference("stripe", "subscription-A"),
        ProviderReference("stripe", "customer-A"), SubscriptionState.ACTIVE,
        (), NOW, NOW, None, False, None)
    assert legacy.payment_method_evidence is None and legacy.trial_start is None
    assert event().binding is None
    assert event().raw_payload == b"original"
    scoped = event(binding=BINDING, customer=reference("customer-A"), subscription=reference("subscription-A"))
    assert scoped.binding == BINDING
    assert scoped.raw_evidence == event().raw_evidence


@pytest.mark.parametrize("field_name", ["customer", "subscription", "checkout", "invoice", "schedule"])
@pytest.mark.parametrize("binding", [None, replace(BINDING, merchant_account_id="merchant-B"),
                                     replace(BINDING, environment=GatewayEnvironment.LIVE)])
def test_scoped_event_rejects_unscoped_or_mismatched_references(field_name, binding):
    ref = ProviderReference("stripe", "object-A", binding=binding)
    with pytest.raises(ValueError):
        event(binding=BINDING, **{field_name: ref})


@pytest.mark.parametrize("field_name", ["reference", "customer", "subscription", "invoice"])
def test_scoped_event_also_checks_embedded_checkout_evidence(field_name):
    checkout = CheckoutSnapshot(reference("session-A"), CheckoutState.COMPLETE, PaymentState.NOT_REQUIRED)
    with pytest.raises(ValueError):
        event(binding=BINDING, checkout_snapshot=replace(checkout, **{
            field_name: ProviderReference("stripe", "unscoped-object")}))


def test_event_rejects_wrong_provider_for_binding():
    with pytest.raises(ValueError):
        event(provider="another", binding=BINDING)
