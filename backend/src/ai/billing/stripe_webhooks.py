"""Verify and translate Stripe notifications; never reconcile or grant access."""
from copy import deepcopy
from datetime import datetime, timezone

from src.ai.billing import stripe_api
from src.ai.billing.stripe_gateway import _checkout
from src.ai.billing.payment_contracts import (
    InvalidPaymentWebhook, PaymentEventKind as Kind, ProviderReference, VerifiedPaymentEvent,
)


_KINDS = {
    "checkout.session.completed": Kind.CHECKOUT_COMPLETED,
    "checkout.session.expired": Kind.CHECKOUT_EXPIRED,
    "invoice.paid": Kind.INVOICE_SETTLED,
    "invoice.payment_succeeded": Kind.INVOICE_SETTLED,
    "invoice.payment_failed": Kind.INVOICE_FAILED,
    **{name: Kind.SUBSCRIPTION_CHANGED for name in (
        "customer.subscription.created", "customer.subscription.updated", "customer.subscription.deleted",
        "customer.subscription.paused", "customer.subscription.resumed", "customer.subscription.trial_will_end",
        "customer.subscription.pending_update_applied", "customer.subscription.pending_update_expired")},
    **{name: Kind.SCHEDULE_ENDED for name in (
        "subscription_schedule.released", "subscription_schedule.completed",
        "subscription_schedule.canceled", "subscription_schedule.aborted")},
}


def _ref(value):
    if isinstance(value, dict):
        value = value.get("id")
    return ProviderReference("stripe", value) if value else None


class StripeWebhookDecoder:
    signature_header = "Stripe-Signature"

    def __init__(self, signing_secret: str):
        if not signing_secret:
            raise ValueError("A webhook signing secret is required")
        self._signing_secret = signing_secret

    def decode(self, payload: bytes, signature: str) -> VerifiedPaymentEvent:
        if not signature or not isinstance(payload, bytes):
            raise InvalidPaymentWebhook("Invalid payment webhook")
        try:
            # Existing SDK verification over the exact bytes, including its
            # timestamp tolerance, precedes parsing/translation or DB access.
            verified = stripe_api.construct_event(payload, signature, self._signing_secret)
            event = deepcopy(verified.to_dict() if hasattr(verified, "to_dict") else dict(verified))
            if not isinstance(event.get("id"), str) or not event["id"]:
                raise InvalidPaymentWebhook("Invalid payment webhook")
            kind = _KINDS.get(event["type"], Kind.UNKNOWN)
            obj = (event.get("data") or {}).get("object") or {}
            customer = _ref(obj.get("customer"))
            subscription, checkout, invoice, schedule = None, None, None, None
            if kind in (Kind.CHECKOUT_COMPLETED, Kind.CHECKOUT_EXPIRED):
                checkout, subscription, invoice = _ref(obj["id"]), _ref(obj.get("subscription")), _ref(obj.get("invoice"))
            elif kind == Kind.SUBSCRIPTION_CHANGED:
                subscription = _ref(obj["id"])
            elif kind in (Kind.INVOICE_SETTLED, Kind.INVOICE_FAILED):
                parent = (obj.get("parent") or {}).get("subscription_details") or {}
                subscription = (_ref(parent.get("subscription")) or
                    _ref((obj.get("subscription_details") or {}).get("subscription")) or _ref(obj.get("subscription")))
                invoice = _ref(obj["id"])
            elif kind == Kind.SCHEDULE_ENDED:
                schedule = _ref(obj["id"])
                subscription = _ref(obj.get("released_subscription")) or _ref(obj.get("subscription"))
            return VerifiedPaymentEvent(
                provider="stripe", event_id=event["id"], kind=kind,
                occurred_at=datetime.fromtimestamp(int(event["created"]), timezone.utc),
                customer=customer, subscription=subscription, checkout=checkout, invoice=invoice,
                schedule=schedule, raw_payload=payload, raw_evidence=event,
                checkout_snapshot=_checkout(obj) if kind in (Kind.CHECKOUT_COMPLETED, Kind.CHECKOUT_EXPIRED) else None,
            )
        except Exception:
            raise InvalidPaymentWebhook("Invalid payment webhook") from None
