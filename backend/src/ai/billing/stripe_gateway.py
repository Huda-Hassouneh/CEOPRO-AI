"""Stripe translation over the existing SDK wrapper; not wired into billing yet.

No SQL, commits, tenant lookup, eligibility, pricing or activation belongs here.
"""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal

import stripe

from src.ai.billing import stripe_api
from src.ai.billing.payment_contracts import (
    CheckoutIntent, CheckoutSnapshot, CheckoutState, InvoiceSnapshot, Money,
    PaymentProviderError, PaymentState, ProviderOperationOutcome as Outcome,
    ProviderReference, ScheduledChange, SubscriptionChangeIntent,
    SubscriptionChangeResult, SubscriptionItem, SubscriptionSnapshot, SubscriptionState,
)


def _reference(value):
    if isinstance(value, dict):
        value = value.get("id")
    return ProviderReference("stripe", value) if value else None


def _identifier(reference):
    if reference.provider != "stripe":
        raise PaymentProviderError(Outcome.UNSUPPORTED_CAPABILITY)
    return reference.opaque_id


def _required_reference(value):
    reference = _reference(value)
    if reference is None:
        raise ValueError("Provider response is missing a required reference")
    return reference


def _time(value):
    return datetime.fromtimestamp(int(value), timezone.utc) if value is not None else None


def _epoch(value):
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Payment timestamps must include a timezone")
    return int(value.timestamp())


def _enum(enum, value):
    return next((item for item in enum if item.value == value), enum.UNKNOWN)


def _checkout(data):
    return CheckoutSnapshot(
        reference=_required_reference(data["id"]), state=_enum(CheckoutState, data.get("status")),
        payment_state=_enum(PaymentState, {"no_payment_required": "not_required"}.get(
            data.get("payment_status"), data.get("payment_status"))),
        customer=_reference(data.get("customer")), subscription=_reference(data.get("subscription")),
        url=data.get("url"), client_reference=data.get("client_reference_id"),
        metadata=deepcopy(data.get("metadata") or {}),
        is_subscription=data.get("mode") == "subscription",
    )


def _subscription(data):
    items = (data.get("items") or {}).get("data") or []
    period = items[0] if items else {}
    state = {"canceled": "cancelled", "incomplete": "pending", "incomplete_expired": "expired",
             "unpaid": "payment_failed"}.get(data.get("status"), data.get("status"))
    return SubscriptionSnapshot(
        reference=_required_reference(data["id"]), customer=_required_reference(data["customer"]),
        state=_enum(SubscriptionState, state),
        items=tuple(SubscriptionItem(_required_reference(item["id"]), _required_reference(item["price"]),
                                     item.get("quantity", 1)) for item in items),
        period_start=_time(period.get("current_period_start") or data.get("current_period_start")),
        period_end=_time(period.get("current_period_end") or data.get("current_period_end")),
        trial_end=_time(data.get("trial_end")), cancel_at_period_end=bool(data.get("cancel_at_period_end")),
        cancelled_at=_time(data.get("canceled_at")), schedule=_reference(data.get("schedule")),
        latest_invoice=_reference(data.get("latest_invoice")), metadata=deepcopy(data.get("metadata") or {}),
    )


def _invoice_subscription(data):
    parent = (data.get("parent") or {}).get("subscription_details") or {}
    return _reference(parent.get("subscription") or (data.get("subscription_details") or {}).get("subscription")
                      or data.get("subscription"))


def _money(minor, currency):
    # Same Stripe representation as store._minor_to_major, without a float round-trip.
    if type(minor) is not int:
        raise ValueError("Provider monetary amounts must be integer minor units")
    zero_decimal = {"bif", "clp", "djf", "gnf", "jpy", "kmf", "krw", "mga", "pyg", "rwf", "vnd", "vuv", "xaf", "xof", "xpf"}
    return Money(Decimal(minor) / (1 if currency.lower() in zero_decimal else 100), currency)


def _invoice(data):
    currency = data.get("currency") or "usd"
    return InvoiceSnapshot(
        reference=_required_reference(data["id"]), customer=_reference(data.get("customer")),
        subscription=_invoice_subscription(data),
        payment_state=PaymentState.PAID if data.get("status") == "paid" or data.get("paid") is True else PaymentState.UNPAID,
        amount_paid=_money(data.get("amount_paid") or 0, currency),
        amount_due=_money(data.get("amount_due") or 0, currency),
        paid_at=_time((data.get("status_transitions") or {}).get("paid_at")),
        initial_subscription_invoice=data.get("billing_reason") == "subscription_create",
        coverage=tuple((_time((line.get("period") or {}).get("start")),
                        _time((line.get("period") or {}).get("end")))
                       for line in (data.get("lines") or {}).get("data", [])),
        payment_url=data.get("hosted_invoice_url"),
    )


def _call(operation, *, mutating=False, completed_writes=None):
    try:
        return operation()
    except PaymentProviderError:
        if completed_writes:
            raise PaymentProviderError(Outcome.OUTCOME_UNKNOWN) from None
        raise
    except Exception as error:
        if completed_writes:
            outcome = Outcome.OUTCOME_UNKNOWN
        elif stripe_api.checkout_request_rejected(error):
            outcome = Outcome.REJECTED
        elif isinstance(error, stripe.InvalidRequestError) and error.http_status == 404:
            outcome = Outcome.NOT_FOUND
        elif isinstance(error, (stripe_api.PaymentsNotConfigured, stripe.AuthenticationError, stripe.PermissionError)):
            outcome = Outcome.UNAVAILABLE
        else:
            # A timeout, 5xx or malformed reply after a write is not proof of failure.
            outcome = Outcome.OUTCOME_UNKNOWN if mutating else Outcome.UNAVAILABLE
        raise PaymentProviderError(outcome) from None


# Transitional parity with service._preserved_current_phase. Phase 2 can move
# the existing caller to this adapter; do not make the adapter import a service.
_PHASE_FIELDS = (
    "application_fee_percent", "automatic_tax", "billing_cycle_anchor", "billing_thresholds",
    "collection_method", "currency", "default_payment_method", "default_tax_rates", "description",
    "discounts", "invoice_settings", "metadata", "on_behalf_of", "proration_behavior", "transfer_data", "trial_end",
)


def _preserved_phase(phase, trial_end):
    if phase.get("add_invoice_items"):
        raise PaymentProviderError(Outcome.UNSUPPORTED_CAPABILITY)
    result = {key: deepcopy(phase[key]) for key in _PHASE_FIELDS if phase.get(key) is not None}
    result.update(start_date=phase["start_date"], end_date=phase["end_date"], items=[])
    for item in phase["items"]:
        saved = {key: deepcopy(item[key]) for key in ("quantity", "tax_rates", "discounts", "billing_thresholds", "metadata")
                 if item.get(key) is not None}
        saved.update(price=_reference(item["price"]).opaque_id)
        saved.setdefault("quantity", 1)
        result["items"].append(saved)
    if trial_end is not None:
        if phase.get("trial_end") not in (None, trial_end) or not phase["start_date"] < trial_end <= phase["end_date"]:
            raise PaymentProviderError(Outcome.REJECTED)
        result.update(trial_end=trial_end, end_date=trial_end)
    return result


class StripeGateway:
    def create_customer(self, *, email, company_name, tenant_reference, idempotency_key):
        if not idempotency_key:
            raise ValueError("A durable idempotency key is required")
        return _call(lambda: _required_reference(stripe_api.create_customer(
            email, company_name, tenant_reference, idempotency_key)["id"]), mutating=True)

    def list_customer_subscriptions(self, customer):
        identifier = _identifier(customer)
        return _call(lambda: tuple(_subscription(item) for item in stripe_api.customer_subscriptions(identifier)))

    def list_open_checkouts(self, customer):
        identifier = _identifier(customer)
        return _call(lambda: tuple(_checkout(item) for item in stripe_api.open_customer_checkouts(identifier)))

    def create_checkout(self, intent: CheckoutIntent):
        if intent.price is not None:
            line = {"price": _identifier(intent.price), "quantity": 1}
        else:
            amount = intent.recurring_amount
            # Current Custom settlement is USD cents. No FX or rounding policy here.
            minor = amount.amount * 100
            if amount.currency != "USD" or minor != minor.to_integral_value():
                raise PaymentProviderError(Outcome.UNSUPPORTED_CAPABILITY)
            line = {"price_data": {"currency": "usd", "unit_amount": int(minor),
                    "product_data": {"name": intent.product_name},
                    "recurring": {"interval": "month", "interval_count": intent.interval_months}}, "quantity": 1}
        params = {"mode": "subscription", "customer": _identifier(intent.customer), "line_items": [line],
                  "client_reference_id": intent.client_reference, "metadata": dict(intent.metadata),
                  "subscription_data": {"metadata": dict(intent.subscription_metadata)},
                  "payment_method_collection": "always", "success_url": intent.success_url.replace(
                      "{checkout_reference}", "{CHECKOUT_SESSION_ID}"),
                  "cancel_url": intent.cancel_url}
        if intent.trial_end is not None:
            params["subscription_data"].update(trial_end=_epoch(intent.trial_end),
                trial_settings={"end_behavior": {"missing_payment_method": "cancel"}})
        if intent.promotion is not None:
            params["discounts"] = [{"promotion_code": _identifier(intent.promotion)}]
        else:
            params["allow_promotion_codes"] = intent.allow_promotion_entry
        if intent.automatic_tax:
            params.update(automatic_tax={"enabled": True}, customer_update={"address": "auto", "name": "auto"})
        return self.replay_frozen_checkout(params, idempotency_key=intent.idempotency_key)

    def replay_frozen_checkout(self, frozen_params: dict, *, idempotency_key: str):
        """Stripe-only legacy bridge, deliberately outside the neutral protocol.

        Never derive retry parameters from a current catalog, quote or intent.
        Copy solely to prevent SDK/test-double mutation of persisted evidence.
        """
        if not idempotency_key:
            raise ValueError("The original provider idempotency key is required")
        return _call(lambda: _checkout(stripe_api.create_checkout_session(
            deepcopy(frozen_params), idempotency_key=idempotency_key)), mutating=True)

    def get_checkout(self, reference):
        identifier = _identifier(reference)
        return _call(lambda: _checkout(stripe_api.retrieve_checkout_session(identifier)))

    def expire_checkout(self, reference):
        identifier = _identifier(reference)
        return _call(lambda: _checkout(stripe_api.expire_checkout_session(identifier)), mutating=True)

    def get_subscription(self, reference):
        identifier = _identifier(reference)
        return _call(lambda: _subscription(stripe_api.retrieve_subscription(identifier)))

    def change_subscription(self, intent: SubscriptionChangeIntent):
        identifier, price = _identifier(intent.subscription), _identifier(intent.price)
        trial_end = _epoch(intent.trial_end) if intent.trial_end is not None else None
        completed = []

        def change():
            current = stripe_api.retrieve_subscription(identifier)
            if _time(current.get("trial_end")) != intent.trial_end and current.get("status") == "trialing":
                raise PaymentProviderError(Outcome.REJECTED)
            schedule = _reference(current.get("schedule"))
            if schedule:
                stripe_api.release_schedule(schedule.opaque_id)
                completed.append("released")
            params = {"items": [{"id": current["items"]["data"][0]["id"], "price": price, "quantity": 1}]}
            if trial_end is not None:
                params.update(proration_behavior="none", trial_end=trial_end)
            else:
                params.update(proration_behavior="always_invoice", payment_behavior="pending_if_incomplete")
            updated = stripe_api.modify_subscription(identifier, **params)
            completed.append("changed")
            pending = bool(updated.get("pending_update"))
            invoice = _reference(updated.get("latest_invoice"))
            payment_url = stripe_api.retrieve_invoice(invoice.opaque_id).get("hosted_invoice_url") if pending and invoice else None
            return SubscriptionChangeResult(_subscription(updated), pending, payment_url)
        return _call(change, mutating=True, completed_writes=completed)

    def schedule_change(self, intent: SubscriptionChangeIntent, *, now: datetime):
        identifier, price = _identifier(intent.subscription), _identifier(intent.price)
        cutoff = _epoch(intent.trial_end) if intent.trial_end is not None else None
        now_epoch = _epoch(now)
        completed = []

        def schedule_change():
            current = stripe_api.retrieve_subscription(identifier)
            if current.get("status") == "trialing" and _time(current.get("trial_end")) != intent.trial_end:
                raise PaymentProviderError(Outcome.REJECTED)
            schedule = _reference(current.get("schedule"))
            if schedule is None:
                schedule = _required_reference(stripe_api.create_schedule_from_subscription(identifier)["id"])
                completed.append("created")
            data = stripe_api.retrieve_schedule(schedule.opaque_id)
            selected = data.get("current_phase") or {}
            phases = data.get("phases") or []
            phase = next((p for p in phases if p.get("start_date") == selected.get("start_date")
                          and p.get("end_date") == selected.get("end_date")), None)
            phase = phase or next((p for p in phases if (p.get("end_date") or 0) > now_epoch), None)
            if phase is None:
                raise PaymentProviderError(Outcome.OUTCOME_UNKNOWN)
            preserved = _preserved_phase(phase, cutoff)
            stripe_api.modify_schedule(schedule.opaque_id, end_behavior="release", proration_behavior="none",
                phases=[preserved, {"items": [{"price": price, "quantity": 1}]}])
            return ScheduledChange(schedule, _time(preserved["end_date"]))
        return _call(schedule_change, mutating=True, completed_writes=completed)

    def cancel_scheduled_change(self, schedule):
        identifier = _identifier(schedule)
        _call(lambda: stripe_api.release_schedule(identifier), mutating=True)
        return Outcome.SUCCESS

    def set_cancellation(self, subscription, *, cancel_at_period_end):
        identifier = _identifier(subscription)
        completed = []

        def cancel():
            if cancel_at_period_end:
                current = stripe_api.retrieve_subscription(identifier)
                schedule = _reference(current.get("schedule"))
                if schedule:
                    stripe_api.release_schedule(schedule.opaque_id)
                    completed.append("released")
            return _subscription(stripe_api.modify_subscription(identifier, cancel_at_period_end=cancel_at_period_end))
        return _call(cancel, mutating=True, completed_writes=completed)

    def get_invoice(self, reference):
        identifier = _identifier(reference)
        return _call(lambda: _invoice(stripe_api.retrieve_invoice(identifier)))

    def create_portal(self, customer, *, return_url):
        identifier = _identifier(customer)
        return _call(lambda: stripe_api.create_portal_session(identifier, return_url)["url"], mutating=True)
