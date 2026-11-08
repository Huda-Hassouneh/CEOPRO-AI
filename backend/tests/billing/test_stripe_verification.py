"""Offline authoritative-read doubles; no provider acceptance or activation claims."""
import ast
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone, tzinfo
from decimal import Decimal
import json
import logging
import ssl
import traceback
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

import pytest
import stripe

from src.ai.billing import payment_contracts as C
from src.ai.billing.stripe_verification import BoundStripeReadTransport, StripeVerificationGateway
from src.ai.billing import stripe_verification as V


NOW = datetime(2026, 11, 7, tzinfo=timezone.utc)
END = NOW + timedelta(days=14)
START, STOP = int(NOW.timestamp()), int(END.timestamp())
BINDING = C.GatewayBinding("stripe", C.GatewayEnvironment.TEST, "acct_A", "binding_A")
VERSION = "2026-08-26.dahlia"


def ref(identifier, binding=BINDING):
    return C.ProviderReference("stripe", identifier, binding=binding)


def trial_request(binding=BINDING):
    return C.TrialObservationRequest(
        C.ApprovedTrialTerms("tenant_A", "growth", "catalog_A", 1, "USD", 14, binding),
        "sha256:" + "a" * 64, "reservation_A", "attempt_A", ref("cs_A", binding),
        ref("cus_A", binding), "operation_A", ref("sub_A", binding),
        expected_terms=C.ObservedRecurringTerms(C.Money(Decimal("59"), "USD"), 1, 1, ref("price_A", binding)),
    )


def subscription_request(binding=BINDING):
    return C.SubscriptionObservationRequest("tenant_A", binding, ref("cus_A", binding), ref("sub_A", binding))


def listing(*items):
    return {"object": "list", "has_more": False, "data": list(items)}


def data():
    return {
        ("account", None): {"object": "account", "id": "acct_A"},
        ("balance", None): {"object": "balance", "livemode": False},
        ("customer", "cus_A"): {"object": "customer", "id": "cus_A", "livemode": False,
            "email": "private-synthetic@example.test", "metadata": {"tenant_id": "tenant_A", "keel_customer_operation_id": "operation_A"}},
        ("checkout", "cs_A"): {"object": "checkout.session", "id": "cs_A", "livemode": False,
            "mode": "subscription", "status": "complete", "customer": "cus_A", "subscription": "sub_A",
            "currency": "usd", "setup_intent": None, "total_details": {"amount_discount": 0}},
        ("checkout_lines", "cs_A"): listing({"price": "price_A", "quantity": 1, "currency": "usd"}),
        ("subscription", "sub_A"): {"object": "subscription", "id": "sub_A", "livemode": False,
            "customer": "cus_A", "status": "trialing", "currency": "usd", "cancel_at_period_end": False,
            "canceled_at": None, "trial_start": START, "trial_end": STOP,
            "items": listing({"subscription": "sub_A", "price": "price_A", "quantity": 1,
                "current_period_start": START, "current_period_end": STOP}),
            "default_payment_method": "pm_A", "pending_setup_intent": "seti_A", "latest_invoice": "in_A"},
        ("price", "price_A"): {"object": "price", "id": "price_A", "livemode": False, "currency": "usd",
            "unit_amount": 5900, "unit_amount_decimal": "5900", "type": "recurring", "billing_scheme": "per_unit",
            "recurring": {"interval": "month", "interval_count": 1, "usage_type": "licensed"}},
        ("payment_method", "pm_A"): {"object": "payment_method", "id": "pm_A", "livemode": False,
            "customer": "cus_A", "type": "card", "card": {"last4": "4242"}},
        ("setup_intent", "seti_A"): {"object": "setup_intent", "id": "seti_A", "livemode": False,
            "customer": "cus_A", "status": "succeeded", "usage": "off_session", "payment_method": "pm_A",
            "client_secret": "synthetic-secret-never-project"},
        ("invoice", "in_A"): {"object": "invoice", "id": "in_A", "livemode": False, "customer": "cus_A",
            "currency": "usd", "status": "paid", "amount_paid": 0, "amount_remaining": 0,
            "billing_reason": "subscription_create", "parent": {"subscription_details": {"subscription": "sub_A"}},
            "status_transitions": {"paid_at": START}},
        ("invoice_lines", "in_A"): listing({"object": "line_item", "id": "il_A", "invoice": "in_A",
            "currency": "usd", "livemode": False, "quantity": 1, "amount": 0, "subtotal": 0,
            "parent": {"subscription_item_details": {"subscription": "sub_A", "proration": False}},
            "pricing": {"price_details": {"price": "price_A"}}, "period": {"start": START, "end": STOP}}),
    }


class Reader:
    def __init__(self, binding=BINDING):
        self.binding, self.api_version = binding, VERSION
        self.data, self.calls, self.error = data(), [], None
        self.data["account", None]["id"] = binding.merchant_account_id

    def get(self, kind, identifier=None):
        self.calls.append((kind, identifier))
        if self.error is not None:
            raise self.error
        return self.data[kind, identifier]


def observe(reader, *, trial=True, request=None, clock=lambda: NOW):
    gateway = StripeVerificationGateway(reader.binding if reader else BINDING, reader, clock)
    if trial:
        return gateway.observe_trial_checkout(request or trial_request(gateway.binding))
    return gateway.observe_subscription(request or subscription_request(gateway.binding))


def test_exact_trial_correlations_and_reusable_setup_still_lack_trusted_consent():
    reader = Reader()
    result = observe(reader)
    assert result.outcome is C.VerificationOutcome.PENDING
    assert result.customer == ref("cus_A") and result.subscription == ref("sub_A")
    assert result.checkout == ref("cs_A") and result.checkout_state is C.CheckoutState.COMPLETE
    assert result.terms == trial_request().expected_terms
    assert result.trial == C.ObservedTrialWindow(NOW, END, END)
    assert (result.period_start, result.period_end, result.cancel_at_period_end) == (NOW, END, False)
    assert result.payment_method.readiness is C.PaymentMethodReadiness.REUSABLE_AUTHORITY_CONFIRMED
    assert result.recurring_authorization.consent is C.RecurringConsentState.UNKNOWN
    assert result.recurring_authorization.consent_reference is None
    assert result.recurring_authorization.consent_terms_revision is None
    assert result.provenance.source is C.ObservationSource.AUTHORITATIVE_LOOKUP
    assert result.provenance.api_version == VERSION and result.provenance.observed_at == NOW
    assert reader.calls[:2] == [("account", None), ("balance", None)]
    assert ("setup_intent", "seti_A") in reader.calls
    assert not result.capabilities.supports_card_backed_trial()


@pytest.mark.parametrize("key,field,value", [
    (("checkout", "cs_A"), "customer", "cus_other"),
    (("subscription", "sub_A"), "customer", "cus_other"),
    (("setup_intent", "seti_A"), "customer", "cus_other"),
    (("payment_method", "pm_A"), "customer", "cus_other"),
    (("setup_intent", "seti_A"), "payment_method", "pm_other"),
    (("customer", "cus_A"), "id", "cus_other"),
    (("customer", "cus_A"), "object", "price"),
    (("customer", "cus_A"), "deleted", True),
])
def test_wrong_object_relationships_are_conflicts(key, field, value):
    reader = Reader()
    reader.data[key][field] = value
    assert observe(reader).outcome is C.VerificationOutcome.CONFLICT


def test_different_subscription_under_same_customer_cannot_replace_expected_subscription():
    reader = Reader()
    reader.data["checkout", "cs_A"]["subscription"] = "sub_other"
    other = deepcopy(reader.data["subscription", "sub_A"])
    other["id"] = "sub_other"
    reader.data["subscription", "sub_other"] = other
    assert observe(reader).outcome is C.VerificationOutcome.CONFLICT


@pytest.mark.parametrize("kind,identifier", [
    ("customer", "cus_A"), ("checkout", "cs_A"), ("subscription", "sub_A"),
    ("price", "price_A"), ("setup_intent", "seti_A"), ("payment_method", "pm_A"),
])
def test_test_live_object_mixing_is_denied(kind, identifier):
    reader = Reader()
    reader.data[kind, identifier]["livemode"] = True
    assert observe(reader).outcome is C.VerificationOutcome.CONFLICT


@pytest.mark.parametrize("mismatch", ["account", "balance", "reader_binding", "request_binding"])
def test_original_account_binding_and_environment_are_required(mismatch):
    reader = Reader()
    gateway = StripeVerificationGateway(BINDING, reader, lambda: NOW)
    request = trial_request()
    if mismatch == "account":
        reader.data["account", None]["id"] = "acct_other"
    elif mismatch == "balance":
        reader.data["balance", None]["livemode"] = True
    elif mismatch == "reader_binding":
        reader.binding = replace(BINDING, merchant_account_id="acct_other", binding_id="other")
    else:
        request = trial_request(replace(BINDING, merchant_account_id="acct_other", binding_id="other"))
    assert gateway.observe_trial_checkout(request).outcome is C.VerificationOutcome.CONFLICT


def test_identical_opaque_ids_in_distinct_accounts_remain_distinct():
    other = replace(BINDING, merchant_account_id="acct_other", binding_id="other")
    first, second = observe(Reader()), observe(Reader(other))
    assert first.customer.opaque_id == second.customer.opaque_id
    assert first.customer != second.customer
    assert second.request.binding == other and second.outcome is C.VerificationOutcome.PENDING


@pytest.mark.parametrize("change", ["amount", "quantity", "price", "currency", "interval", "count"])
def test_frozen_commercial_mismatches_fail_closed(change):
    reader = Reader()
    price = reader.data["price", "price_A"]
    if change == "amount":
        price.update(unit_amount=6000, unit_amount_decimal="6000")
    elif change == "quantity":
        reader.data["subscription", "sub_A"]["items"]["data"][0]["quantity"] = 2
    elif change == "price":
        reader.data["subscription", "sub_A"]["items"]["data"][0]["price"] = "price_other"
        reader.data["price", "price_other"] = dict(price, id="price_other")
    elif change == "currency":
        price["currency"] = "eur"
        reader.data["subscription", "sub_A"]["currency"] = "eur"
    elif change == "interval":
        price["recurring"]["interval"] = "year"
    else:
        price["recurring"]["interval_count"] = 2
    assert observe(reader).outcome is C.VerificationOutcome.CONFLICT


@pytest.mark.parametrize("change", ["discount", "tax", "tiered", "metered", "multiple", "pagination"])
def test_unrepresented_adjustments_and_incomplete_lists_are_unsupported(change):
    reader = Reader()
    sub = reader.data["subscription", "sub_A"]
    price = reader.data["price", "price_A"]
    if change == "discount":
        sub["discounts"] = ["di_synthetic"]
    elif change == "tax":
        sub["automatic_tax"] = {"enabled": True}
    elif change == "tiered":
        price["billing_scheme"] = "tiered"
    elif change == "metered":
        price["recurring"]["usage_type"] = "metered"
    elif change == "multiple":
        sub["items"]["data"].append(deepcopy(sub["items"]["data"][0]))
    else:
        sub["items"]["has_more"] = True
    assert observe(reader).outcome is C.VerificationOutcome.UNSUPPORTED


@pytest.mark.parametrize("value,outcome", [(STOP + 1, C.VerificationOutcome.CONFLICT),
    (START - 1, C.VerificationOutcome.UNAVAILABLE), (None, C.VerificationOutcome.UNAVAILABLE),
    (True, C.VerificationOutcome.UNAVAILABLE)])
def test_trial_boundaries_are_exact_and_not_fabricated(value, outcome):
    reader = Reader()
    reader.data["subscription", "sub_A"]["trial_end"] = value
    assert observe(reader).outcome is outcome


@pytest.mark.parametrize("status", ["requires_action", "requires_confirmation", "processing", "requires_payment_method"])
def test_pending_setup_remains_pending(status):
    reader = Reader()
    reader.data["setup_intent", "seti_A"]["status"] = status
    result = observe(reader)
    assert result.outcome is C.VerificationOutcome.PENDING
    assert result.payment_method.readiness is C.PaymentMethodReadiness.PENDING_SETUP


@pytest.mark.parametrize("change", ["null_setup", "on_session", "no_method", "metadata_consent"])
def test_attached_method_unrelated_setup_and_metadata_do_not_manufacture_consent(change):
    reader = Reader()
    sub = reader.data["subscription", "sub_A"]
    if change == "null_setup":
        sub["pending_setup_intent"] = None
        sub["metadata"] = {"setup_intent": "seti_A"}
    elif change == "on_session":
        reader.data["setup_intent", "seti_A"]["usage"] = "on_session"
    elif change == "no_method":
        sub["default_payment_method"] = None
    else:
        reader.data["checkout", "cs_A"].update(consent={"terms_of_service": "accepted"},
            metadata={"recurring_consent": "true", "agreement_version": "v1"})
    result = observe(reader)
    assert result.outcome is C.VerificationOutcome.PENDING
    assert result.recurring_authorization.consent is C.RecurringConsentState.UNKNOWN
    if change == "null_setup":
        assert result.payment_method.readiness is C.PaymentMethodReadiness.ATTACHED
        assert ("setup_intent", "seti_A") not in reader.calls
    elif change in ("on_session", "no_method"):
        assert result.payment_method.readiness is C.PaymentMethodReadiness.UNKNOWN


def test_missing_expected_terms_or_customer_lineage_cannot_verify_trial():
    assert observe(Reader(), request=replace(trial_request(), expected_terms=None)).outcome is C.VerificationOutcome.UNAVAILABLE
    reader = Reader()
    reader.data["customer", "cus_A"]["metadata"].pop("keel_customer_operation_id")
    assert observe(reader).outcome is C.VerificationOutcome.UNAVAILABLE


@pytest.mark.parametrize("field,value", [("price", "price_other"), ("quantity", 2), ("currency", "eur")])
def test_checkout_line_must_match_authoritative_subscription(field, value):
    reader = Reader()
    reader.data["checkout_lines", "cs_A"]["data"][0][field] = value
    assert observe(reader).outcome is C.VerificationOutcome.CONFLICT


@pytest.mark.parametrize("status,outcome", [("open", C.VerificationOutcome.PENDING),
    ("expired", C.VerificationOutcome.CONFLICT), ("future", C.VerificationOutcome.UNSUPPORTED)])
def test_checkout_not_complete_never_verifies_or_fetches_a_replacement_subscription(status, outcome):
    reader = Reader()
    reader.data["checkout", "cs_A"]["status"] = status
    assert observe(reader).outcome is outcome
    assert not any(kind == "subscription" for kind, _ in reader.calls)


@pytest.mark.parametrize("change", ["customer_tenant", "subscription_tenant", "customer_operation"])
def test_negative_metadata_mismatch_is_rejected_but_never_used_as_positive_authority(change):
    reader = Reader()
    if change == "customer_tenant":
        reader.data["customer", "cus_A"]["metadata"]["tenant_id"] = "tenant_other"
    elif change == "subscription_tenant":
        reader.data["subscription", "sub_A"]["metadata"] = {"tenant_id": "tenant_other"}
    else:
        reader.data["customer", "cus_A"]["metadata"]["keel_customer_operation_id"] = "operation_other"
    assert observe(reader).outcome is C.VerificationOutcome.CONFLICT


@pytest.mark.parametrize("change,outcome", [("setup_cancelled", C.VerificationOutcome.CONFLICT),
    ("setup_unknown", C.VerificationOutcome.UNSUPPORTED), ("non_card", C.VerificationOutcome.UNSUPPORTED),
    ("missing_trial", C.VerificationOutcome.UNAVAILABLE), ("malformed", C.VerificationOutcome.UNAVAILABLE)])
def test_incomplete_or_rejected_authority_cannot_verify_trial(change, outcome):
    reader = Reader()
    if change == "setup_cancelled":
        reader.data["setup_intent", "seti_A"]["status"] = "canceled"
    elif change == "setup_unknown":
        reader.data["setup_intent", "seti_A"]["status"] = "future_state"
    elif change == "non_card":
        reader.data["payment_method", "pm_A"]["type"] = "future_method"
    elif change == "missing_trial":
        reader.data["subscription", "sub_A"].update(trial_start=None, trial_end=None)
    else:
        reader.data["setup_intent", "seti_A"] = []
    assert observe(reader).outcome is outcome


@pytest.mark.parametrize("state,normalized", [
    ("trialing", C.SubscriptionState.TRIALING), ("active", C.SubscriptionState.ACTIVE),
    ("canceled", C.SubscriptionState.CANCELLED), ("incomplete_expired", C.SubscriptionState.EXPIRED),
    ("past_due", C.SubscriptionState.PAST_DUE), ("unpaid", C.SubscriptionState.PAYMENT_FAILED),
    ("paused", C.SubscriptionState.PAUSED), ("incomplete", C.SubscriptionState.PENDING),
])
def test_existing_subscription_lifecycle_is_observation_not_access(state, normalized):
    reader = Reader()
    reader.data["subscription", "sub_A"]["status"] = state
    result = observe(reader, trial=False)
    assert result.outcome is C.VerificationOutcome.VERIFIED
    assert result.subscription_state is normalized
    assert result.settlement.purpose is C.SettlementPurpose.INITIAL_SUBSCRIPTION
    assert result.settlement.initial_subscription_invoice is True
    assert result.settlement.amount_paid.amount == 0
    assert not hasattr(result, "activate")


@pytest.mark.parametrize("amount", [0, 5900])
def test_renewal_settlement_keeps_purpose_coverage_and_zero_value_explicit(amount):
    reader = Reader()
    reader.data["invoice", "in_A"].update(billing_reason="subscription_cycle", amount_paid=amount)
    result = observe(reader, trial=False)
    assert result.outcome is C.VerificationOutcome.VERIFIED
    assert result.settlement.purpose is C.SettlementPurpose.RENEWAL
    assert result.settlement.initial_subscription_invoice is False
    assert result.settlement.settlement_confirmed is True
    assert result.settlement.amount_paid.amount == Decimal(amount) / 100
    assert result.settlement.coverage == ((NOW, END),)
    assert result.subscription_state is C.SubscriptionState.TRIALING


def test_cancelled_subscription_lifecycle_is_not_replaced_with_an_active_subscription():
    reader = Reader()
    reader.data["subscription", "sub_A"].update(status="canceled", cancel_at_period_end=True, canceled_at=START)
    result = observe(reader, trial=False)
    assert result.outcome is C.VerificationOutcome.VERIFIED
    assert result.subscription_state is C.SubscriptionState.CANCELLED
    assert result.cancelled_at == NOW and result.cancel_at_period_end is True
    assert [call for call in reader.calls if call[0] == "subscription"] == [("subscription", "sub_A")]


@pytest.mark.parametrize("mismatch", ["customer", "subscription", "line_subscription", "line_price", "invoice_mode", "line_mode"])
def test_settlement_cannot_cross_customer_subscription_price_or_mode(mismatch):
    reader = Reader()
    invoice = reader.data["invoice", "in_A"]
    line = reader.data["invoice_lines", "in_A"]["data"][0]
    if mismatch == "customer":
        invoice["customer"] = "cus_other"
    elif mismatch == "subscription":
        invoice["parent"]["subscription_details"]["subscription"] = "sub_other"
    elif mismatch == "line_subscription":
        line["parent"]["subscription_item_details"]["subscription"] = "sub_other"
    elif mismatch == "line_price":
        line["pricing"]["price_details"]["price"] = "price_other"
    elif mismatch == "invoice_mode":
        invoice["livemode"] = True
    else:
        line["livemode"] = True
    assert observe(reader, trial=False).outcome is C.VerificationOutcome.CONFLICT


@pytest.mark.parametrize("status", ["open", "draft", "void", "uncollectible"])
def test_unsettled_invoice_does_not_establish_paid_coverage(status):
    reader = Reader()
    reader.data["invoice", "in_A"]["status"] = status
    result = observe(reader, trial=False)
    assert result.outcome is C.VerificationOutcome.VERIFIED
    assert result.settlement.payment_state is C.PaymentState.UNPAID
    assert result.settlement.settlement_confirmed is False and result.settlement.paid_at is None


@pytest.mark.parametrize("change", ["pagination", "proration", "manual", "out_of_band", "unknown_state"])
def test_unsupported_settlement_never_becomes_positive_coverage(change):
    reader = Reader()
    invoice = reader.data["invoice", "in_A"]
    if change == "pagination":
        reader.data["invoice_lines", "in_A"]["has_more"] = True
    elif change == "proration":
        reader.data["invoice_lines", "in_A"]["data"][0]["parent"]["subscription_item_details"]["proration"] = True
    elif change == "manual":
        invoice["billing_reason"] = "manual"
    elif change == "out_of_band":
        invoice["paid_out_of_band"] = True
    else:
        reader.data["subscription", "sub_A"]["status"] = "future_state"
    assert observe(reader, trial=False).outcome is C.VerificationOutcome.UNSUPPORTED


@pytest.mark.parametrize("error", [TimeoutError("private-error"), ValueError("private-error"),
    stripe.AuthenticationError("private-error"), stripe.InvalidRequestError("private-error", "id", http_status=404)])
def test_provider_failures_are_sanitized_unavailable_without_retry_or_noncreation_claim(error):
    reader = Reader()
    reader.error = error
    result = observe(reader)
    assert result.outcome is C.VerificationOutcome.UNAVAILABLE
    assert reader.calls == [("account", None)]
    assert "private-error" not in repr(result) and result.customer is None


def test_unresolved_or_unsupported_provider_access_fails_closed():
    assert observe(None).outcome is C.VerificationOutcome.UNAVAILABLE
    reader = Reader()
    reader.error = NotImplementedError()
    assert observe(reader).outcome is C.VerificationOutcome.UNSUPPORTED
    reader = Reader()
    reader.api_version = "unverified-version"
    assert observe(reader).outcome is C.VerificationOutcome.UNSUPPORTED and reader.calls == []


def test_reader_scope_cannot_change_mid_observation():
    reader = Reader()
    original = reader.get
    def changed(kind, identifier=None):
        response = original(kind, identifier)
        reader.api_version = "2026-01-28.clover"
        return response
    reader.get = changed
    result = observe(reader)
    assert result.outcome is C.VerificationOutcome.CONFLICT
    assert result.provenance.api_version == VERSION and reader.calls == [("account", None)]


def test_response_aliases_and_mutable_timezone_cannot_change_observations():
    class MutableZone(tzinfo):
        offset = timedelta(hours=2)
        def utcoffset(self, dt):
            return self.offset
        def dst(self, dt):
            return timedelta(0)
    zone = MutableZone()
    clock = datetime(2026, 11, 7, 2, 0, 0, 123456, tzinfo=zone)
    reader = Reader()
    result = observe(reader, trial=False, clock=lambda: clock)
    before = (result, hash(result), result.provenance.observed_at, result.settlement.coverage)
    reader.data["subscription", "sub_A"]["items"]["data"].clear()
    reader.data["invoice_lines", "in_A"]["data"][0]["period"]["end"] = START
    zone.offset = timedelta(hours=-8)
    assert (result, hash(result), result.provenance.observed_at, result.settlement.coverage) == before
    assert result.provenance.observed_at == NOW.replace(microsecond=123456)
    assert result.provenance.observed_at.tzinfo is timezone.utc
    assert "private-synthetic" not in repr(result) and "synthetic-secret" not in repr(result)
    with pytest.raises(FrozenInstanceError):
        result.period_end = NOW


def test_optional_contract_extensions_preserve_defaults_and_validate_lifecycle():
    request = trial_request()
    assert replace(request, expected_terms=None).expected_terms is None
    base = observe(Reader(), trial=False)
    assert replace(base, period_start=None, period_end=None, cancel_at_period_end=None, cancelled_at=None).period_start is None
    with pytest.raises(ValueError, match="Both observed"):
        replace(base, period_start=None)
    with pytest.raises(ValueError, match="Positive observed"):
        replace(base, period_end=NOW)
    with pytest.raises(ValueError, match="Explicit cancellation"):
        replace(base, cancel_at_period_end=1)
    with pytest.raises(ValueError):
        replace(base, period_start=NOW.replace(tzinfo=None))
    with pytest.raises(ValueError, match="purpose"):
        replace(base.settlement, purpose=C.SettlementPurpose.RENEWAL)
    with pytest.raises(ValueError, match="summary"):
        replace(request, expected_terms=replace(request.expected_terms, interval_months=12))


class InterceptHTTPS:
    """Real transport call boundary, with HTTP bytes supplied without sockets."""
    def __init__(self, monkeypatch, *, reader=None, body=None, status=200, error=None):
        self.reader, self.body, self.status, self.error = reader or Reader(), body, status, error
        self.calls, self.connections, self.reads = [], [], []
        self.paths = {
            "/v1/account": ("account", None), "/v1/balance": ("balance", None),
            "/v1/customers/cus_A": ("customer", "cus_A"), "/v1/checkout/sessions/cs_A": ("checkout", "cs_A"),
            "/v1/subscriptions/sub_A": ("subscription", "sub_A"), "/v1/prices/price_A": ("price", "price_A"),
            "/v1/checkout/sessions/cs_A/line_items": ("checkout_lines", "cs_A"),
            "/v1/payment_methods/pm_A": ("payment_method", "pm_A"), "/v1/setup_intents/seti_A": ("setup_intent", "seti_A"),
            "/v1/invoices/in_A": ("invoice", "in_A"), "/v1/invoices/in_A/lines": ("invoice_lines", "in_A"),
        }
        outer = self
        class Connection:
            def __init__(self, host, *, port, timeout, context):
                self.host, self.port, self.timeout, self.context = host, port, timeout, context
                self.debuglevel, self.closed = 99, False
                outer.connections.append(self)
            def set_debuglevel(self, level):
                self.debuglevel = level
            def request(self, method, url, *, headers):
                assert self.debuglevel == 0
                self.url = url
                outer.calls.append((method, url, headers.copy()))
                if outer.error is not None:
                    raise outer.error
            def getresponse(self):
                connection = self
                class Response:
                    status = outer.status
                    def read(self, limit):
                        outer.reads.append(limit)
                        body = outer.body
                        if body is None:
                            path = urlsplit(connection.url).path
                            body = json.dumps(outer.reader.data[outer.paths[path]]).encode()
                        return body[:limit]
                return Response()
            def close(self):
                self.closed = True
        monkeypatch.setattr(V, "HTTPSConnection", Connection)


@pytest.mark.parametrize("version", ["2026-01-28.clover", VERSION])
def test_owned_https_uses_only_get_explicit_credentials_version_and_validating_transport(monkeypatch, version):
    http = InterceptHTTPS(monkeypatch)
    transport = BoundStripeReadTransport(BINDING, "sk_test_offline_synthetic", api_version=version)
    monkeypatch.setattr(stripe, "api_key", "sk_live_wrong_synthetic")
    monkeypatch.setattr(stripe, "api_base", "https://wrong.example.test")
    assert transport.get("account") == http.reader.data["account", None]
    result = StripeVerificationGateway(BINDING, transport, lambda: NOW).observe_trial_checkout(trial_request())
    assert result.outcome is C.VerificationOutcome.PENDING
    assert any(url == "/v1/setup_intents/seti_A" for _, url, _ in http.calls)
    for method, url, headers in http.calls:
        assert method == "GET" and url.startswith("/v1/")
        assert headers == {"Authorization": "Bearer sk_test_offline_synthetic", "Stripe-Version": version, "Accept": "application/json"}
        if urlsplit(url).path.endswith("line_items"):
            assert parse_qs(urlsplit(url).query) == {"limit": ["100"]}
    assert len(http.calls) == len(http.connections)  # No hidden retries or redirects.
    for connection in http.connections:
        assert (connection.host, connection.port, connection.timeout) == ("api.stripe.com", 443, 5)
        assert connection.context.check_hostname and connection.context.verify_mode == ssl.CERT_REQUIRED
        assert connection.closed and connection.debuglevel == 0
    assert "sk_test_" not in repr(transport)
    with pytest.raises(FrozenInstanceError):
        transport.binding = replace(BINDING, binding_id="other")
    with pytest.raises(NotImplementedError):
        transport.get("create_customer")


@pytest.mark.parametrize("body,status", [(b"{}", 500), (b"{}", 401), (b"{}", 404), (b"{}", 302),
    (b"not-json", 200), (b"[]", 200), (b'{"id":"a","id":"b"}', 200), (b'{"x":NaN}', 200)])
def test_intercepted_http_failure_or_malformed_body_cannot_be_positive_or_retry(monkeypatch, body, status):
    http = InterceptHTTPS(monkeypatch, body=body, status=status)
    transport = BoundStripeReadTransport(BINDING, "sk_test_offline_synthetic", api_version=VERSION)
    result = StripeVerificationGateway(BINDING, transport, lambda: NOW).observe_trial_checkout(trial_request())
    assert [(method, url) for method, url, _ in http.calls] == [("GET", "/v1/account")]
    assert result.outcome is C.VerificationOutcome.UNAVAILABLE
    assert result.customer is None and result.subscription is None
    assert http.connections[0].closed
    assert bool(http.reads) is (status == 200)


@pytest.mark.parametrize("case,outcome", [
    ("subscription", C.VerificationOutcome.CONFLICT), ("price", C.VerificationOutcome.CONFLICT),
    ("proration", C.VerificationOutcome.CONFLICT), ("quantity", C.VerificationOutcome.CONFLICT),
    ("amount", C.VerificationOutcome.CONFLICT), ("currency", C.VerificationOutcome.CONFLICT),
    ("unit_amount", C.VerificationOutcome.CONFLICT), ("coverage", C.VerificationOutcome.UNSUPPORTED),
    ("purpose", C.VerificationOutcome.UNSUPPORTED), ("invoice_subscription", C.VerificationOutcome.CONFLICT),
    ("malformed_proration", C.VerificationOutcome.UNAVAILABLE), ("fractional_quantity", C.VerificationOutcome.UNSUPPORTED),
    ("nested_quantity", C.VerificationOutcome.UNSUPPORTED), ("nested_currency", C.VerificationOutcome.UNSUPPORTED),
    ("nested_amount", C.VerificationOutcome.UNSUPPORTED), ("nested_coverage", C.VerificationOutcome.UNSUPPORTED),
    ("nested_purpose", C.VerificationOutcome.UNSUPPORTED), ("wrong_parent", C.VerificationOutcome.UNSUPPORTED),
])
def test_contradictory_or_unknown_financial_representations_reach_normalizer_and_fail_closed(case, outcome, monkeypatch):
    reader = Reader()
    line = reader.data["invoice_lines", "in_A"]["data"][0]
    if case == "subscription":
        line["subscription"] = "sub_other"
    elif case == "price":
        line["price"] = "price_other"
    elif case == "proration":
        line["proration"] = True
    elif case == "quantity":
        line["quantity_decimal"] = "2.000"
    elif case == "amount":
        line.update(amount=5900, subtotal=5901)
    elif case == "currency":
        line["price"] = {"id": "price_A", "currency": "eur"}
    elif case == "unit_amount":
        line["pricing"]["unit_amount_decimal"] = "5900.00"
        line["price"] = {"id": "price_A", "unit_amount": 6000}
    elif case == "coverage":
        line["period_start"] = START + 1
    elif case == "purpose":
        reader.data["invoice", "in_A"]["purpose"] = "renewal"
    elif case == "invoice_subscription":
        reader.data["invoice", "in_A"]["subscription"] = "sub_other"
    elif case == "malformed_proration":
        line["proration"] = "false"
    elif case == "fractional_quantity":
        line.pop("quantity")
        line["quantity_decimal"] = "1.25"
    elif case.startswith("nested_"):
        key = {"nested_quantity": "quantity", "nested_currency": "currency", "nested_amount": "amount",
            "nested_coverage": "period", "nested_purpose": "billing_reason"}[case]
        line["parent"]["subscription_item_details"][key] = "unmodeled-financial-evidence"
    else:
        line["parent"]["type"] = "invoice_item_details"
    reached = []
    original = StripeVerificationGateway._invoice_line
    def normalize(self, actual, invoice, subscription, terms):
        reached.append(True)
        return original(self, actual, invoice, subscription, terms)
    monkeypatch.setattr(StripeVerificationGateway, "_invoice_line", normalize)
    result = observe(reader, trial=False)
    # Explicit enum checks exclude unrelated AttributeError/TypeError false positives.
    assert result.outcome is outcome and result.settlement is None
    if case not in ("purpose", "invoice_subscription"):
        assert reached == [True]
    assert ("invoice", "in_A") in reader.calls


@pytest.mark.parametrize("shape", ["modern", "legacy", "dual"])
@pytest.mark.parametrize("reason,amount,purpose", [
    ("subscription_create", 0, C.SettlementPurpose.INITIAL_SUBSCRIPTION),
    ("subscription_cycle", 5900, C.SettlementPurpose.RENEWAL),
    ("subscription_cycle", 0, C.SettlementPurpose.RENEWAL),
])
def test_supported_invoice_shapes_preserve_consistent_terms_and_settlement_purpose(shape, reason, amount, purpose):
    reader = Reader()
    line = reader.data["invoice_lines", "in_A"]["data"][0]
    reader.data["invoice", "in_A"].update(billing_reason=reason, amount_paid=amount)
    if shape in ("legacy", "dual"):
        line.update(subscription={"id": "sub_A"}, price={"id": "price_A", "currency": "usd",
            "unit_amount": 5900, "unit_amount_decimal": "5900.00"}, proration=False,
            quantity_decimal="1.000", type="subscription")
    if shape == "legacy":
        line.pop("parent");line.pop("pricing")
        reader.data["invoice", "in_A"].pop("parent")
        reader.data["invoice", "in_A"]["subscription"] = "sub_A"
    else:
        line["pricing"]["unit_amount_decimal"] = "5900.0"
    result = observe(reader, trial=False)
    assert result.outcome is C.VerificationOutcome.VERIFIED
    assert result.settlement.settlement_confirmed and result.settlement.purpose is purpose
    assert result.settlement.coverage == ((NOW, END),)
    assert result.settlement.initial_subscription_invoice is (reason == "subscription_create")
    assert result.settlement.amount_paid.amount == Decimal(amount) / 100


@pytest.mark.parametrize("container", ["invoice_parent", "invoice_details", "line_parent", "line_details", "pricing", "price_details"])
@pytest.mark.parametrize("malformed", [False, [], 0, ""])
def test_falsey_malformed_mixed_shapes_are_not_silently_treated_as_absent(container, malformed):
    reader = Reader()
    line = reader.data["invoice_lines", "in_A"]["data"][0]
    # Supply otherwise valid legacy aliases so a truthiness fallback would pass.
    reader.data["invoice", "in_A"]["subscription"] = "sub_A"
    line.update(subscription="sub_A", price="price_A", proration=False)
    if container == "invoice_parent":
        reader.data["invoice", "in_A"]["parent"] = malformed
    elif container == "invoice_details":
        reader.data["invoice", "in_A"]["parent"]["subscription_details"] = malformed
    elif container == "line_parent":
        line["parent"] = malformed
    elif container == "line_details":
        line["parent"]["subscription_item_details"] = malformed
    elif container == "pricing":
        line["pricing"] = malformed
    else:
        line["pricing"]["price_details"] = malformed
    result = observe(reader, trial=False)
    assert result.outcome is C.VerificationOutcome.UNAVAILABLE and result.settlement is None


@pytest.mark.parametrize("location", ["subscription_item", "modern_line", "legacy_line"])
@pytest.mark.parametrize("change,outcome", [
    ("interval", C.VerificationOutcome.CONFLICT), ("usage", C.VerificationOutcome.CONFLICT),
    ("type", C.VerificationOutcome.CONFLICT), ("scheme", C.VerificationOutcome.CONFLICT),
    ("transform", C.VerificationOutcome.UNSUPPORTED), ("custom_amount", C.VerificationOutcome.UNSUPPORTED),
    ("unknown_financial", C.VerificationOutcome.UNSUPPORTED),
])
def test_expanded_price_claims_cannot_contradict_authoritative_price(location, change, outcome):
    reader = Reader()
    price = deepcopy(reader.data["price", "price_A"])
    if change == "interval":
        price["recurring"]["interval"] = "year"
    elif change == "usage":
        price["recurring"]["usage_type"] = "metered"
    elif change == "type":
        price["type"] = "one_time"
    elif change == "scheme":
        price["billing_scheme"] = "tiered"
    elif change == "transform":
        price["transform_quantity"] = {"divide_by": 100, "round": "up"}
    elif change == "custom_amount":
        price["custom_unit_amount"] = {"minimum": 1}
    else:
        price["financial_override"] = "unsupported"
    line = reader.data["invoice_lines", "in_A"]["data"][0]
    if location == "subscription_item":
        reader.data["subscription", "sub_A"]["items"]["data"][0]["price"] = price
    elif location == "modern_line":
        line["pricing"]["price_details"]["price"] = price
    else:
        line["price"] = price
    result = observe(reader, trial=False)
    assert result.outcome is outcome and result.settlement is None


def test_full_consistent_expanded_price_is_supported_at_all_read_sites():
    reader = Reader()
    price = reader.data["price", "price_A"]
    reader.data["subscription", "sub_A"]["items"]["data"][0]["price"] = deepcopy(price)
    line = reader.data["invoice_lines", "in_A"]["data"][0]
    line["pricing"]["price_details"]["price"] = deepcopy(price)
    line["price"] = deepcopy(price)
    assert observe(reader, trial=False).outcome is C.VerificationOutcome.VERIFIED


@pytest.mark.parametrize("location", ["root", "parent"])
@pytest.mark.parametrize("extra", [{"credited_items": {"invoice": "in_other"}}, {"unknown_financial": 1}, False])
def test_nonproration_cannot_hide_unsupported_proration_financial_details(location, extra):
    reader = Reader()
    line = reader.data["invoice_lines", "in_A"]["data"][0]
    target = line if location == "root" else line["parent"]["subscription_item_details"]
    target["proration_details"] = extra
    result = observe(reader, trial=False)
    expected = C.VerificationOutcome.UNAVAILABLE if extra is False else C.VerificationOutcome.UNSUPPORTED
    assert result.outcome is expected and result.settlement is None


@pytest.mark.parametrize("status,legacy_paid,outcome", [
    ("paid", False, C.VerificationOutcome.CONFLICT), ("open", True, C.VerificationOutcome.CONFLICT),
    ("paid", "true", C.VerificationOutcome.UNAVAILABLE), ("paid", True, C.VerificationOutcome.VERIFIED),
    ("open", False, C.VerificationOutcome.VERIFIED),
])
def test_invoice_paid_alias_must_agree_with_authoritative_status(status, legacy_paid, outcome):
    reader = Reader()
    reader.data["invoice", "in_A"].update(status=status, paid=legacy_paid)
    result = observe(reader, trial=False)
    assert result.outcome is outcome
    if outcome is C.VerificationOutcome.VERIFIED:
        assert result.settlement.settlement_confirmed is (status == "paid")
    else:
        assert result.settlement is None


@pytest.mark.parametrize("location,key,value", [
    ("invoice", "tax", 123), ("invoice", "total_tax_amounts", [{"amount": 123}]),
    ("line", "tax_amounts", [{"amount": 123}]),
])
def test_legacy_tax_fields_cannot_hide_unsupported_commercial_adjustments(location, key, value):
    reader = Reader()
    target = reader.data["invoice", "in_A"] if location == "invoice" else reader.data["invoice_lines", "in_A"]["data"][0]
    target[key] = value
    result = observe(reader, trial=False)
    assert result.outcome is C.VerificationOutcome.UNSUPPORTED and result.settlement is None


@pytest.mark.parametrize("scenario", ["success", "error", "malformed", "network", "oversize"])
def test_actual_transport_never_logs_secret_bodies_even_with_sdk_and_application_debug(monkeypatch, caplog, capsys, scenario):
    markers = ["synthetic-protected-client-secret", "synthetic-protected-api-token", "private-person@example.test"]
    payload = {"id": "seti_A", "object": "setup_intent", "client_secret": markers[0],
        "nested": {"access_token": markers[1], "email": markers[2]}}
    body = json.dumps(payload).encode()
    status, error = 200, None
    if scenario == "error":
        status = 400
    elif scenario == "malformed":
        body = body[:-1]
    elif scenario == "network":
        error = TimeoutError(" ".join(markers))
    elif scenario == "oversize":
        body += b" " * (2 * 1024 * 1024)
    http = InterceptHTTPS(monkeypatch, body=body, status=status, error=error)
    monkeypatch.setattr(stripe, "log", "debug")
    caplog.set_level(logging.DEBUG)
    caplog.set_level(logging.DEBUG, logger="stripe")
    from stripe import _util
    _util.log_debug("SDK DEBUG remains enabled")
    logging.getLogger("keel.verification.test").debug("Application DEBUG remains enabled")
    transport = BoundStripeReadTransport(BINDING, "sk_test_offline_synthetic", api_version=VERSION)
    error_text = ""
    if scenario == "success":
        assert transport.get("setup_intent", "seti_A") == payload
    else:
        with pytest.raises(V._Failure) as captured:
            transport.get("setup_intent", "seti_A")
        assert captured.value.outcome is C.VerificationOutcome.UNAVAILABLE
        assert captured.value.__context__ is None and captured.value.__cause__ is None
        error_text = str(captured.value) + repr(captured.value) + ''.join(traceback.format_exception(captured.value))
    output = capsys.readouterr()
    assert "SDK DEBUG remains enabled" in output.err and "SDK DEBUG remains enabled" in caplog.text
    assert "Application DEBUG remains enabled" in caplog.text
    protected_output = output.out + output.err + caplog.text + error_text + repr(transport)
    assert all(marker not in protected_output for marker in markers)
    assert "sk_test_offline_synthetic" not in protected_output
    assert len(http.calls) == 1 and http.calls[0][0] == "GET" and http.connections[0].closed


@pytest.mark.parametrize("identifier", ["..", "../account", "x?expand=y", "x\r\nHeader:value", "https://evil.example.test", "caf\u00e9"])
def test_transport_rejects_unsafe_identifiers_before_any_http(monkeypatch, identifier):
    http = InterceptHTTPS(monkeypatch)
    transport = BoundStripeReadTransport(BINDING, "sk_test_offline_synthetic", api_version=VERSION)
    with pytest.raises(V._Failure) as captured:
        transport.get("customer", identifier)
    assert captured.value.outcome is C.VerificationOutcome.UNAVAILABLE
    assert http.calls == [] and http.connections == []


@pytest.mark.parametrize("credential,version,timeout", [
    ("sk_live_wrong_synthetic", VERSION, 5), ("sk_test_offline_synthetic", "unknown", 5),
    ("sk_test_offline_synthetic", VERSION, 0),
])
def test_invalid_bound_transport_fails_before_dispatch(credential, version, timeout):
    with pytest.raises(ValueError):
        BoundStripeReadTransport(BINDING, credential, api_version=version, timeout=timeout)


def test_adapter_remains_optional_read_only_and_unimported_by_active_runtime():
    src = Path(__file__).resolve().parents[2] / "src"
    for path in (src / "ai").rglob("*.py"):
        if "tests" in path.parts or path.name == "stripe_verification.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").endswith("stripe_verification"), str(path)
                assert not any(n.name == "stripe_verification" for n in node.names), str(path)
            elif isinstance(node, ast.Import):
                assert not any(n.name.endswith("stripe_verification") for n in node.names), str(path)
    tree = ast.parse((src / "ai/billing/stripe_verification.py").read_text(encoding="utf-8"))
    assert not any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and n.func.attr in {"create", "modify", "delete", "confirm", "cancel", "execute", "commit"} for n in ast.walk(tree))
    assert "StripeVerificationGateway" not in (src / "ai/billing/payment_runtime.py").read_text(encoding="utf-8")
    assert not hasattr(C.SubscriptionPaymentGateway, "observe_trial_checkout")
