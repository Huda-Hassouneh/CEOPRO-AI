"""Legacy Stripe reconciliation through neutral snapshots; offline DB doubles.

Non-Stripe events must use the protected journey handler and never this legacy path.

Native receipt/RLS/payment outcomes are separately exercised by the billing suite.
"""
import ast
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.ai.billing import promotions, store, stripe_api, webhooks
from src.ai.billing.payment_contracts import (
    CheckoutSnapshot, CheckoutState, InvoiceSnapshot, Money, PaymentEventKind as Kind,
    PaymentProviderError, PaymentState, ProviderOperationOutcome as Outcome,
    ProviderReference as Ref, SubscriptionItem, SubscriptionSnapshot, SubscriptionState,
    VerifiedPaymentEvent,
)
from src.ai.billing.stripe_gateway import _invoice, _subscription
from .test_payment_webhook_decoder import SECRET, event as stripe_event, signed
from .test_reconciliation_roles import restricted_runtime, send  # noqa: F401
from src.ai.billing.stripe_webhooks import StripeWebhookDecoder


NOW = datetime(2027, 1, 15, tzinfo=timezone.utc)


def notification(kind, **fields):
    return replace(VerifiedPaymentEvent(
        provider="stripe", event_id="notification-alpha", kind=kind, occurred_at=NOW,
        customer=None, subscription=Ref("stripe", "contract-alpha"), checkout=None,
        invoice=None, schedule=None, raw_payload=b"original evidence", raw_evidence={"type": "opaque-notification"},
    ), **fields)


class Provider:
    """Only neutral snapshots and opaque references; no provider event dictionaries."""
    def __init__(self):
        self.reads = []
        self.subscription = SubscriptionSnapshot(
            Ref("stripe", "contract-alpha"), Ref("stripe", "account-alpha"), SubscriptionState.ACTIVE,
            (SubscriptionItem(Ref("stripe", "item-alpha"), Ref("stripe", "offer-alpha"), 1),),
            NOW, NOW + timedelta(days=30), None, False, None)
        self.invoice = InvoiceSnapshot(
            Ref("stripe", "bill-alpha"), self.subscription.customer, self.subscription.reference,
            PaymentState.PAID, Money(Decimal("29"), "USD"), Money(Decimal("29"), "USD"),
            NOW, True, ((NOW, NOW + timedelta(days=30)),), settlement_confirmed=True, currency_explicit=True)

    def get_subscription(self, reference):
        self.reads.append(("subscription", reference))
        return self.subscription

    def get_invoice(self, reference):
        self.reads.append(("invoice", reference))
        return self.invoice


@pytest.fixture
def reconciliation(monkeypatch):
    provider, connection = Provider(), MagicMock()
    connection.verified_webhook_only = False
    # This fixture models unrelated legacy subscriptions; protected cohort
    # classification and failure behavior are exercised by journey native tests.
    connection.cursor.return_value.__enter__.return_value.fetchone.return_value = (False,)
    receipts, completed, applied, payments = [], set(), [], []

    def claim(conn, event):
        receipts.append(event)
        return event.event_id not in completed

    def finish(conn, event_id, tenant, error=None):
        if error is None:
            completed.add(event_id)

    monkeypatch.setattr(webhooks, "payment_gateway", lambda: provider)
    monkeypatch.setattr(store, "claim_payment_event", claim)
    monkeypatch.setattr(store, "finish_event", finish)
    monkeypatch.setattr(store, "tenant_for_subscription", lambda *a: "tenant-alpha")
    monkeypatch.setattr(store, "tenant_for_customer", lambda *a: "tenant-alpha")
    monkeypatch.setattr(store, "current_subscription", lambda *a: None)
    monkeypatch.setattr(store, "resolve_price", lambda *a: ("starter", "monthly"))
    monkeypatch.setattr(store, "apply_subscription", lambda *a, **k: applied.append((a, k)))
    monkeypatch.setattr(store, "record_payment", lambda *a, **k: payments.append((a, k)))
    monkeypatch.setattr(webhooks.entitlements, "forget", lambda *a: None)
    monkeypatch.setattr(promotions, "invoice_event", lambda *a, **k: None)
    return provider, connection, receipts, applied, payments


def test_neutral_notification_uses_fresh_state_and_deduplicates(reconciliation):
    provider, conn, receipts, applied, payments = reconciliation
    event = notification(Kind.SUBSCRIPTION_CHANGED, raw_evidence={"stale": "cancelled"})
    assert webhooks.handle_event(conn, event) == {"duplicate": False}
    assert webhooks.handle_event(conn, event) == {"duplicate": True}
    assert provider.reads == [("subscription", event.subscription)]
    assert applied[0][0][2] is provider.subscription
    assert applied[0][0][2].state == SubscriptionState.ACTIVE
    assert not payments and receipts == [event, event]
    sql = [call.args[0] for call in conn.cursor.return_value.__enter__.return_value.execute.call_args_list]
    assert any("pg_advisory_lock" in query for query in sql)
    assert any("pg_advisory_xact_lock" in query for query in sql)
    assert any("pg_advisory_unlock" in query for query in sql)


def test_unverified_dictionary_never_reaches_receipt_or_lock(reconciliation):
    _, conn, receipts, applied, payments = reconciliation
    with pytest.raises(TypeError, match="verified payment event"):
        webhooks.handle_event(conn, {"id": "untrusted"})
    conn.cursor.assert_not_called()
    assert not receipts and not applied and not payments


def test_unknown_notification_keeps_receipt_without_provider_or_entitlement_action(reconciliation):
    provider, conn, receipts, applied, payments = reconciliation
    event = notification(Kind.UNKNOWN)
    assert webhooks.handle_event(conn, event) == {"duplicate": False}
    assert receipts == [event] and not provider.reads and not applied and not payments


def test_provider_unavailable_is_retryable_then_duplicate_after_success(reconciliation, monkeypatch):
    provider, conn, _, applied, _ = reconciliation
    original = provider.get_subscription
    def fail(reference):
        raise PaymentProviderError(Outcome.UNAVAILABLE)
    monkeypatch.setattr(provider, "get_subscription", fail)
    event = notification(Kind.SUBSCRIPTION_CHANGED)
    with pytest.raises(webhooks.WebhookRetry):
        webhooks.handle_event(conn, event)
    assert not applied
    monkeypatch.setattr(provider, "get_subscription", original)
    assert webhooks.handle_event(conn, event) == {"duplicate": False}
    assert webhooks.handle_event(conn, event) == {"duplicate": True}
    assert len(applied) == 1


@pytest.mark.parametrize("mismatch", ["subscription", "invoice", "customer", "invoice_subscription", "unresolved_tenant", "unresolved_price"])
def test_identity_and_mapping_failures_remain_retryable(reconciliation, monkeypatch, mismatch):
    provider, conn, _, _, payments = reconciliation
    event = notification(Kind.INVOICE_SETTLED, invoice=provider.invoice.reference)
    if mismatch == "subscription":
        provider.subscription = replace(provider.subscription, reference=Ref("stripe", "foreign-contract"))
    elif mismatch == "invoice":
        provider.invoice = replace(provider.invoice, reference=Ref("stripe", "foreign-bill"))
    elif mismatch == "customer":
        provider.invoice = replace(provider.invoice, customer=Ref("stripe", "foreign-account"))
        monkeypatch.setattr(store, "tenant_for_customer", lambda conn, ref: "foreign-tenant" if ref == "foreign-account" else "tenant-alpha")
    elif mismatch == "invoice_subscription":
        provider.invoice = replace(provider.invoice, subscription=Ref("stripe", "foreign-contract"))
    elif mismatch == "unresolved_tenant":
        monkeypatch.setattr(store, "tenant_for_subscription", lambda *a: None)
        monkeypatch.setattr(store, "tenant_for_customer", lambda *a: None)
    else:
        monkeypatch.setattr(store, "resolve_price", lambda *a: None)
    with pytest.raises(webhooks.WebhookRetry):
        webhooks.handle_event(conn, event)
    assert not payments


@pytest.mark.parametrize("kind,paid,expected", [
    (Kind.INVOICE_SETTLED, True, "succeeded"), (Kind.INVOICE_FAILED, True, "succeeded"),
    (Kind.INVOICE_FAILED, False, "failed"), (Kind.INVOICE_SETTLED, False, None),
])
def test_current_invoice_truth_wins_over_notification_kind(reconciliation, kind, paid, expected):
    provider, conn, _, _, payments = reconciliation
    provider.invoice = replace(provider.invoice, payment_state=PaymentState.PAID if paid else PaymentState.UNPAID)
    event = notification(kind, invoice=provider.invoice.reference)
    if expected is None:
        with pytest.raises(webhooks.WebhookRetry):
            webhooks.handle_event(conn, event)
    else:
        assert webhooks.handle_event(conn, event) == {"duplicate": False}
        assert payments[0][0][2] is provider.invoice
        assert payments[0][0][4] == expected
    assert provider.reads[0] == ("invoice", event.invoice)


@pytest.mark.parametrize("case,verified", [
    ("post_trial_paid", True), ("zero_trial_invoice", False), ("missing_coverage", False),
    ("other_customer", False), ("other_subscription", False), ("not_confirmed", False),
    ("missing_invoice", False),
])
def test_post_trial_payment_requires_identity_status_and_current_coverage(reconciliation, monkeypatch, case, verified):
    provider, conn, _, applied, _ = reconciliation
    cutoff = NOW
    provider.subscription = replace(provider.subscription, trial_end=cutoff, latest_invoice=provider.invoice.reference)
    monkeypatch.setattr(store, "current_subscription", lambda *a: {
        "stripe_subscription_id": "contract-alpha", "trial_end": cutoff, "status": "trialing"})
    if case == "zero_trial_invoice":
        provider.invoice = replace(provider.invoice, amount_paid=Money(Decimal("0"), "USD"),
            coverage=((NOW - timedelta(days=14), NOW),))
    elif case == "missing_coverage":
        provider.invoice = replace(provider.invoice, coverage=())
    elif case == "other_customer":
        provider.invoice = replace(provider.invoice, customer=Ref("stripe", "foreign-account"))
    elif case == "other_subscription":
        provider.invoice = replace(provider.invoice, subscription=Ref("stripe", "foreign-contract"))
    elif case == "not_confirmed":
        provider.invoice = replace(provider.invoice, settlement_confirmed=False)
    elif case == "missing_invoice":
        provider.subscription = replace(provider.subscription, latest_invoice=None)
    webhooks.handle_event(conn, notification(Kind.SUBSCRIPTION_CHANGED))
    assert applied[0][1]["trial_payment_verified"] is verified


def test_custom_checkout_completion_only_correlates_and_cannot_attest_payment(reconciliation, monkeypatch):
    provider, conn, _, _, payments = reconciliation
    metadata = {"billing_kind": "custom_quote", "tenant_id": "tenant-alpha"}
    checkout = CheckoutSnapshot(Ref("stripe", "purchase-alpha"), CheckoutState.COMPLETE, PaymentState.PAID,
        customer=provider.subscription.customer, subscription=provider.subscription.reference,
        client_reference="attempt-alpha", metadata=metadata, is_subscription=True)
    synced, linked = [], []
    monkeypatch.setattr(webhooks, "sync_subscription", lambda *a, **k: synced.append((a, k)) or "tenant-alpha")
    monkeypatch.setattr(webhooks, "_record_custom_checkout_session", lambda *a: linked.append(a))
    webhooks.handle_event(conn, notification(Kind.CHECKOUT_COMPLETED, checkout=checkout.reference, checkout_snapshot=checkout))
    assert synced[0][0][1] == checkout.subscription and synced[0][1] == {}
    assert linked[0][1] is checkout and not payments


def test_original_evidence_is_persisted_without_normalizing_type_or_payload(monkeypatch):
    original = stripe_event("customer.subscription.updated", {"id": "sub_one", "metadata": {"keep": "أصل"}})
    payload, signature = signed(original)
    decoded = StripeWebhookDecoder(SECRET).decode(payload, signature)
    captured = []
    monkeypatch.setattr(store, "claim_event", lambda *a: captured.append(a) or True)
    assert store.claim_payment_event(None, decoded)
    assert captured[0] == (None, original["id"], original["type"], decoded.occurred_at, original)
    assert decoded.raw_payload == payload


@pytest.mark.parametrize("invalid", ["signature", "tampered", "expired", "malformed", "missing_identity"])
def test_http_verification_failure_never_opens_trusted_database(client, monkeypatch, invalid):
    from src.ai import db
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", SECRET)
    original = stripe_event("invoice.paid", {"id": "in_one"})
    if invalid == "missing_identity":
        del original["id"]
    payload, signature = signed(original, timestamp=1 if invalid == "expired" else None)
    if invalid == "signature":
        signature = "invalid"
    elif invalid == "tampered":
        payload += b" "
    elif invalid == "malformed":
        payload = b"invalid json"
    monkeypatch.setattr(db, "billing_webhook_connection", lambda *a: pytest.fail("Unverified event reached trusted DB"))
    response = client.post("/billing/webhook", content=payload, headers={"Stripe-Signature": signature})
    assert response.status_code == 400


def test_http_boundary_preserves_exact_bytes_and_opens_event_scoped_socket_after_decode(client, monkeypatch):
    from src.ai import db
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", SECRET)
    payload, signature = signed(stripe_event("future.provider.event", {"id": "opaque"}))
    original_verify, order = stripe_api.construct_event, []
    def verify(body, header, secret):
        order.append(("verified", body))
        return original_verify(body, header, secret)
    monkeypatch.setattr(stripe_api, "construct_event", verify)
    conn = MagicMock()
    monkeypatch.setattr(db, "billing_webhook_connection", lambda identity: order.append(("connection", identity)) or conn)
    def handle(connection, event):
        assert connection is conn and isinstance(event, VerifiedPaymentEvent)
        assert event.kind == Kind.UNKNOWN and event.raw_payload == payload
        order.append(("reconcile", event.event_id))
        return {"duplicate": False}
    monkeypatch.setattr(webhooks, "handle_event", handle)
    assert client.post("/billing/webhook", content=payload, headers={"Stripe-Signature": signature}).json() == {
        "received": True, "duplicate": False}
    assert order == [("verified", payload), ("connection", "evt_original"), ("reconcile", "evt_original")]
    conn.close.assert_called_once()


@pytest.mark.parametrize("case", ["tenant", "revision", "quote_state", "revision_state", "customer", "missing_session",
                                  "missing_payment", "overlap", "amount", "currency", "missing_currency", "invoice_reason", "expired"])
def test_custom_exact_contract_guards_are_not_bypassed_by_paid_event(monkeypatch, case):
    from src.ai.billing import admin
    provider, conn = Provider(), MagicMock()
    metadata = {"billing_kind": "custom_quote", "custom_quote_id": "quote-alpha",
                "custom_quote_revision_id": "revision-alpha", "quote_attempt_id": "attempt-alpha"}
    provider.subscription = replace(provider.subscription, metadata=metadata)
    row = ["tenant-alpha", "quote-alpha", "revision-alpha", "accepted", "revision-alpha", "accepted", {}, {},
           {"currency": "USD", "monthlyPriceUsd": "29.00", "billingPeriodMonths": 1},
           NOW + timedelta(days=1), "owner-alpha", "attempt-alpha", "purchase-alpha", None, False]
    if case == "tenant": row[0] = "foreign-tenant"
    elif case == "revision": row[2] = "other-revision"
    elif case == "quote_state": row[3] = "draft"
    elif case == "revision_state": row[5] = "draft"
    elif case == "missing_session": row[12] = None
    elif case == "amount": provider.invoice = replace(provider.invoice, amount_paid=Money(Decimal("28.99"), "USD"))
    elif case == "currency": provider.invoice = replace(provider.invoice, amount_paid=Money(Decimal("29"), "JOD"))
    elif case == "missing_currency": provider.invoice = replace(provider.invoice, currency_explicit=False)
    elif case == "invoice_reason": provider.invoice = replace(provider.invoice, initial_subscription_invoice=False)
    elif case == "expired": row[9] = NOW - timedelta(seconds=1)
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchone.side_effect = [tuple(row), None if case == "missing_payment" else ("succeeded",),
                                 (1,) if case == "overlap" else None]
    monkeypatch.setattr(webhooks, "payment_gateway", lambda: provider)
    monkeypatch.setattr(store, "tenant_for_customer", lambda *a: "foreign-tenant" if case == "customer" else "tenant-alpha")
    monkeypatch.setattr(admin, "set_custom_contract", lambda *a, **k: pytest.fail("Invalid paid event activated a contract"))
    with pytest.raises(webhooks.WebhookRetry):
        webhooks._sync_custom_quote_subscription(conn, provider.subscription, "tenant-alpha", NOW,
            payment_verified=True, invoice_id="bill-alpha", provider_event_id="notification-alpha")


@pytest.mark.parametrize("boundary", ["subscription", "payment"])
def test_normalized_and_legacy_persistence_produce_identical_sql(boundary):
    from .test_custom_webhook_contract import Connection
    from .test_database import live_subscription
    if boundary == "subscription":
        raw = live_subscription("tenant-alpha", "price_original")
        normalized = _subscription(raw)
        def persist(conn, obj):
            # No actual DB or entitlements here; compare the SQL/parameter seam.
            return store.apply_subscription(conn, "tenant-alpha", obj, "starter", "monthly", NOW)
    else:
        raw = {"id": "in_original", "currency": "usd", "amount_paid": 2900, "amount_due": 3000,
               "status_transitions": {"paid_at": int(NOW.timestamp())}, "hosted_invoice_url": "https://pay.example.test",
               "invoice_pdf": "https://pay.example.test/invoice", "lines": {"data": [{"period": {
                   "start": int(NOW.timestamp()), "end": int((NOW + timedelta(days=30)).timestamp())}}]}}
        normalized = _invoice(raw)
        def persist(conn, obj):
            return store.record_payment(conn, "tenant-alpha", obj, "sub_original", "succeeded")
    calls = []
    for obj in (raw, normalized):
        conn = Connection([])
        if boundary == "subscription":
            # The first lookup returns no existing subscription; the guarded
            # INSERT returns no row and stops before assignment mutation.
            conn._cursor.rows = [None, None]
            with pytest.raises(ValueError, match="another company"):
                persist(conn, obj)
        else:
            persist(conn, obj)
        calls.append(conn._cursor.statements)
    assert calls[0] == calls[1]


def test_reconciliation_has_no_provider_transport_or_event_name_branching():
    source = Path(webhooks.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            assert node.value.id != "stripe_api"
            assert not (node.value.id == "event" and node.attr in {"raw_evidence", "raw_payload"})
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert node.value not in {"invoice.paid", "invoice.payment_failed", "checkout.session.completed",
                "customer.subscription.updated", "subscription_schedule.released"}


@pytest.mark.parametrize("shape", ["invoice", "schedule"])
def test_expanded_empty_reference_preserves_legacy_fallback(shape):
    if shape == "invoice":
        obj = {"id": "in_one", "parent": {"subscription_details": {"subscription": {"id": None}}},
               "subscription": "sub_one"}
        decoded = StripeWebhookDecoder(SECRET).decode(*signed(stripe_event("invoice.paid", obj)))
        assert _invoice(obj).subscription == Ref("stripe", "sub_one")
    else:
        obj = {"id": "sched_one", "released_subscription": {"id": None}, "subscription": "sub_one"}
        decoded = StripeWebhookDecoder(SECRET).decode(*signed(stripe_event("subscription_schedule.released", obj)))
    assert decoded.subscription == Ref("stripe", "sub_one")


def test_native_unknown_event_retains_original_receipt_without_tenant_binding(send, owner_db):
    import uuid
    identity = "evt_unknown_" + uuid.uuid4().hex
    obj = {"id": "opaque_resource", "metadata": {"tenant_id": "untrusted-hint"}}
    first = send("future.provider.event", obj, identity)
    assert first.status_code == 200 and first.json() == {"received": True, "duplicate": False}
    assert send("future.provider.event", obj, identity).json() == {"received": True, "duplicate": True}
    with owner_db.cursor() as cur:
        cur.execute("SELECT event_type,payload,processed_at,tenant_id FROM billing_webhook_events WHERE stripe_event_id=%s", (identity,))
        kind, evidence, processed, tenant = cur.fetchone()
    assert kind == "future.provider.event" and evidence["data"]["object"] == obj
    assert processed is not None and tenant is None


@pytest.mark.parametrize("provider", ["paddle", "another"])
def test_non_stripe_notification_cannot_fall_through_to_legacy_rights(reconciliation, provider):
    remote, conn, receipts, applied, payments = reconciliation
    event = notification(Kind.SUBSCRIPTION_CHANGED, provider=provider,
                         subscription=Ref(provider, "original-subscription"))
    with pytest.raises(webhooks.WebhookRetry, match="Protected journey reconciliation unavailable"):
        webhooks.handle_event(conn, event)
    assert not remote.reads and not receipts and not applied and not payments


def test_protected_stripe_cohort_cannot_fall_through_to_legacy_rights(reconciliation):
    remote, conn, receipts, applied, payments = reconciliation
    conn.cursor.return_value.__enter__.return_value.fetchone.return_value = (True,)
    with pytest.raises(webhooks.WebhookRetry, match="Protected journey reconciliation unavailable"):
        webhooks.handle_event(conn, notification(Kind.SUBSCRIPTION_CHANGED))
    assert not remote.reads and not receipts and not applied and not payments
