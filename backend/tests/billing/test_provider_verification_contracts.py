"""Dormant contract proofs only: no adapters, database, providers or activation."""
import ast
from dataclasses import FrozenInstanceError, fields, replace
from datetime import datetime, timedelta, timezone, tzinfo
from decimal import Decimal
import inspect
from pathlib import Path

import pytest

from src.ai.billing.payment_contracts import (
    ApprovedTrialTerms, CapabilityState, CheckoutState, GatewayBinding,
    GatewayCapabilities, GatewayEnvironment, Money, ObservationProvenance,
    ObservationSource, ObservedRecurringTerms, ObservedSettlement, ObservedTrialWindow,
    PaymentMethodEvidence, PaymentMethodReadiness, PaymentState, ProviderReference,
    ProviderVerificationGateway, ProviderVerificationObservation, RecurringAuthorizationEvidence,
    RecurringAuthorizationKind, RecurringConsentState, SubscriptionObservationRequest,
    SubscriptionPaymentGateway, SubscriptionState, TrialObservationRequest, VerificationOutcome,
)


NOW = datetime(2026, 11, 7, tzinfo=timezone.utc)
END = NOW + timedelta(days=14)
BINDING = GatewayBinding("stripe", GatewayEnvironment.TEST, "merchant-A", "binding-A")
DIGEST = "sha256:" + "a" * 64


def reference(identifier, binding=BINDING):
    return ProviderReference(binding.provider, identifier, binding=binding)


def request(binding=BINDING, **changes):
    return replace(TrialObservationRequest(
        ApprovedTrialTerms("tenant-A", "growth", "catalog-A", 1, "USD", 14, binding),
        DIGEST, "reservation-A", "attempt-A", reference("checkout-A", binding),
        reference("customer-A", binding), "customer-operation-A",
    ), **changes)


def provenance(binding=BINDING, **changes):
    return replace(ObservationProvenance(
        ObservationSource.AUTHORITATIVE_LOOKUP, reference("lookup-A", binding), NOW,
        "synthetic-adapter-v1", "synthetic-api-v1",
    ), **changes)


def authority(binding=BINDING, **changes):
    return replace(RecurringAuthorizationEvidence(
        reference("customer-A", binding), reference("authorization-A", binding),
        RecurringAuthorizationKind.PAYMENT_METHOD_SETUP,
        PaymentMethodReadiness.REUSABLE_AUTHORITY_CONFIRMED,
        RecurringConsentState.RECORDED, reference("consent-A", binding), "agreement-v1",
    ), **changes)


def capabilities(**changes):
    return replace(GatewayCapabilities(**{
        f.name: CapabilityState.SUPPORTED for f in fields(GatewayCapabilities)
    }), **changes)


def observation(binding=BINDING, **changes):
    return replace(ProviderVerificationObservation(
        request(binding), provenance(binding), VerificationOutcome.VERIFIED, capabilities(),
        customer=reference("customer-A", binding), checkout=reference("checkout-A", binding),
        subscription=reference("subscription-A", binding), checkout_state=CheckoutState.COMPLETE,
        subscription_state=SubscriptionState.TRIALING,
        terms=ObservedRecurringTerms(Money(Decimal("59"), "USD"), 1, price=reference("price-A", binding)),
        trial=ObservedTrialWindow(NOW, END, END), recurring_authorization=authority(binding),
    ), **changes)


def settlement(**changes):
    return replace(ObservedSettlement(
        reference("invoice-A"), reference("customer-A"), reference("subscription-A"),
        Money(Decimal("0"), "USD"), PaymentState.PAID, True, True, NOW, ((NOW, END),),
    ), **changes)


def test_complete_trial_observation_preserves_exact_frozen_context_without_activation():
    result = observation()
    assert result.request.tenant_id == "tenant-A"
    assert result.request.binding == BINDING
    assert result.request.approved_terms_digest == DIGEST
    assert result.request.customer_operation_id == "customer-operation-A"
    assert result.request.reservation_id == "reservation-A"
    assert result.request.checkout_attempt_id == "attempt-A"
    assert result.trial.cutoff == END
    assert result.recurring_authorization.consent is RecurringConsentState.RECORDED
    # Even a complete DTO is constructible data, not a signed capability or a grant.
    assert not hasattr(result, "activate") and not hasattr(result, "grant_entitlements")
    assert not hasattr(result, "confirmed_transition_id")


@pytest.mark.parametrize("binding", [
    replace(BINDING, provider="hypothetical-mor", binding_id="mor-binding"),
    replace(BINDING, merchant_account_id="merchant-B", binding_id="account-B-binding"),
    replace(BINDING, environment=GatewayEnvironment.LIVE, binding_id="live-binding"),
    replace(BINDING, binding_id="other-stable-binding"),
])
def test_identical_opaque_ids_never_collapse_provider_account_environment_or_binding(binding):
    first, other = observation(), observation(binding)
    assert first != other
    assert first.customer.opaque_id == other.customer.opaque_id
    assert len({first, other}) == 2


def test_hypothetical_mor_can_use_agreement_evidence_without_exposing_payment_method():
    binding = replace(BINDING, provider="hypothetical-mor", binding_id="mor-binding")
    result = observation(binding, recurring_authorization=authority(
        binding, kind=RecurringAuthorizationKind.PROVIDER_AGREEMENT))
    assert result.outcome is VerificationOutcome.VERIFIED
    assert result.payment_method is None
    assert result.recurring_authorization.source.provider == "hypothetical-mor"
    # A hypothetical declaration is not real provider capability acceptance.


@pytest.mark.parametrize("kind", [RecurringAuthorizationKind.MANDATE,
                                  RecurringAuthorizationKind.PAYMENT_METHOD_SETUP])
def test_authorization_mechanisms_have_shared_semantics_without_setupintent_assumptions(kind):
    assert observation(recurring_authorization=authority(kind=kind)).recurring_authorization.kind is kind


@pytest.mark.parametrize("outcome", [VerificationOutcome.PENDING, VerificationOutcome.CONFLICT,
                                     VerificationOutcome.UNAVAILABLE, VerificationOutcome.UNSUPPORTED])
def test_incomplete_and_unsupported_results_remain_explicit_nonverified_data(outcome):
    result = ProviderVerificationObservation(request(), provenance(), outcome)
    assert result.outcome is not VerificationOutcome.VERIFIED
    assert result.recurring_authorization is None and result.subscription is None
    assert not result.capabilities.supports_card_backed_trial()


def test_default_outcome_is_unavailable_not_implicit_success():
    assert ProviderVerificationObservation(request(), provenance()).outcome is VerificationOutcome.UNAVAILABLE


@pytest.mark.parametrize("changes", [
    {"customer": None}, {"subscription": None}, {"checkout": None}, {"terms": None},
    {"trial": None}, {"recurring_authorization": None},
    {"checkout_state": CheckoutState.OPEN}, {"subscription_state": SubscriptionState.UNKNOWN},
    {"terms": ObservedRecurringTerms(Money(Decimal("59"), "JOD"), 1)},
    {"terms": ObservedRecurringTerms(Money(Decimal("59"), "USD"), 12)},
    {"trial": ObservedTrialWindow(NOW, END + timedelta(days=1), END + timedelta(days=1))},
    {"provenance": provenance(source=ObservationSource.AUTHENTICATED_NOTIFICATION)},
])
def test_verified_trial_rejects_missing_or_inconsistent_evidence(changes):
    with pytest.raises(ValueError):
        observation(**changes)


@pytest.mark.parametrize("capability", [f.name for f in fields(GatewayCapabilities)])
@pytest.mark.parametrize("state", [CapabilityState.UNKNOWN, CapabilityState.UNSUPPORTED,
                                   CapabilityState.REQUIRES_APPROVAL])
def test_missing_mandatory_capability_cannot_be_presented_as_verified_trial(capability, state):
    with pytest.raises(ValueError):
        observation(capabilities=capabilities(**{capability: state}))


@pytest.mark.parametrize("state", [PaymentMethodReadiness.ATTACHED, PaymentMethodReadiness.PENDING_SETUP,
                                   PaymentMethodReadiness.REJECTED, PaymentMethodReadiness.UNKNOWN])
def test_attached_or_pending_method_is_distinct_from_reusable_authority(state):
    partial = ProviderVerificationObservation(request(), provenance(), VerificationOutcome.PENDING,
        recurring_authorization=authority(readiness=state))
    assert partial.recurring_authorization.readiness is state
    with pytest.raises(ValueError):
        observation(recurring_authorization=partial.recurring_authorization)


@pytest.mark.parametrize("state", [RecurringConsentState.UNKNOWN, RecurringConsentState.PENDING,
                                   RecurringConsentState.REJECTED])
def test_reusable_authority_does_not_imply_recorded_consent(state):
    with pytest.raises(ValueError):
        observation(recurring_authorization=authority(consent=state))


def test_payment_method_readiness_is_reused_and_checked_independently_of_consent():
    method = PaymentMethodEvidence(reference("customer-A"), reference("setup-A"), NOW,
        PaymentMethodReadiness.REUSABLE_AUTHORITY_CONFIRMED, reference("method-A"))
    assert observation(payment_method=method).payment_method == method
    with pytest.raises(ValueError):
        observation(payment_method=replace(method, readiness=PaymentMethodReadiness.PENDING_SETUP))


@pytest.mark.parametrize("changes", [
    {"consent_reference": None}, {"consent_terms_revision": None},
    {"kind": RecurringAuthorizationKind.UNKNOWN}, {"readiness": True},
    {"consent": "recorded"}, {"kind": "provider_agreement"},
])
def test_recurring_proof_rejects_untyped_or_missing_provenance(changes):
    with pytest.raises(ValueError):
        authority(**changes)


@pytest.mark.parametrize("binding", [None, replace(BINDING, provider="other"),
    replace(BINDING, environment=GatewayEnvironment.LIVE), replace(BINDING, merchant_account_id="other"),
    replace(BINDING, binding_id="other")])
@pytest.mark.parametrize("field_name", ["customer", "checkout", "subscription"])
def test_observation_rejects_unscoped_or_cross_binding_provider_objects(binding, field_name):
    ref = ProviderReference(binding.provider if binding else "stripe", "same", binding=binding)
    with pytest.raises(ValueError):
        observation(**{field_name: ref})


@pytest.mark.parametrize("changes", [
    {"provenance": provenance(replace(BINDING, merchant_account_id="other"))},
    {"terms": ObservedRecurringTerms(Money(Decimal("59"), "USD"), 1,
        price=reference("price-A", replace(BINDING, environment=GatewayEnvironment.LIVE)))},
    {"recurring_authorization": authority(replace(BINDING, binding_id="other"))},
    {"recurring_authorization": authority(customer=reference("other-customer"))},
    {"payment_method": PaymentMethodEvidence(reference("other-customer"), reference("setup-A"), NOW)},
    {"settlement": settlement(customer=reference("other-customer"))},
    {"settlement": settlement(subscription=reference("other-subscription"))},
])
def test_nested_evidence_cannot_smuggle_foreign_associations(changes):
    with pytest.raises(ValueError):
        observation(**changes)


def test_exact_request_associations_are_checked_without_fabricating_tenant_ownership():
    with pytest.raises(ValueError):
        observation(customer=reference("another-customer"))
    with pytest.raises(ValueError):
        observation(checkout=reference("another-checkout"))
    with pytest.raises(ValueError):
        observation(request=request(subscription=reference("different-subscription")))
    # Opaque provider IDs cannot prove tenant ownership; later persistence must.
    changed = request(approved_terms=replace(request().approved_terms, tenant_id="tenant-B"))
    assert changed != request()


@pytest.mark.parametrize("changes", [
    {"customer": ProviderReference("stripe", "unscoped")}, {"checkout": None},
    {"subscription": reference("subscription-A", replace(BINDING, environment=GatewayEnvironment.LIVE))},
    {"reservation_id": " "}, {"checkout_attempt_id": []}, {"customer_operation_id": ""},
    {"approved_terms": {}}, {"approved_terms_digest": "sha256:short"},
    {"approved_terms_digest": "sha256:" + "A" * 64},
])
def test_trial_request_requires_immutable_explicit_persisted_context(changes):
    with pytest.raises(ValueError):
        request(**changes)


@pytest.mark.parametrize("changes", [
    {"source": "authoritative_lookup"}, {"reference": ProviderReference("stripe", "unscoped")},
    {"observed_at": NOW.replace(tzinfo=None)}, {"adapter_version": None}, {"api_version": ""},
    {"stored_observation_id": []},
])
def test_provenance_requires_typed_origin_version_and_timezone(changes):
    with pytest.raises(ValueError):
        provenance(**changes)


def test_storing_an_observation_preserves_lookup_origin_without_fabricating_webhook_or_transition():
    stored = provenance(stored_observation_id="local-observation-A")
    assert stored.source is ObservationSource.AUTHORITATIVE_LOOKUP
    assert stored.reference == provenance().reference
    assert stored.stored_observation_id == "local-observation-A"
    notification = provenance(source=ObservationSource.AUTHENTICATED_NOTIFICATION)
    assert notification != stored
    with pytest.raises(ValueError):
        observation(provenance=notification)
    assert "confirmed_transition" not in {s.value for s in ObservationSource}


def test_existing_subscription_observation_does_not_require_or_invent_a_new_trial():
    context = SubscriptionObservationRequest("tenant-A", BINDING, reference("customer-A"), reference("subscription-A"))
    result = ProviderVerificationObservation(context, provenance(), VerificationOutcome.VERIFIED,
        capabilities(authoritative_reconciliation=CapabilityState.SUPPORTED),
        customer=context.customer, subscription=context.subscription, subscription_state=SubscriptionState.ACTIVE,
        terms=ObservedRecurringTerms(Money(Decimal("59"), "USD"), 1))
    assert result.trial is None and result.recurring_authorization is None
    assert result.settlement is None  # active state is not proof of paid coverage
    assert context.customer_operation_id is None  # unknown historical lineage stays unknown
    with pytest.raises(ValueError):
        replace(result, subscription=reference("other-subscription"))
    with pytest.raises(ValueError):
        replace(result, capabilities=GatewayCapabilities())


@pytest.mark.parametrize("changes", [
    {"tenant_id": ""}, {"binding": None}, {"customer": None}, {"subscription": None},
    {"customer_operation_id": []},
])
def test_subscription_request_rejects_missing_or_malformed_identity(changes):
    with pytest.raises(ValueError):
        replace(SubscriptionObservationRequest("tenant-A", BINDING, reference("customer-A"), reference("subscription-A")), **changes)


def test_zero_trial_invoice_is_explicit_and_cannot_replace_method_or_consent_evidence():
    initial = settlement()
    result = observation(settlement=initial)
    assert result.settlement.initial_subscription_invoice is True
    assert result.settlement.amount_paid.amount == Decimal("0")
    with pytest.raises(ValueError):
        observation(settlement=initial, recurring_authorization=None)
    post_trial_zero = replace(initial, initial_subscription_invoice=False,
        coverage=((END, END + timedelta(days=30)),))
    assert post_trial_zero != initial  # legitimate zero-value settlements are not erased
    assert observation(settlement=post_trial_zero).subscription_state is SubscriptionState.TRIALING


def test_nested_coverage_is_copied_and_entire_new_aggregate_is_hashable_and_frozen():
    coverage = [[NOW, END]]
    payment = settlement(coverage=coverage)
    result = observation(settlement=payment)
    expected_hash = hash(result)
    coverage[0][1] = END + timedelta(days=1)
    coverage.clear()
    assert result.settlement.coverage == ((NOW, END),)
    assert hash(result) == expected_hash
    nested = [result, result.request, result.request.approved_terms, result.request.binding,
        result.provenance, result.capabilities, result.terms, result.terms.amount,
        result.trial, result.recurring_authorization, result.settlement]
    for value in nested:
        for f in fields(value):
            with pytest.raises(FrozenInstanceError):
                setattr(value, f.name, "mutated")


@pytest.mark.parametrize("field_name", ["terms", "trial", "payment_method", "recurring_authorization", "settlement"])
def test_mutable_provider_dictionaries_cannot_be_embedded_in_observation(field_name):
    with pytest.raises(ValueError):
        observation(**{field_name: {"nested": ["untrusted"]}})


@pytest.mark.parametrize("changes", [
    {"outcome": True}, {"outcome": "verified"}, {"outcome": "future-provider-success"},
    {"subscription_state": "trialing"}, {"checkout_state": "complete"}, {"capabilities": {}},
])
def test_unknown_provider_values_cannot_be_treated_as_verified(changes):
    with pytest.raises(ValueError):
        observation(**changes)


@pytest.mark.parametrize("changes", [
    {"coverage": None}, {"coverage": [[NOW]]}, {"coverage": [[END, NOW]]},
    {"coverage": [[NOW.replace(tzinfo=None), END]]}, {"payment_state": "paid"},
    {"settlement_confirmed": 1}, {"initial_subscription_invoice": "false"},
    {"paid_at": None}, {"payment_state": PaymentState.UNPAID},
])
def test_settlement_rejects_mutable_malformed_or_unconfirmed_paid_claims(changes):
    with pytest.raises(ValueError):
        settlement(**changes)


@pytest.mark.parametrize("changes", [
    {"started_at": NOW.replace(tzinfo=None)}, {"ends_at": NOW}, {"cutoff": END + timedelta(seconds=1)},
])
def test_trial_window_requires_consistent_timezone_aware_boundaries(changes):
    with pytest.raises(ValueError):
        replace(ObservedTrialWindow(NOW, END, END), **changes)


@pytest.mark.parametrize("changes", [
    {"amount": {"amount": "59", "currency": "USD"}}, {"interval_months": True},
    {"interval_months": 0}, {"quantity": 0}, {"price": "provider-price"},
])
def test_observed_commercial_terms_require_precise_typed_values(changes):
    with pytest.raises(ValueError):
        replace(ObservedRecurringTerms(Money(Decimal("59"), "USD"), 1), **changes)


def test_representations_exclude_context_and_opaque_proof_identifiers():
    result = observation()
    for value in (result, result.request, result.provenance, result.recurring_authorization, settlement()):
        text = repr(value)
        for protected in ("customer-A", "subscription-A", "authorization-A", "consent-A",
                          "tenant-A", "reservation-A", "lookup-A", "invoice-A", DIGEST):
            assert protected not in text
    with pytest.raises(TypeError):
        ObservationProvenance(**dict(source=ObservationSource.AUTHORITATIVE_LOOKUP,
            reference=reference("lookup-A"), observed_at=NOW, adapter_version="v1", api_version="v1",
            raw_payload={"password": "must-not-be-stored"}))


def test_optional_protocol_preserves_existing_gateway_and_customer_signatures():
    from src.ai.billing.stripe_gateway import StripeGateway
    for name in ("observe_trial_checkout", "observe_subscription"):
        assert name in ProviderVerificationGateway.__dict__
        assert name not in SubscriptionPaymentGateway.__dict__
        assert not hasattr(StripeGateway, name)
    assert "decode" not in ProviderVerificationGateway.__dict__
    assert list(inspect.signature(StripeGateway.create_customer).parameters) == [
        "self", "email", "company_name", "tenant_reference", "idempotency_key"]


def test_optional_protocol_allows_provider_neutral_doubles_without_a_second_runtime_adapter():
    class ObservationDouble:
        binding = replace(BINDING, provider="hypothetical-mor", binding_id="mor-binding")

        def observe_trial_checkout(self, context):
            return ProviderVerificationObservation(context, provenance(self.binding), VerificationOutcome.UNSUPPORTED)

        def observe_subscription(self, context):
            return ProviderVerificationObservation(context, provenance(self.binding), VerificationOutcome.UNAVAILABLE)

    def observe(gateway: ProviderVerificationGateway):
        return gateway.observe_trial_checkout(request(gateway.binding))

    assert observe(ObservationDouble()).outcome is VerificationOutcome.UNSUPPORTED


def test_new_verification_contracts_remain_unused_by_active_or_dormant_runtime_modules():
    src = Path(__file__).resolve().parents[2] / "src"
    names = {"ProviderVerificationGateway", "ProviderVerificationObservation", "TrialObservationRequest",
             "SubscriptionObservationRequest", "ObservationProvenance", "RecurringAuthorizationEvidence",
             "ObservedSettlement", "ObservedRecurringTerms", "ObservedTrialWindow"}
    for path in (src / "ai").rglob("*.py"):
        if "tests" in path.parts or path.name in {"payment_contracts.py", "stripe_verification.py", "verification_observations.py"}:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                assert node.id not in names, str(path)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                assert not {a.name for a in node.names} & names, str(path)
            elif isinstance(node, ast.Attribute):
                assert node.attr not in names, str(path)


class SwitchableBinding(GatewayBinding):
    """Reproduce the review: ordinary extension assignment changes a property."""
    def __getattribute__(self, name):
        if name == "merchant_account_id":
            try:
                return object.__getattribute__(self, "account_override")
            except AttributeError:
                pass
        return super().__getattribute__(name)


class SwitchableReference(ProviderReference):
    def __getattribute__(self, name):
        if name == "opaque_id":
            try:
                return object.__getattribute__(self, "object_override")
            except AttributeError:
                pass
        return super().__getattribute__(name)


def subscription_request(binding=BINDING):
    return SubscriptionObservationRequest("tenant-A", binding, reference("customer-A", binding),
                                          reference("subscription-A", binding))


@pytest.mark.parametrize("build", [
    lambda b: request(b), lambda b: subscription_request(b), lambda b: provenance(b),
    lambda b: ObservedRecurringTerms(Money(Decimal("59"), "USD"), 1, price=reference("price-A", b)),
    lambda b: authority(b), lambda b: observation(customer=reference("customer-A", b)),
    lambda b: settlement(invoice=reference("invoice-A", b)),
    lambda b: observation(payment_method=PaymentMethodEvidence(reference("customer-A", b),
        reference("setup-A", b), NOW)),
])
def test_mutation_regression_binding_subclass_cannot_enter_verification_graph(build):
    binding = SwitchableBinding("stripe", GatewayEnvironment.TEST, "merchant-A", "binding-A")
    customer = reference("customer-A", binding)
    assert customer.binding.merchant_account_id == "merchant-A"
    # Assert the intended exact-type rejection, not an unrelated identity error.
    with pytest.raises(ValueError, match="^Unsupported verification value type$"):
        build(binding)
    binding.account_override = "merchant-B"
    assert customer.binding.merchant_account_id == "merchant-B"
    # Legacy objects still permit this subclass; none entered the new boundary.


@pytest.mark.parametrize("build", [
    lambda r: request(customer=r), lambda r: request(checkout=r), lambda r: request(subscription=r),
    lambda r: replace(subscription_request(), customer=r), lambda r: provenance(reference=r),
    lambda r: ObservedRecurringTerms(Money(Decimal("59"), "USD"), 1, price=r),
    lambda r: authority(customer=r), lambda r: authority(source=r), lambda r: authority(consent_reference=r),
    lambda r: settlement(invoice=r), lambda r: settlement(customer=r), lambda r: settlement(subscription=r),
    lambda r: observation(customer=r),
    lambda r: observation(payment_method=PaymentMethodEvidence(r, reference("setup-A"), NOW)),
])
def test_mutation_regression_provider_reference_subclass_is_rejected_everywhere(build):
    ref = SwitchableReference("stripe", "customer-A", binding=BINDING)
    assert ref.opaque_id == "customer-A"
    with pytest.raises(ValueError, match="^Unsupported verification value type$"):
        build(ref)
    ref.object_override = "customer-B"
    assert ref.opaque_id == "customer-B"


@pytest.mark.parametrize("field_name, base, build", [
    ("approved_terms", request().approved_terms, lambda v: request(approved_terms=v)),
    ("capabilities", capabilities(), lambda v: observation(capabilities=v)),
    ("amount", Money(Decimal("59"), "USD"), lambda v: ObservedRecurringTerms(v, 1)),
    ("amount_paid", Money(Decimal("0"), "USD"), lambda v: settlement(amount_paid=v)),
    ("payment_method", PaymentMethodEvidence(reference("customer-A"), reference("setup-A"), NOW),
        lambda v: observation(payment_method=v)),
])
def test_reused_legacy_evidence_subclasses_cannot_retain_extension_aliases(field_name, base, build):
    subclass = type("MutableLegacyEvidence", (type(base),), {})
    value = subclass(**{f.name: getattr(base, f.name) for f in fields(base)})
    value.extension = ["original"]
    expected = ("Typed observation context and outcome required" if field_name == "capabilities"
                else "Unsupported verification value type")
    with pytest.raises(ValueError, match="^" + expected + "$"):
        build(value)
    value.extension.append("changed")
    assert value.extension == ["original", "changed"]


@pytest.mark.parametrize("base", [provenance(), request(), subscription_request(),
    observation().terms, observation().trial, authority(), settlement(), observation()])
def test_new_verification_dataclasses_reject_unsupported_subclass_construction(base):
    subclass = type("MutableVerificationEvidence", (type(base),), {})
    with pytest.raises(ValueError, match="^Unsupported verification value type$"):
        subclass(**{f.name: getattr(base, f.name) for f in fields(base)})


def test_decimal_and_identifier_subclasses_are_not_hidden_mutable_leaves():
    class MutableDecimal(Decimal):
        pass

    class MutableString(str):
        pass

    with pytest.raises(ValueError, match="^Unsupported verification value type$"):
        ObservedRecurringTerms(Money(MutableDecimal("59"), "USD"), 1)
    for name in ("provider", "merchant_account_id", "binding_id"):
        binding = replace(BINDING, **{name: MutableString(getattr(BINDING, name))})
        with pytest.raises(ValueError, match="^Explicit non-secret observation identifiers required$"):
            subscription_request(binding)
    with pytest.raises(ValueError, match="^Explicit non-secret observation identifiers required$"):
        request(customer=ProviderReference("stripe", MutableString("customer-A"), binding=BINDING))


class MutableZone(tzinfo):
    def __init__(self, offset=timedelta(0)):
        self.offset = offset

    def utcoffset(self, dt):
        return self.offset

    def dst(self, dt):
        return timedelta(0)


class DecoderSequence:
    def __init__(self, values):
        self.values = values

    def __iter__(self):
        return iter(self.values)


def test_mutation_regression_verified_graph_keeps_every_instant_after_timezone_and_sequence_changes():
    zone = MutableZone()
    local_start, local_end = NOW.replace(tzinfo=zone), END.replace(tzinfo=zone)
    # Match the rejected sequence: UTC start, caller-mutable end/cutoff zone.
    window = ObservedTrialWindow(NOW, local_end, local_end)
    proof = provenance(observed_at=local_start)
    method = PaymentMethodEvidence(reference("customer-A"), reference("setup-A"), local_start,
        PaymentMethodReadiness.REUSABLE_AUTHORITY_CONFIRMED, reference("method-A"))
    inner = DecoderSequence([local_start, local_end])
    outer = DecoderSequence([inner])
    payment = settlement(paid_at=local_start, coverage=outer)
    result = observation(provenance=proof, trial=window, payment_method=method, settlement=payment)
    replay = replace(result, request=replace(result.request))

    def instants(value):
        return (value.provenance.observed_at, value.trial.started_at, value.trial.ends_at,
                value.trial.cutoff, value.payment_method.observed_at, value.settlement.paid_at,
                *value.settlement.coverage[0])

    original, original_hash = instants(result), hash(result)
    assert original == (NOW, NOW, END, END, NOW, NOW, NOW, END)
    assert all(type(v) is datetime and v.tzinfo is timezone.utc for v in original)
    assert result.payment_method is not method
    assert method.observed_at is local_start  # Legacy constructor behavior unchanged.
    zone.offset = timedelta(hours=2)
    inner.values.clear()
    outer.values.clear()
    assert instants(result) == original == instants(replay)
    assert result.trial.ends_at - result.trial.started_at == timedelta(days=14)
    assert result.trial.started_at < result.trial.ends_at == result.trial.cutoff
    assert result.outcome is VerificationOutcome.VERIFIED
    assert hash(result) == original_hash
    assert method.observed_at.astimezone(timezone.utc) == NOW - timedelta(hours=2)
    zone.offset = None
    assert instants(result) == original  # Even later-invalid caller zones are detached.


@pytest.mark.parametrize("offset", [timedelta(hours=14), timedelta(hours=-12),
    timedelta(hours=5, minutes=30), -timedelta(hours=3, minutes=30)])
def test_non_utc_instants_cross_day_boundaries_without_losing_microseconds(offset):
    local = datetime(2026, 11, 7, 0, 10, 20, 123456, tzinfo=MutableZone(offset))
    expected = datetime(2026, 11, 7, 0, 10, 20, 123456, tzinfo=timezone.utc) - offset
    proof = provenance(observed_at=local)
    assert proof.observed_at == expected
    assert type(proof.observed_at) is datetime and proof.observed_at.tzinfo is timezone.utc
    assert proof.observed_at.microsecond == 123456
    assert proof.observed_at is not local
    rebuilt = replace(proof)
    local.tzinfo.offset = timedelta(0)
    assert rebuilt.observed_at == proof.observed_at == expected


def test_datetime_subclass_overrides_and_extension_state_do_not_survive_normalization():
    class MutableDateTime(datetime):
        @property
        def year(self):
            return self.year_override

        def utcoffset(self):
            raise AssertionError("Subclass method must not be used")

        def astimezone(self, *args, **kwargs):
            raise AssertionError("Subclass method must not be used")

    zone = MutableZone(timedelta(hours=3))
    value = MutableDateTime(2026, 11, 7, 3, 0, 0, 654321, tzinfo=zone)
    value.year_override = 2040
    result = provenance(observed_at=value)
    expected = datetime(2026, 11, 7, 0, 0, 0, 654321, tzinfo=timezone.utc)
    assert result.observed_at == expected
    assert type(result.observed_at) is datetime and result.observed_at.tzinfo is timezone.utc
    value.year_override = 2050
    zone.offset = timedelta(hours=-5)
    assert result.observed_at == expected


@pytest.mark.parametrize("invalid", [None, "not-an-offset", timedelta(hours=24)])
@pytest.mark.parametrize("build", [
    lambda t: provenance(observed_at=t), lambda t: ObservedTrialWindow(t, END, END),
    lambda t: settlement(paid_at=t), lambda t: settlement(coverage=((t, END),)),
])
def test_invalid_timezone_behavior_fails_closed_in_each_timestamp_path(invalid, build):
    value = NOW.replace(tzinfo=MutableZone(invalid))
    with pytest.raises(ValueError, match="^Valid timezone-aware verification timestamp required$"):
        build(value)


def test_timezone_errors_are_sanitized_and_unrepresentable_utc_instants_are_rejected():
    class BrokenZone(tzinfo):
        def utcoffset(self, dt):
            raise RuntimeError("private-zone-error-must-not-leak")

    for value in (NOW.replace(tzinfo=BrokenZone()),
                  datetime(1, 1, 1, tzinfo=timezone(timedelta(hours=14))),
                  NOW.replace(tzinfo=None)):
        with pytest.raises(ValueError, match="^Valid timezone-aware verification timestamp required$") as exc:
            provenance(observed_at=value)
        assert "private-zone-error" not in str(exc.value)


def test_nested_legacy_method_with_later_invalid_timezone_is_rejected_on_admission():
    zone = MutableZone()
    method = PaymentMethodEvidence(reference("customer-A"), reference("setup-A"), NOW.replace(tzinfo=zone))
    zone.offset = None
    with pytest.raises(ValueError, match="^Valid timezone-aware verification timestamp required$"):
        observation(outcome=VerificationOutcome.PENDING, payment_method=method)


def test_trial_order_and_cutoff_are_checked_using_normalized_utc_instants():
    start = datetime(2026, 11, 7, 10, tzinfo=timezone(timedelta(hours=2)))
    # Earlier wall-clock hour, later UTC instant: this is a valid positive window.
    end = datetime(2026, 11, 7, 9, tzinfo=timezone.utc)
    cutoff = datetime(2026, 11, 7, 12, tzinfo=timezone(timedelta(hours=3)))
    window = ObservedTrialWindow(start, end, cutoff)
    assert window.ends_at - window.started_at == timedelta(hours=1)
    with pytest.raises(ValueError, match="^Consistent observed trial boundaries required$"):
        ObservedTrialWindow(end, start, start)
