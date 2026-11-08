"""Dormant, GET-only Stripe observations. No selection, SQL or billing writes.

The platform must supply an original persisted binding and its private client.
No default credentials, catalog lookup, consent flags or historical adoption.
Current KEEL Checkout does not record an approved recurring consent/version;
therefore this implementation NEVER emits VERIFIED for trial Checkout. B3 must
introduce trusted KEEL consent provenance without inventing Stripe references.
Provider doubles establish parser behavior, not merchant/provider acceptance.
"""
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from http.client import HTTPSConnection
import ssl
from urllib.parse import quote

from src.ai.billing import payment_contracts as C


API_VERSIONS = frozenset({"2026-01-28.clover", "2026-08-26.dahlia"})
ADAPTER_VERSION = "stripe-observation-v1-no-trial-consent"
_STATES = {
    "trialing": C.SubscriptionState.TRIALING, "active": C.SubscriptionState.ACTIVE,
    "past_due": C.SubscriptionState.PAST_DUE, "incomplete": C.SubscriptionState.PENDING,
    "incomplete_expired": C.SubscriptionState.EXPIRED, "unpaid": C.SubscriptionState.PAYMENT_FAILED,
    "paused": C.SubscriptionState.PAUSED, "canceled": C.SubscriptionState.CANCELLED,
}
_PATHS = {
    "checkout": ("/v1/checkout/sessions/", ""), "checkout_lines": ("/v1/checkout/sessions/", "/line_items"),
    "customer": ("/v1/customers/", ""), "subscription": ("/v1/subscriptions/", ""),
    "price": ("/v1/prices/", ""), "payment_method": ("/v1/payment_methods/", ""),
    "setup_intent": ("/v1/setup_intents/", ""), "invoice": ("/v1/invoices/", ""),
    "invoice_lines": ("/v1/invoices/", "/lines"),
}


class _Failure(Exception):
    def __init__(self, outcome):
        super().__init__(outcome.value)  # Never retain raw provider errors.
        self.outcome = outcome


def _conflict():
    raise _Failure(C.VerificationOutcome.CONFLICT)


def _unavailable():
    raise _Failure(C.VerificationOutcome.UNAVAILABLE)


def _unsupported():
    raise _Failure(C.VerificationOutcome.UNSUPPORTED)


def _identifier(value):
    if type(value) is dict:
        value = value.get("id")
    if type(value) is not str or not value or value != value.strip():
        _unavailable()
    return value


def _time(value):
    if type(value) is not int or value < 0:
        _unavailable()
    return datetime.fromtimestamp(value, timezone.utc)


def _money(value, currency):
    # Current KEEL Standard/Custom prices are USD. No speculative FX or
    # currency-exponent policy is introduced for future gateways/currencies.
    if currency != "usd":
        _unsupported()
    if type(value) is not int or value < 0:
        _unavailable()
    return C.Money(Decimal(value) / Decimal(100), currency)


def _list(data):
    if type(data) is not dict or type(data.get("data")) is not list:
        _unavailable()
    if data.get("has_more") is not False:
        _unsupported()  # Never mistake a truncated page for complete evidence.
    return data["data"]


def _no_adjustments(data):
    if (data.get("discount") or data.get("discounts") or data.get("discount_amounts")
            or data.get("total_discount_amounts") or data.get("default_tax_rates")
            or data.get("tax_rates") or data.get("taxes") or data.get("total_taxes")
            or data.get("tax") or data.get("tax_amounts") or data.get("total_tax_amounts")
            or (data.get("automatic_tax") or {}).get("enabled") is True):
        _unsupported()  # Frozen discount/tax semantics are not in B1 terms.


def _consistent(decode, *values):
    """All populated representations of one fact must agree, including False/0."""
    decoded = [decode(value) for value in values if value is not None]
    if not decoded:
        _unavailable()
    if any(value != decoded[0] for value in decoded[1:]):
        _conflict()
    return decoded[0]


def _boolean(value):
    if type(value) is not bool:
        _unavailable()
    return value


def _decimal(value):
    if type(value) not in (str, int):
        _unavailable()
    number = Decimal(value)
    if not number.is_finite() or number < 0:
        _unavailable()
    return number


def _only(data, allowed):
    # Unknown nested financial shapes are unsupported, never silently merged.
    if data is None:
        return {}
    if type(data) is not dict:
        _unavailable()
    if set(data) - set(allowed):
        _unsupported()
    return data


def _json_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate JSON field")
        value[key] = item
    return value


def _json_constant(value):
    raise ValueError("Non-finite JSON number")


@dataclass(frozen=True, init=False, repr=False)
class BoundStripeReadTransport:
    """Explicit root-account HTTPS reads, isolated from SDK payload logging.

    Root-account credentials only. Connect/MoR account selection is not guessed.
    Zero retries/redirects; connect/read timeouts are not total wall-clock bounds.
    Constructing this class performs no request. Only get() can perform GETs.
    """
    binding: C.GatewayBinding
    api_version: str
    _credential: str = field(repr=False)
    _timeout: int = field(repr=False)

    def __init__(self, binding, credential, *, api_version, timeout=5):
        C._observation_scope(binding)
        if binding.provider != "stripe" or type(api_version) is not str or api_version not in API_VERSIONS:
            raise ValueError("Unsupported explicit Stripe binding/API version")
        prefixes = ("sk_test_", "rk_test_") if binding.environment is C.GatewayEnvironment.TEST else ("sk_live_", "rk_live_")
        if type(credential) is not str or not credential.startswith(prefixes):
            raise ValueError("Stripe credential environment mismatch")
        if type(timeout) is not int or not 1 <= timeout <= 20:
            raise ValueError("Bounded Stripe read timeout required")
        object.__setattr__(self, "binding", binding)
        object.__setattr__(self, "api_version", api_version)
        object.__setattr__(self, "_credential", credential)
        object.__setattr__(self, "_timeout", timeout)

    def get(self, kind, identifier=None):
        if kind in ("account", "balance"):
            path = "/v1/" + kind
        elif kind in _PATHS:
            prefix, suffix = _PATHS[kind]
            identifier = _identifier(identifier)
            if not identifier.isascii() or any(not (c.isalnum() or c == "_") for c in identifier):
                _unavailable()  # No path traversal, query/header injection or arbitrary URLs.
            path = prefix + quote(identifier, safe="") + suffix
            if kind in ("checkout_lines", "invoice_lines"):
                path += "?limit=100"
        else:
            raise NotImplementedError("Unsupported Stripe observation read")
        connection, value = None, None
        try:
            context = ssl.create_default_context()
            connection = HTTPSConnection("api.stripe.com", port=443, timeout=self._timeout, context=context)
            connection.set_debuglevel(0)  # Instance only; never global logging/SDK state.
            connection.request("GET", path, headers={
                "Authorization": "Bearer " + self._credential,
                "Stripe-Version": self.api_version, "Accept": "application/json",
            })
            response = connection.getresponse()
            # No redirects, retries, proxy/environment credentials or error-body logging.
            # Socket timeout is NOT an end-to-end wall-clock guarantee.
            if response.status == 200:
                body = response.read(2 * 1024 * 1024 + 1)
                if len(body) <= 2 * 1024 * 1024:
                    value = json.loads(body.decode("utf-8"), object_pairs_hook=_json_object,
                        parse_constant=_json_constant)
        except Exception:
            value = None
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    value = None
        # Raise OUTSIDE the handler: no chained provider/JSON exception carrying
        # raw body, credentials or PII. No logger or stderr output on any path.
        if type(value) is not dict:
            _unavailable()
        return value


@dataclass(frozen=True, repr=False)
class StripeVerificationGateway:
    """Optional C.ProviderVerificationGateway; injected reader is trusted code.

    An unresolved reader fails closed, never consulting environment/defaults.
    Provenance describes a lookup attempt; only VERIFIED describes complete
    authoritative observations. It is still not permission to activate rights.
    """
    binding: C.GatewayBinding
    _reader: object = field(repr=False)
    _clock: object = field(default=lambda: datetime.now(timezone.utc), repr=False)
    _api_version: str = field(init=False, repr=False)
    _read: object = field(init=False, repr=False)

    def __post_init__(self):
        C._observation_scope(self.binding)
        if self.binding.provider != "stripe":
            raise ValueError("Stripe verification requires original Stripe binding")
        object.__setattr__(self, "_api_version", getattr(self._reader, "api_version", "unresolved"))
        object.__setattr__(self, "_read", getattr(self._reader, "get", None))

    def _get(self, kind, identifier=None):
        reader = self._reader
        if reader is None:
            _unavailable()
        if reader.binding != self.binding:
            _conflict()
        if reader.api_version != self._api_version:
            _conflict()
        if self._api_version not in API_VERSIONS:
            _unsupported()
        value = self._read(kind, identifier)
        if reader.binding != self.binding:
            _conflict()
        if reader.api_version != self._api_version:
            _conflict()
        if type(value) is not dict:
            _unavailable()
        return deepcopy(value)

    def _object(self, kind, identifier):
        identifier = _identifier(identifier)
        value = self._get(kind, identifier)
        object_type = {"checkout": "checkout.session"}.get(kind, kind)
        if value.get("id") != identifier or value.get("object") != object_type:
            _conflict()
        if value.get("livemode") is not (self.binding.environment is C.GatewayEnvironment.LIVE):
            _conflict()
        if value.get("deleted") is True:
            _conflict()
        if value.get("on_behalf_of") is not None or value.get("transfer_data"):
            _unsupported()  # No guessed Connect/merchant-of-record namespace.
        return value

    def _ref(self, identifier):
        return C.ProviderReference("stripe", _identifier(identifier), binding=self.binding)

    def _namespace(self):
        account, balance = self._get("account"), self._get("balance")
        if (account.get("id") != self.binding.merchant_account_id or account.get("object") != "account"
                or balance.get("object") != "balance"
                or balance.get("livemode") is not (self.binding.environment is C.GatewayEnvironment.LIVE)):
            _conflict()

    def _customer(self, request):
        customer = self._object("customer", request.customer.opaque_id)
        metadata = customer.get("metadata") or {}
        if metadata.get("tenant_id") not in (None, request.tenant_id):
            _conflict()
        if request.customer_operation_id is not None:
            operation = metadata.get("keel_customer_operation_id")
            if operation is None:
                _unavailable()  # No automatic historical adoption.
            if operation != request.customer_operation_id:
                _conflict()
        return customer

    def _subscription(self, request, identifier):
        subscription = self._object("subscription", identifier)
        if request.subscription is not None and identifier != request.subscription.opaque_id:
            _conflict()
        if _identifier(subscription.get("customer")) != request.customer.opaque_id:
            _conflict()
        if (subscription.get("metadata") or {}).get("tenant_id") not in (None, request.tenant_id):
            _conflict()
        if subscription.get("status") not in _STATES:
            _unsupported()
        _no_adjustments(subscription)
        issuer = (subscription.get("invoice_settings") or {}).get("issuer")
        if issuer is not None and issuer.get("type") != "self":
            _unsupported()
        items = _list(subscription.get("items"))
        if len(items) != 1:
            _unsupported()
        item = items[0]
        if _identifier(item.get("subscription")) != identifier:
            _conflict()
        _no_adjustments(item)
        price_id = _identifier(item.get("price"))
        price = self._object("price", price_id)
        if subscription.get("currency") != price.get("currency"):
            _conflict()
        if type(request) is C.TrialObservationRequest and price.get("currency", "").upper() != request.approved_terms.currency:
            _conflict()
        recurring = price.get("recurring") or {}
        if (price.get("type") != "recurring" or price.get("billing_scheme") != "per_unit"
                or recurring.get("usage_type") != "licensed" or price.get("transform_quantity")):
            _unsupported()
        multiplier = {"month": 1, "year": 12}.get(recurring.get("interval"))
        count, quantity = recurring.get("interval_count"), item.get("quantity")
        if multiplier is None:
            _unsupported()
        if type(count) is not int or count <= 0 or type(quantity) is not int or quantity <= 0:
            _unavailable()
        amount = _money(price.get("unit_amount"), price.get("currency"))
        if price.get("unit_amount_decimal") is not None and Decimal(price["unit_amount_decimal"]) != price["unit_amount"]:
            _unsupported()
        terms = C.ObservedRecurringTerms(amount, multiplier * count, quantity, self._ref(price_id))
        self._price_claims(item.get("price"), terms)
        expected = request.expected_terms if type(request) is C.TrialObservationRequest else None
        if expected is not None and terms != expected:
            _conflict()
        begin, end = item.get("current_period_start"), item.get("current_period_end")
        for name, value in (("current_period_start", begin), ("current_period_end", end)):
            root = subscription.get(name)
            if root is not None and value is not None and root != value:
                _conflict()
        begin = begin if begin is not None else subscription.get("current_period_start")
        end = end if end is not None else subscription.get("current_period_end")
        if type(subscription.get("cancel_at_period_end")) is not bool:
            _unavailable()
        facts = dict(customer=request.customer, subscription=self._ref(identifier), terms=terms,
            subscription_state=_STATES[subscription["status"]], period_start=_time(begin), period_end=_time(end),
            cancel_at_period_end=subscription["cancel_at_period_end"], cancelled_at=(
                _time(subscription["canceled_at"]) if subscription.get("canceled_at") is not None else None))
        if subscription.get("trial_start") is not None or subscription.get("trial_end") is not None:
            start, stop = _time(subscription.get("trial_start")), _time(subscription.get("trial_end"))
            facts["trial"] = C.ObservedTrialWindow(start, stop, stop)
        return subscription, facts

    def _method(self, request, customer, subscription):
        source = self._ref(subscription["id"])
        method_id = subscription.get("default_payment_method") or (customer.get("invoice_settings") or {}).get("default_payment_method")
        setup_id = subscription.get("pending_setup_intent")
        readiness, kind = C.PaymentMethodReadiness.UNKNOWN, C.RecurringAuthorizationKind.UNKNOWN
        method = None
        if method_id:
            method = self._object("payment_method", _identifier(method_id))
            if _identifier(method.get("customer")) != request.customer.opaque_id:
                _conflict()
            if method.get("type") != "card":
                _unsupported()
            readiness = C.PaymentMethodReadiness.ATTACHED
        if setup_id:
            setup = self._object("setup_intent", _identifier(setup_id))
            source, kind = self._ref(setup["id"]), C.RecurringAuthorizationKind.PAYMENT_METHOD_SETUP
            if _identifier(setup.get("customer")) != request.customer.opaque_id:
                _conflict()
            status = setup.get("status")
            if status in ("requires_action", "requires_confirmation", "processing", "requires_payment_method"):
                readiness = C.PaymentMethodReadiness.PENDING_SETUP
            elif status == "canceled":
                readiness = C.PaymentMethodReadiness.REJECTED
            elif status == "succeeded":
                if setup.get("usage") != "off_session" or method is None:
                    readiness = C.PaymentMethodReadiness.UNKNOWN
                elif _identifier(setup.get("payment_method")) != method["id"]:
                    _conflict()
                else:
                    readiness = C.PaymentMethodReadiness.REUSABLE_AUTHORITY_CONFIRMED
            else:
                _unsupported()
        authority = C.RecurringAuthorizationEvidence(request.customer, source, kind, readiness)
        method_evidence = C.PaymentMethodEvidence(request.customer, source,
            C._observation_time(self._clock()), readiness, self._ref(method["id"]) if method else None)
        return method_evidence, authority

    def _settlement(self, request, subscription, terms):
        latest = subscription.get("latest_invoice")
        if latest is None:
            return None
        invoice = self._object("invoice", _identifier(latest))
        invoice_parent = _only(invoice.get("parent"), ("type", "subscription_details", "quote_details"))
        if invoice_parent.get("type") not in (None, "subscription_details") or invoice_parent.get("quote_details") is not None:
            _unsupported()
        parent = _only(invoice_parent.get("subscription_details"), ("subscription", "metadata", "subscription_proration_date"))
        if parent.get("subscription_proration_date") is not None:
            _unsupported()
        linked = _consistent(_identifier, parent.get("subscription"), invoice.get("subscription"))
        if (_identifier(linked) != subscription["id"]
                or _identifier(invoice.get("customer")) != request.customer.opaque_id):
            _conflict()
        _no_adjustments(invoice)
        # No second invoice-purpose/coverage representation is supported by this
        # API subset. Reject it instead of silently trusting billing_reason.
        if any(invoice.get(k) is not None for k in ("purpose", "initial_subscription_invoice", "coverage")):
            _unsupported()
        if invoice.get("currency", "").upper() != terms.amount.currency:
            _conflict()
        purpose = {"subscription_create": C.SettlementPurpose.INITIAL_SUBSCRIPTION,
                   "subscription_cycle": C.SettlementPurpose.RENEWAL,
                   "subscription_update": C.SettlementPurpose.ADJUSTMENT}.get(invoice.get("billing_reason"))
        if purpose is None:
            _unsupported()
        if invoice.get("status") not in ("paid", "open", "draft", "void", "uncollectible"):
            _unsupported()
        paid = invoice["status"] == "paid"
        if invoice.get("paid") is not None and _boolean(invoice["paid"]) is not paid:
            _conflict()
        if type(invoice.get("amount_remaining")) is not int or invoice["amount_remaining"] < 0:
            _unavailable()
        if (invoice.get("issuer") or {}).get("type", "self") != "self":
            _unsupported()
        if paid and (invoice["amount_remaining"] != 0 or invoice.get("paid_out_of_band") is True):
            _unsupported()
        coverage = []
        for line in _list(self._get("invoice_lines", invoice["id"])):
            coverage.append(self._invoice_line(line, invoice, subscription, terms))
        if not coverage:
            _unavailable()
        return C.ObservedSettlement(self._ref(invoice["id"]), request.customer, self._ref(subscription["id"]),
            _money(invoice.get("amount_paid"), invoice.get("currency")),
            C.PaymentState.PAID if paid else C.PaymentState.UNPAID, paid,
            purpose is C.SettlementPurpose.INITIAL_SUBSCRIPTION,
            _time((invoice.get("status_transitions") or {}).get("paid_at")) if paid else None,
            tuple(coverage), purpose=purpose)

    def _invoice_line(self, line, invoice, subscription, terms):
        # Installed SDK 15.6.1 models modern parent/pricing, quantity_decimal
        # and root subscription. Legacy price/proration remain read-compatible.
        # Extra financial representations (e.g. nested quantity/period/purpose)
        # are unsupported. Never normalize them away into positive evidence.
        _only(line, ("object", "id", "invoice", "currency", "livemode", "parent", "pricing", "price",
            "subscription", "proration", "proration_details", "period", "amount", "subtotal", "quantity",
            "quantity_decimal", "description", "metadata", "discount_amounts", "discountable", "discounts",
            "pretax_credit_amounts", "taxes", "tax_rates", "tax_amounts", "type"))
        parent = _only(line.get("parent"), ("type", "subscription_item_details", "invoice_item_details"))
        if parent.get("type") not in (None, "subscription_item_details") or parent.get("invoice_item_details") is not None:
            _unsupported()
        details = _only(parent.get("subscription_item_details"),
            ("subscription", "subscription_item", "invoice_item", "proration", "proration_details"))
        pricing = _only(line.get("pricing"), ("type", "price_details", "unit_amount_decimal"))
        if pricing.get("type") not in (None, "price_details") or line.get("type") not in (None, "subscription"):
            _unsupported()
        prices = _only(pricing.get("price_details"), ("price", "product"))
        modern_price, legacy_price = prices.get("price"), line.get("price")
        linked_sub = _consistent(_identifier, details.get("subscription"), line.get("subscription"))
        linked_price = _consistent(_identifier, modern_price, legacy_price)
        proration = _consistent(_boolean, details.get("proration"), line.get("proration"))
        for extra in (details.get("proration_details"), line.get("proration_details")):
            if extra is not None:
                extra = _only(extra, ("credited_items",))
                if extra.get("credited_items") is not None:
                    _unsupported()
        if (linked_sub != subscription["id"] or linked_price != terms.price.opaque_id
                or line.get("object") != "line_item"
                or line.get("livemode") is not (self.binding.environment is C.GatewayEnvironment.LIVE)
                or line.get("currency", "").upper() != terms.amount.currency
                or line.get("invoice") not in (None, invoice["id"])):
            _conflict()
        if proration or line.get("pretax_credit_amounts"):
            _unsupported()
        _no_adjustments(line)
        quantity = _consistent(_decimal, line.get("quantity"), line.get("quantity_decimal"))
        if quantity != quantity.to_integral_value():
            _unsupported()  # Fractional quantities are outside the approved subset.
        if quantity != terms.quantity:
            _conflict()
        # amount and subtotal coincide only in this no-tax/no-discount subset.
        _money(line.get("amount"), line.get("currency"))
        _consistent(_decimal, line.get("amount"), line.get("subtotal"))
        units = [pricing.get("unit_amount_decimal")]
        for price in (modern_price, legacy_price):
            if type(price) is dict:
                self._price_claims(price, terms)
                units.extend((price.get("unit_amount_decimal"), price.get("unit_amount")))
        if any(value is not None for value in units):
            if _consistent(_decimal, *units) != terms.amount.amount * 100:
                _conflict()
        period = _only(line.get("period"), ("start", "end"))
        return (_time(period.get("start")), _time(period.get("end")))

    def _price_claims(self, price, terms):
        if type(price) is not dict:
            return  # Bare reference already checked against the authoritative ID.
        _only(price, ("id", "object", "active", "created", "currency", "livemode", "lookup_key", "metadata",
            "nickname", "product", "recurring", "billing_scheme", "type", "unit_amount", "unit_amount_decimal",
            "tax_behavior", "currency_options", "custom_unit_amount", "tiers", "tiers_mode", "transform_quantity"))
        if _identifier(price) != terms.price.opaque_id:
            _conflict()
        if (price.get("object") not in (None, "price")
                or price.get("currency") is not None and price["currency"].upper() != terms.amount.currency
                or price.get("livemode") is not None and price["livemode"] is not (self.binding.environment is C.GatewayEnvironment.LIVE)
                or price.get("type") not in (None, "recurring")
                or price.get("billing_scheme") not in (None, "per_unit")):
            _conflict()
        if (any(price.get(key) is not None for key in ("currency_options", "custom_unit_amount", "tiers", "tiers_mode", "transform_quantity"))
                or price.get("tax_behavior") not in (None, "unspecified")):
            _unsupported()
        units = [price.get("unit_amount"), price.get("unit_amount_decimal")]
        if any(value is not None for value in units) and _consistent(_decimal, *units) != terms.amount.amount * 100:
            _conflict()
        if price.get("recurring") is not None:
            recurring = _only(price["recurring"], ("interval", "interval_count", "usage_type", "meter", "trial_period_days", "aggregate_usage"))
            interval, count = recurring.get("interval"), recurring.get("interval_count")
            if interval not in ("month", "year") or type(count) is not int or count <= 0:
                _unavailable()
            if (count * (12 if interval == "year" else 1) != terms.interval_months
                    or recurring.get("usage_type") != "licensed"):
                _conflict()
            if any(recurring.get(key) is not None for key in ("meter", "trial_period_days", "aggregate_usage")):
                _unsupported()

    def _observe(self, request, trial):
        expected_type = C.TrialObservationRequest if trial else C.SubscriptionObservationRequest
        C._observation_type(request, expected_type)
        outcome, facts, capabilities = C.VerificationOutcome.UNAVAILABLE, {}, C.GatewayCapabilities()
        source = request.checkout if trial else request.subscription
        try:
            if request.binding != self.binding:
                _conflict()
            self._namespace()
            capabilities = C.GatewayCapabilities(authoritative_reconciliation=C.CapabilityState.SUPPORTED)
            customer = self._customer(request)
            if trial:
                session = self._object("checkout", request.checkout.opaque_id)
                if session.get("mode") != "subscription" or _identifier(session.get("customer")) != request.customer.opaque_id:
                    _conflict()
                status = {"open": C.CheckoutState.OPEN, "complete": C.CheckoutState.COMPLETE,
                          "expired": C.CheckoutState.EXPIRED}.get(session.get("status"))
                if status is None:
                    _unsupported()
                facts = dict(customer=request.customer, checkout=request.checkout, checkout_state=status)
                if status is not C.CheckoutState.COMPLETE:
                    outcome = C.VerificationOutcome.PENDING if status is C.CheckoutState.OPEN else C.VerificationOutcome.CONFLICT
                    return self._result(request, source, outcome, capabilities, facts)
                if session.get("setup_intent") is not None:
                    _conflict()  # Setup-mode sessions are not subscription Checkout proof.
                subscription_id = _identifier(session.get("subscription"))
            else:
                subscription_id = request.subscription.opaque_id
            subscription, subscription_facts = self._subscription(request, subscription_id)
            facts.update(subscription_facts)
            if trial:
                approved = request.approved_terms
                if (session.get("currency", "").upper() != approved.currency
                        or facts["terms"].amount.currency != approved.currency
                        or facts["terms"].interval_months != approved.interval_months):
                    _conflict()
                _no_adjustments(session)
                if (session.get("total_details") or {}).get("amount_discount", 0) != 0:
                    _unsupported()
                lines = _list(self._get("checkout_lines", session["id"]))
                if len(lines) != 1:
                    _conflict()
                line = lines[0]
                if type(line.get("quantity")) is not int:
                    _unavailable()
                if (_identifier(line.get("price")) != facts["terms"].price.opaque_id
                        or line.get("quantity") != facts["terms"].quantity
                        or line.get("currency", "").upper() != approved.currency):
                    _conflict()
                _no_adjustments(line)
                window = facts.get("trial")
                if window is None:
                    _unavailable()
                if window.ends_at - window.started_at != timedelta(days=approved.trial_duration_days):
                    _conflict()
                method, authority = self._method(request, customer, subscription)
                facts.update(payment_method=method, recurring_authorization=authority)
                # No trusted KEEL agreement/version exists in current Checkout.
                # Provider metadata, consent booleans and $0 invoices cannot fill it.
                outcome = C.VerificationOutcome.PENDING
                if request.expected_terms is None:
                    outcome = C.VerificationOutcome.UNAVAILABLE
                if authority.readiness is C.PaymentMethodReadiness.REJECTED or facts["subscription_state"] in (
                    C.SubscriptionState.CANCELLED, C.SubscriptionState.EXPIRED, C.SubscriptionState.PAYMENT_FAILED
                ):
                    outcome = C.VerificationOutcome.CONFLICT
            else:
                facts["settlement"] = self._settlement(request, subscription, facts["terms"])
                outcome = C.VerificationOutcome.VERIFIED
                if facts["subscription_state"] is C.SubscriptionState.TRIALING and facts.get("trial") is None:
                    outcome = C.VerificationOutcome.PENDING
        except _Failure as error:
            outcome, facts = error.outcome, {}
        except NotImplementedError:
            outcome, facts = C.VerificationOutcome.UNSUPPORTED, {}
        except Exception:
            # Includes auth/permission/404/timeout/malformed replies. Missing is
            # not operation-wide non-creation. No raw error text or PII escapes.
            outcome, facts = C.VerificationOutcome.UNAVAILABLE, {}
        return self._result(request, source, outcome, capabilities, facts)

    def _result(self, request, source, outcome, capabilities, facts):
        api_version = self._api_version
        if type(api_version) is not str or not api_version.strip():
            api_version = "unresolved"
        provenance = C.ObservationProvenance(C.ObservationSource.AUTHORITATIVE_LOOKUP, source,
            C._observation_time(self._clock()), ADAPTER_VERSION, api_version)
        try:
            return C.ProviderVerificationObservation(request, provenance, outcome, capabilities, **facts)
        except (ValueError, TypeError, OverflowError):
            return C.ProviderVerificationObservation(request, provenance, C.VerificationOutcome.UNAVAILABLE, capabilities)

    def observe_trial_checkout(self, request):
        return self._observe(request, True)

    def observe_subscription(self, request):
        return self._observe(request, False)
