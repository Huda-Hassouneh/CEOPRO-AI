"""
The only module that talks to Stripe. Every call goes through here so tests
replace these functions instead of the network, and so the API key is set in
one place. Uses the official stripe-python SDK.
"""
import stripe

from src.ai.billing import config


def _plain(obj):
    """Stripe SDK objects (stripe 15+) are not dicts - no .get(), no dict() -
    but the billing code reads Stripe data as dicts everywhere. Every response
    is converted here, once, so callers (and tests that pass plain dicts)
    see the same shape."""
    return obj.to_dict() if hasattr(obj, "to_dict") else obj


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
    return _plain(_client().Customer.create(
        email=email, name=company_name, metadata={"tenant_id": tenant_id},
        idempotency_key=idempotency_key,
    ))


def create_checkout_session(params: dict, idempotency_key: str):
    return _plain(_client().checkout.Session.create(**params, idempotency_key=idempotency_key))


def retrieve_checkout_session(session_id: str):
    return _plain(_client().checkout.Session.retrieve(session_id))


def create_portal_session(customer_id: str, return_url: str):
    return _plain(_client().billing_portal.Session.create(customer=customer_id, return_url=return_url))


def retrieve_subscription(subscription_id: str):
    return _plain(_client().Subscription.retrieve(subscription_id))


def modify_subscription(subscription_id: str, **params):
    return _plain(_client().Subscription.modify(subscription_id, **params))


def create_schedule_from_subscription(subscription_id: str):
    return _plain(_client().SubscriptionSchedule.create(from_subscription=subscription_id))


def retrieve_schedule(schedule_id: str):
    return _plain(_client().SubscriptionSchedule.retrieve(schedule_id))


def modify_schedule(schedule_id: str, **params):
    return _plain(_client().SubscriptionSchedule.modify(schedule_id, **params))


def release_schedule(schedule_id: str):
    return _plain(_client().SubscriptionSchedule.release(schedule_id, preserve_cancel_date=True))


def retrieve_invoice(invoice_id: str):
    return _plain(_client().Invoice.retrieve(invoice_id))


def create_product(name: str, idempotency_key: str):
    return _plain(_client().Product.create(name=name, metadata={"app": "apex"}, idempotency_key=idempotency_key))


def create_price(params: dict, idempotency_key: str):
    return _plain(_client().Price.create(**params, idempotency_key=idempotency_key))


def construct_event(payload: bytes, signature: str, secret: str):
    """Verifies the Stripe-Signature header against the raw body (default
    5-minute tolerance) and returns the event; raises on any mismatch."""
    return stripe.Webhook.construct_event(payload, signature, secret)


# --- Catalog reads/updates (scripts/stripe_sync_catalog.py reconciles with these) ---

def list_products(active: bool = True, limit: int = 100):
    return [_plain(p) for p in _client().Product.list(active=active, limit=limit).auto_paging_iter()]


def retrieve_product(product_id: str):
    return _plain(_client().Product.retrieve(product_id))


def list_prices(product_id: str, active: bool = True):
    return [_plain(p) for p in _client().Price.list(product=product_id, active=active, limit=100).auto_paging_iter()]


def retrieve_price(price_id: str):
    return _plain(_client().Price.retrieve(price_id))


# Managed promotion administration uses the same SDK/client authority as
# checkout. Stable idempotency keys are supplied by the promotions service so
# retries after a partial provider response do not create duplicate objects.
def create_coupon(params: dict, idempotency_key: str):
    return _plain(_client().Coupon.create(**params, idempotency_key=idempotency_key))


def retrieve_coupon(coupon_id: str):
    return _plain(_client().Coupon.retrieve(coupon_id))


def create_promotion_code(params: dict, idempotency_key: str):
    return _plain(_client().PromotionCode.create(**params, idempotency_key=idempotency_key))


def retrieve_promotion_code(promotion_code_id: str):
    return _plain(_client().PromotionCode.retrieve(promotion_code_id))


def deactivate_promotion_code(promotion_code_id: str):
    return _plain(_client().PromotionCode.modify(promotion_code_id, active=False))


def activate_promotion_code(promotion_code_id: str):
    return _plain(_client().PromotionCode.modify(promotion_code_id, active=True))
