"""
The only module that talks to Stripe. Every call goes through here so tests
replace these functions instead of the network, and so the API key is set in
one place. Uses the official stripe-python SDK.
"""
from copy import deepcopy
import stripe

from src.ai.billing import config, test_clock


def _plain(obj):
    """Stripe SDK objects (stripe 15+) are not dicts - no .get(), no dict() -
    but the billing code reads Stripe data as dicts everywhere. Every response
    is converted here, once, so callers (and tests that pass plain dicts)
    see the same shape."""
    return obj.to_dict() if hasattr(obj, "to_dict") else obj


class PaymentsNotConfigured(Exception):
    """STRIPE_SECRET_KEY isn't set on this server."""


def _client():
    test_clock.adapter()  # Reject accidental enabled mode before any provider operation.
    key = config.stripe_secret_key()
    if not key:
        raise PaymentsNotConfigured("STRIPE_SECRET_KEY is not set.")
    stripe.api_key = key
    stripe.max_network_retries = 2
    return stripe


def customer_namespace(client):
    return {'account':_plain(client.Account.retrieve())['id'], 'livemode':_plain(client.Balance.retrieve())['livemode']}


def prepare_customer_create(email, company_name, tenant_id, operation_id):
    client=_client()
    local=test_clock.adapter()
    options=local.creation_options(client) if local else {}
    return {'namespace':customer_namespace(client),'api_version':stripe.api_version,
            'params':{'email':email,'name':company_name,'metadata':{'tenant_id':tenant_id,'keel_customer_operation_id':operation_id},**options}}


def _customer_context(client, frozen):
    if customer_namespace(client)!=frozen['namespace']:
        raise ValueError('Frozen customer CREATE belongs to a different provider namespace.')
    options=frozen['params']
    if options.get('test_clock'):
        local=test_clock.adapter()
        if local is None:
            raise test_clock.TestClockError('Frozen Test Clock customer creation requires the local TEST adapter.')
        local.clock(client,clock_id=options['test_clock'])


def create_customer(email: str, company_name: str, tenant_id: str, idempotency_key: str, *, frozen=None):
    client = _client()
    if frozen is not None:
        _customer_context(client,frozen)
        return _plain(client.Customer.create(**deepcopy(frozen['params']),idempotency_key=idempotency_key,stripe_version=frozen['api_version']))
    local = test_clock.adapter()
    options = local.creation_options(client) if local else {}
    customer = _plain(client.Customer.create(
        email=email, name=company_name, metadata={"tenant_id": tenant_id},
        idempotency_key=idempotency_key, **options,
    ))
    if local:
        local.validate_customer(customer, tenant_id)
    return customer


def retrieve_customer(customer_id):
    return _plain(_client().Customer.retrieve(customer_id))


def recover_customer_create(tenant_id, operation_id, frozen):
    if frozen is None:
        # A legacy CREATE has no frozen namespace/options or operation marker.
        # A negative search cannot establish absence. Require original evidence.
        return None
    client=_client();_customer_context(client,frozen)
    params=frozen['params']
    if params.get('test_clock'):
        candidates=client.Customer.list(test_clock=params['test_clock'],limit=100).auto_paging_iter()
    else:
        candidates=client.Customer.search(query=f"metadata['keel_customer_operation_id']:'{operation_id}' AND metadata['tenant_id']:'{tenant_id}'",limit=100).auto_paging_iter()
    matches=[_plain(c) for c in candidates if (_plain(c).get('metadata') or {}).get('tenant_id')==tenant_id
             and (_plain(c).get('metadata') or {}).get('keel_customer_operation_id')==operation_id]
    if len(matches)>1:
        raise ValueError('Several provider customers claim the same logical operation.')
    return matches[0] if matches else None


def create_checkout_session(params: dict, idempotency_key: str):
    return _plain(_client().checkout.Session.create(**params, idempotency_key=idempotency_key))


def checkout_request_rejected(error: Exception) -> bool:
    """A provider validation rejection created no session. Timeouts stay unknown."""
    return isinstance(error, stripe.InvalidRequestError) and error.http_status == 400


def retrieve_checkout_session(session_id: str):
    return _plain(_client().checkout.Session.retrieve(session_id))


def customer_subscriptions(customer_id: str):
    return [_plain(item) for item in _client().Subscription.list(customer=customer_id, status="all", limit=100).auto_paging_iter()]


def open_customer_checkouts(customer_id: str):
    return [_plain(item) for item in _client().checkout.Session.list(customer=customer_id, status="open", limit=100).auto_paging_iter()]


def create_portal_session(customer_id: str, return_url: str):
    return _plain(_client().billing_portal.Session.create(customer=customer_id, return_url=return_url))


def retrieve_subscription(subscription_id: str):
    return _plain(_client().Subscription.retrieve(subscription_id, expand=["customer"]))


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


def expire_checkout_session(session_id: str):
    return _plain(_client().checkout.Session.expire(session_id))


def customer_clock_time(customer_id, tenant_id, *, require_clock=False):
    local = test_clock.adapter()
    if local is None:
        return None
    return local.customer_time(_client(), customer_id, tenant_id, require_clock=require_clock)
