"""
The only module that talks to Stripe. Every call goes through here so tests
replace these functions instead of the network, and so the API key is set in
one place. Uses the official stripe-python SDK.
"""
import stripe
from datetime import datetime, timezone

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


def create_customer(email: str, company_name: str, tenant_id: str, idempotency_key: str):
    client = _client()
    local = test_clock.adapter()
    options = local.creation_options(client) if local else {}
    customer = _plain(client.Customer.create(
        email=email, name=company_name, metadata={"tenant_id": tenant_id},
        idempotency_key=idempotency_key, **options,
    ))
    if local:
        local.validate_customer(customer, tenant_id)
    return customer


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


def expire_checkout_session(session_id: str):
    return _plain(_client().checkout.Session.expire(session_id))


def customer_clock_time(customer_id, tenant_id, *, require_clock=False):
    local = test_clock.adapter()
    if local is None:
        return None
    return local.customer_time(_client(), customer_id, tenant_id, require_clock=require_clock)


CUSTOMER_ENCODER = 'stripe-customer-v2-no-replay'


class BoundCustomerTransport:
    """Dormant request-scoped SDK client. Never uses _client/global API keys.

    Credentials come only from a future platform-controlled binding resolver.
    The encoder revision fixes zero retries/backoff and equal connect/read
    timeouts. These are NOT a total deadline or a remote arrival guarantee.
    After a submission marker, recovery is read-only; automatic replay is off.
    No caller or environment can construct this from the current runtime path.
    """
    def __init__(self, binding, credential, *, api_version, replay_window_seconds=0, timeout=5):
        from src.ai.billing.payment_contracts import GatewayEnvironment
        if binding.provider != 'stripe' or not api_version or not 1 <= timeout <= 20:
            raise ValueError('Explicit Stripe binding/version/timeout required')
        prefix = ('sk_test_', 'rk_test_') if binding.environment is GatewayEnvironment.TEST else ('sk_live_', 'rk_live_')
        if not credential.startswith(prefix):
            raise ValueError('Credential mode does not match binding')
        self._policy = (binding, api_version, replay_window_seconds, timeout)
        # Requests defaults to zero adapter retries. Refuse HTTP redirects too:
        # a 307/308 must not silently repeat a Customer write at another URL.
        import requests
        session = requests.Session()
        session.max_redirects = 0
        self._sdk = stripe.StripeClient(credential, stripe_version=api_version,
            max_network_retries=0, http_client=stripe.RequestsClient(
                timeout=(timeout, timeout), session=session, verify_ssl_certs=True))

    binding = property(lambda self: self._policy[0])
    api_version = property(lambda self: self._policy[1])
    replay_window_seconds = property(lambda self: self._policy[2])
    timeout = property(lambda self: self._policy[3])
    max_network_retries = property(lambda self: 0)
    backoff_seconds = property(lambda self: 0)

    def _validate_policy(self, request):
        from src.ai.billing.payment_contracts import PaymentProviderError, ProviderOperationOutcome as Outcome
        if (request.binding != self.binding or request.api_version != self.api_version
            or request.encoder_version != CUSTOMER_ENCODER
            or request.dispatch_timeout_seconds != self.timeout
            or request.replay_window_seconds != self.replay_window_seconds
            or self.max_network_retries != 0 or self.backoff_seconds != 0):
            raise PaymentProviderError(Outcome.UNSUPPORTED_CAPABILITY)

    def _check_budget(self, request, deadline):
        from src.ai.billing.payment_contracts import CapabilityState, PaymentProviderError, ProviderOperationOutcome as Outcome
        if (request.replay_support is not CapabilityState.SUPPORTED
            or request.replay_window_seconds <= request.dispatch_timeout_seconds + 2
            or (deadline - datetime.now(timezone.utc)).total_seconds() <= request.dispatch_timeout_seconds + 2):
            raise PaymentProviderError(Outcome.UNAVAILABLE)

    def verify_namespace(self):
        from src.ai.billing.payment_contracts import GatewayEnvironment
        account = _plain(self._sdk.raw_request('get', '/v1/account'))
        balance = _plain(self._sdk.v1.balance.retrieve())
        if account.get('id') != self.binding.merchant_account_id or balance.get('livemode') is not (
            self.binding.environment is GatewayEnvironment.LIVE
        ):
            raise ValueError('Provider namespace mismatch')

    def create(self, request, *, deadline, authorize):
        from src.ai.billing.payment_contracts import PaymentProviderError, ProviderOperationOutcome as Outcome
        self._validate_policy(request)
        self._check_budget(request, deadline)
        payload = request.transport.unpack()  # Prepare before the final checks.
        receipt = authorize()  # Commits; no database locks span the SDK call.
        # Even a still-valid legacy replay authorization is not dispatch authority.
        if (not isinstance(receipt, dict) or receipt.get('dispatch_count') != 1
            or receipt.get('state') != 'submitted'
            or receipt.get('operation_id') != request.operation_id
            or receipt.get('tenant_id') != request.tenant_id
            or receipt.get('idempotency_key') != request.idempotency_key
            or receipt.get('binding') != dict(binding_id=self.binding.binding_id,
                provider=self.binding.provider, environment=self.binding.environment.value,
                merchant_account_id=self.binding.merchant_account_id)
            or datetime.fromisoformat(receipt['replay_deadline']) != deadline):
            raise PaymentProviderError(Outcome.UNSUPPORTED_CAPABILITY)
        self._validate_policy(request)
        self._check_budget(request, deadline)
        # This last refusal check covers pauses in preparation/authorization. It
        # cannot fence arbitrary pauses inside HTTP/DNS or guarantee arrival.
        # Safety after ambiguity comes from NEVER automatically resubmitting.
        return _plain(self._sdk.v1.customers.create(payload, options={
            'idempotency_key': request.idempotency_key, 'max_network_retries': 0}))

    def retrieve(self, identifier):
        return _plain(self._sdk.v1.customers.retrieve(identifier))

    def checkout_create(self, payload, key):
        return _plain(self._sdk.v1.checkout.sessions.create(payload, options={
            'idempotency_key': key, 'max_network_retries': 0}))

    def checkout_retrieve(self, identifier):
        return _plain(self._sdk.v1.checkout.sessions.retrieve(identifier))

    def checkout_expire(self, identifier, key):
        return _plain(self._sdk.v1.checkout.sessions.expire(identifier,options={'idempotency_key':key,'max_network_retries':0}))

    def subscription_retrieve(self, identifier):
        return _plain(self._sdk.v1.subscriptions.retrieve(identifier))

    def subscription_cancel(self, identifier, key):
        return _plain(self._sdk.v1.subscriptions.update(identifier,{'cancel_at_period_end':True},
            options={'idempotency_key':key,'max_network_retries':0}))

    def checkout_list(self, customer):
        # Enumerate every status for exact-operation recovery, never open-only.
        return [_plain(v) for v in self._sdk.v1.checkout.sessions.list({'customer': customer, 'limit':100}).auto_paging_iter()]

    def search(self, tenant_id, operation_id):
        # UUIDs originate in KEEL and are validated before query interpolation.
        from uuid import UUID
        UUID(tenant_id); UUID(operation_id)
        result = self._sdk.v1.customers.search({'query':
            f"metadata['tenant_id']:'{tenant_id}' AND metadata['keel_customer_operation_id']:'{operation_id}'",
            'limit': 100})
        return [_plain(item) for item in result.auto_paging_iter()]
