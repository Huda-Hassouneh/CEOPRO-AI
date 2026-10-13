"""
The only module that talks to Stripe. Every call goes through here so tests
replace these functions instead of the network, and so the API key is set in
one place. Uses the official stripe-python SDK.
"""
import stripe

from src.ai.billing import config


class PaymentsNotConfigured(Exception):
    """STRIPE_SECRET_KEY isn't set on this server."""


def _client():
    key = config.stripe_secret_key()
    if not key:
        raise PaymentsNotConfigured("STRIPE_SECRET_KEY is not set.")
    stripe.api_key = key
    stripe.max_network_retries = 2
    return stripe


def create_customer(email: str, company_name: str, tenant_id: str, idempotency_key: str):
    return _client().Customer.create(
        email=email, name=company_name, metadata={"tenant_id": tenant_id},
        idempotency_key=idempotency_key,
    )


def create_checkout_session(params: dict, idempotency_key: str):
    return _client().checkout.Session.create(**params, idempotency_key=idempotency_key)


def create_portal_session(customer_id: str, return_url: str):
    return _client().billing_portal.Session.create(customer=customer_id, return_url=return_url)


def retrieve_subscription(subscription_id: str):
    return _client().Subscription.retrieve(subscription_id)


def modify_subscription(subscription_id: str, **params):
    return _client().Subscription.modify(subscription_id, **params)


def create_schedule_from_subscription(subscription_id: str):
    return _client().SubscriptionSchedule.create(from_subscription=subscription_id)


def retrieve_schedule(schedule_id: str):
    return _client().SubscriptionSchedule.retrieve(schedule_id)


def modify_schedule(schedule_id: str, **params):
    return _client().SubscriptionSchedule.modify(schedule_id, **params)


def release_schedule(schedule_id: str):
    return _client().SubscriptionSchedule.release(schedule_id, preserve_cancel_date=True)


def retrieve_invoice(invoice_id: str):
    return _client().Invoice.retrieve(invoice_id)


def create_product(name: str, idempotency_key: str):
    return _client().Product.create(name=name, metadata={"app": "apex"}, idempotency_key=idempotency_key)


def create_price(params: dict, idempotency_key: str):
    return _client().Price.create(**params, idempotency_key=idempotency_key)


def construct_event(payload: bytes, signature: str, secret: str):
    """Verifies the Stripe-Signature header against the raw body (default
    5-minute tolerance) and returns the event; raises on any mismatch."""
    return stripe.Webhook.construct_event(payload, signature, secret)
