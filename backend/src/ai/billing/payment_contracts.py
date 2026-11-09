"""External subscription-payment capabilities, independent of SDKs and persistence.

Callers own authorization, commercial decisions, locks, durable attempts and
transactions. A provider snapshot or verified notification never grants rights.
"""
from dataclasses import dataclass, field, fields
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Callable, Mapping, Protocol
import json


class GatewayEnvironment(str, Enum):
    TEST = "test"
    LIVE = "live"


@dataclass(frozen=True)
class GatewayBinding:
    """Stable, non-secret identity; not a credential or a runtime selector."""
    provider: str
    environment: GatewayEnvironment
    merchant_account_id: str
    binding_id: str

    def __post_init__(self):
        for value in (self.provider, self.merchant_account_id, self.binding_id):
            if not isinstance(value, str) or not value.strip() or value != value.strip():
                raise ValueError("Explicit provider, merchant account and binding identifiers are required")
        if not isinstance(self.environment, GatewayEnvironment):
            raise ValueError("An explicit gateway environment is required")


class CapabilityState(str, Enum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"
    REQUIRES_APPROVAL = "requires_approval"


@dataclass(frozen=True)
class GatewayCapabilities:
    """Minimum card-backed recurring-trial requirements, unknown by default.

    Declarations are necessary, not authorization or proof of merchant/currency
    eligibility. Every requirement must be explicitly supported. This contract
    is not consulted by the existing Stripe runtime in this phase.
    """
    hosted_checkout: CapabilityState = CapabilityState.UNKNOWN
    reusable_payment_method: CapabilityState = CapabilityState.UNKNOWN
    setup_without_charge: CapabilityState = CapabilityState.UNKNOWN
    off_session_recurring: CapabilityState = CapabilityState.UNKNOWN
    trial_subscription_setup: CapabilityState = CapabilityState.UNKNOWN
    authenticated_webhooks: CapabilityState = CapabilityState.UNKNOWN
    authoritative_reconciliation: CapabilityState = CapabilityState.UNKNOWN
    idempotent_submission: CapabilityState = CapabilityState.UNKNOWN
    cancellation: CapabilityState = CapabilityState.UNKNOWN

    def __post_init__(self):
        if any(not isinstance(getattr(self, item.name), CapabilityState) for item in fields(self)):
            raise ValueError("Capabilities require explicit capability states")

    def supports_card_backed_trial(self) -> bool:
        return all(getattr(self, item.name) is CapabilityState.SUPPORTED for item in fields(self))


@dataclass(frozen=True)
class ProviderReference:
    """An opaque object identity, optionally qualified by its durable binding.

    None preserves legacy Stripe callers; it means unscoped, never an inferred
    account or TEST environment. Scoped references require a binding-aware
    resolver before use by an adapter; no current runtime caller emits them.
    """
    provider: str
    opaque_id: str
    binding: GatewayBinding | None = field(default=None, kw_only=True)

    def __post_init__(self):
        if (not isinstance(self.provider, str) or not isinstance(self.opaque_id, str)
                or not self.provider.strip() or not self.opaque_id.strip()):
            raise ValueError("Provider and opaque identifier are required")
        if self.binding is not None and (not isinstance(self.binding, GatewayBinding)
                                         or self.binding.provider != self.provider):
            raise ValueError("Reference provider must match its gateway binding")


@dataclass(frozen=True)
class Money:
    amount: Decimal
    currency: str

    def __post_init__(self):
        if not isinstance(self.amount, Decimal) or not self.amount.is_finite() or self.amount < 0:
            raise ValueError("Money requires a finite nonnegative Decimal")
        if (not isinstance(self.currency, str) or len(self.currency) != 3
                or not self.currency.isascii() or not self.currency.isalpha()):
            raise ValueError("A three-letter currency is required")
        object.__setattr__(self, "currency", self.currency.upper())


def _require_binding(binding: GatewayBinding | None, *references: ProviderReference | None) -> None:
    if not isinstance(binding, GatewayBinding) or any(
        reference is not None and (not isinstance(reference, ProviderReference) or reference.binding != binding)
        for reference in references
    ):
        raise ValueError("Evidence references require the same explicit gateway binding")


def _require_aware_time(value: datetime) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Evidence timestamps must include a timezone")


@dataclass(frozen=True)
class ApprovedTrialTerms:
    """Frozen KEEL-approved inputs, not an eligibility decision or price engine.

    Catalog revision identifies the approved commercial terms. Persistence must
    preserve that revision and enforce tenant ownership before future use.
    """
    tenant_id: str
    plan_key: str
    catalog_revision_id: str
    interval_months: int
    currency: str
    trial_duration_days: int
    binding: GatewayBinding

    def __post_init__(self):
        for value in (self.tenant_id, self.plan_key, self.catalog_revision_id):
            if not isinstance(value, str) or not value.strip() or value != value.strip():
                raise ValueError("Tenant, plan and catalog revision are required")
        if (type(self.interval_months) is not int or self.interval_months <= 0
                or type(self.trial_duration_days) is not int or self.trial_duration_days <= 0):
            raise ValueError("Positive approved interval and trial duration are required")
        if (not isinstance(self.currency, str) or len(self.currency) != 3
                or not self.currency.isascii() or not self.currency.isalpha()):
            raise ValueError("A three-letter currency is required")
        object.__setattr__(self, "currency", self.currency.upper())
        _require_binding(self.binding)


class PaymentMethodReadiness(str, Enum):
    ATTACHED = "attached"
    PENDING_SETUP = "pending_setup"
    REUSABLE_AUTHORITY_CONFIRMED = "reusable_authority_confirmed"
    REJECTED = "rejected"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class PaymentMethodEvidence:
    """Adapter-observed readiness with scoped provenance, never access authority.

    Source identifies the setup, mandate or reconciled provider object used to
    establish readiness. Callers must still verify trusted provenance and match
    the reservation, tenant and approved recurring terms before granting rights.
    """
    customer: ProviderReference
    source: ProviderReference
    observed_at: datetime
    readiness: PaymentMethodReadiness = PaymentMethodReadiness.UNKNOWN
    payment_method: ProviderReference | None = None

    def __post_init__(self):
        if not isinstance(self.customer, ProviderReference) or not isinstance(self.source, ProviderReference):
            raise ValueError("Customer and readiness source references are required")
        _require_binding(self.customer.binding, self.source, self.payment_method)
        _require_aware_time(self.observed_at)
        if not isinstance(self.readiness, PaymentMethodReadiness):
            raise ValueError("An explicit payment-method readiness state is required")
        if self.readiness is PaymentMethodReadiness.REUSABLE_AUTHORITY_CONFIRMED and self.payment_method is None:
            raise ValueError("Confirmed reusable authority requires a payment-method reference")


class ProviderOperationOutcome(str, Enum):
    SUCCESS = "success"
    REJECTED = "rejected"
    OUTCOME_UNKNOWN = "outcome_unknown"
    UNAVAILABLE = "unavailable"
    NOT_FOUND = "not_found"
    UNSUPPORTED_CAPABILITY = "unsupported_capability"


class PaymentProviderError(Exception):
    """Stable failure classification; deliberately contains no provider error body."""

    def __init__(self, outcome: ProviderOperationOutcome, *, reason: str | None = None):
        super().__init__(outcome.value)
        self.outcome = outcome
        self.reason = reason


class InvalidPaymentWebhook(ValueError):
    """No verified event may be emitted for an invalid signature or payload."""


class CheckoutState(str, Enum):
    OPEN = "open"
    COMPLETE = "complete"
    EXPIRED = "expired"
    UNKNOWN = "unknown"


class PaymentState(str, Enum):
    PAID = "paid"
    NOT_REQUIRED = "not_required"
    UNPAID = "unpaid"
    UNKNOWN = "unknown"


class SubscriptionState(str, Enum):
    TRIALING = "trialing"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    PENDING = "pending"
    PAYMENT_FAILED = "payment_failed"
    PAUSED = "paused"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class CheckoutIntent:
    """Already approved terms; this layer never selects a plan, price or trial.

    Exactly one of a catalog price reference and an inline recurring amount is
    supplied. Amount/FX provenance remains in KEEL's frozen quote, not here.
    The optional {checkout_reference} return-URL token is encoded by the adapter.
    """
    customer: ProviderReference
    idempotency_key: str
    client_reference: str
    success_url: str
    cancel_url: str
    metadata: Mapping[str, str]
    subscription_metadata: Mapping[str, str]
    price: ProviderReference | None = None
    recurring_amount: Money | None = None
    interval_months: int = 1
    product_name: str | None = None
    trial_end: datetime | None = None
    promotion: ProviderReference | None = None
    allow_promotion_entry: bool = True
    automatic_tax: bool = False

    def __post_init__(self):
        if (self.price is None) == (self.recurring_amount is None):
            raise ValueError("Supply a catalog price or a frozen recurring amount")
        if not self.idempotency_key or not self.client_reference:
            raise ValueError("Durable retry and client references are required")
        if type(self.interval_months) is not int or self.interval_months <= 0:
            raise ValueError("A positive monthly interval is required")
        if self.recurring_amount is not None and not self.product_name:
            raise ValueError("Inline recurring terms require a product name")


@dataclass(frozen=True)
class FrozenCheckoutRequest:
    """Opaque transport evidence, persisted before sending and never rebuilt.

    Only the matching adapter interprets payload. Persistence preserves its
    original shape for compatibility with already frozen Checkout attempts.
    """
    provider: str
    idempotency_key: str
    payload: Mapping


@dataclass(frozen=True)
class CheckoutSnapshot:
    reference: ProviderReference
    state: CheckoutState
    payment_state: PaymentState
    customer: ProviderReference | None = None
    subscription: ProviderReference | None = None
    url: str | None = None
    client_reference: str | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)
    is_subscription: bool = False
    invoice: ProviderReference | None = None


@dataclass(frozen=True)
class SubscriptionItem:
    reference: ProviderReference
    price: ProviderReference
    quantity: int


@dataclass(frozen=True)
class SubscriptionSnapshot:
    reference: ProviderReference
    customer: ProviderReference
    state: SubscriptionState
    items: tuple[SubscriptionItem, ...]
    period_start: datetime | None
    period_end: datetime | None
    trial_end: datetime | None
    cancel_at_period_end: bool
    cancelled_at: datetime | None
    schedule: ProviderReference | None = None
    latest_invoice: ProviderReference | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)
    # Missing evidence is unknown, never implicit reusable authority. These
    # fields are not populated or used for activation by the current runtime.
    trial_start: datetime | None = field(default=None, kw_only=True)
    payment_method_evidence: PaymentMethodEvidence | None = field(default=None, kw_only=True)

    def __post_init__(self):
        if self.trial_start is not None:
            _require_aware_time(self.trial_start)
        if self.payment_method_evidence is not None:
            evidence = self.payment_method_evidence
            if (not isinstance(evidence, PaymentMethodEvidence) or evidence.customer != self.customer
                    or not isinstance(self.reference, ProviderReference)):
                raise ValueError("Payment-method evidence must match the subscription customer and reference")
            _require_binding(evidence.customer.binding, self.reference, self.customer)


@dataclass(frozen=True)
class InvoiceSnapshot:
    reference: ProviderReference
    customer: ProviderReference | None
    subscription: ProviderReference | None
    payment_state: PaymentState
    amount_paid: Money
    amount_due: Money
    paid_at: datetime | None
    initial_subscription_invoice: bool | None
    coverage: tuple[tuple[datetime | None, datetime | None], ...]
    payment_url: str | None = None
    document_url: str | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)
    tenant_hint: str | None = None
    failure_reason: str | None = None
    # Preserve the stricter explicit-settled-state predicate used for the first
    # post-trial period, separately from legacy provider paid-flag support.
    settlement_confirmed: bool = False
    currency_explicit: bool = False


@dataclass(frozen=True)
class SubscriptionChangeIntent:
    """An approved immediate or scheduled change; direction is decided by KEEL."""
    subscription: ProviderReference
    price: ProviderReference
    trial_end: datetime | None = None


@dataclass(frozen=True)
class SubscriptionChangeResult:
    subscription: SubscriptionSnapshot
    payment_required: bool
    payment_url: str | None = None


@dataclass(frozen=True)
class ScheduledChange:
    schedule: ProviderReference
    effective_at: datetime


class PaymentEventKind(str, Enum):
    CHECKOUT_COMPLETED = "checkout_completed"
    CHECKOUT_EXPIRED = "checkout_expired"
    SUBSCRIPTION_CHANGED = "subscription_changed"
    INVOICE_SETTLED = "invoice_settled"
    INVOICE_FAILED = "invoice_failed"
    SCHEDULE_ENDED = "schedule_ended"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class VerifiedPaymentEvent:
    """Authenticated notification, not a payment/tenant authorization decision.

    Keep raw evidence unchanged for the existing event-scoped SQL guards. The
    reconciler must still retrieve current provider state under its own locks.
    """
    provider: str
    event_id: str
    kind: PaymentEventKind
    occurred_at: datetime
    customer: ProviderReference | None
    subscription: ProviderReference | None
    checkout: ProviderReference | None
    invoice: ProviderReference | None
    schedule: ProviderReference | None
    raw_payload: bytes
    raw_evidence: Mapping
    checkout_snapshot: CheckoutSnapshot | None = None
    # Legacy events remain unscoped; no default account or environment is inferred.
    binding: GatewayBinding | None = field(default=None, kw_only=True)

    def __post_init__(self):
        if self.binding is not None:
            if not isinstance(self.binding, GatewayBinding) or self.provider != self.binding.provider:
                raise ValueError("Event provider must match its gateway binding")
            _require_binding(self.binding, self.customer, self.subscription, self.checkout, self.invoice, self.schedule)
            if self.checkout_snapshot is not None:
                snapshot = self.checkout_snapshot
                _require_binding(self.binding, snapshot.reference, snapshot.customer, snapshot.subscription, snapshot.invoice)


class SubscriptionPaymentGateway(Protocol):
    """No transaction ownership; failures raise PaymentProviderError.

    Scheduling means the existing term's end (or the explicitly supplied
    preserved trial cutoff). Callers approve timing and direction beforehand.
    """
    provider: str

    def customer_time(self, customer: ProviderReference, *, tenant_reference: str,
                      require_clock: bool = False) -> datetime | None: ...
    def create_customer(self, *, email: str, company_name: str, tenant_reference: str,
                        idempotency_key: str) -> ProviderReference: ...
    def list_customer_subscriptions(self, customer: ProviderReference) -> tuple[SubscriptionSnapshot, ...]: ...
    def list_open_checkouts(self, customer: ProviderReference) -> tuple[CheckoutSnapshot, ...]: ...
    def create_checkout(self, intent: CheckoutIntent) -> CheckoutSnapshot: ...
    def prepare_checkout(self, intent: CheckoutIntent) -> FrozenCheckoutRequest: ...
    def submit_checkout(self, request: FrozenCheckoutRequest) -> CheckoutSnapshot: ...
    def get_checkout(self, reference: ProviderReference) -> CheckoutSnapshot: ...
    def expire_checkout(self, reference: ProviderReference) -> CheckoutSnapshot: ...
    def get_subscription(self, reference: ProviderReference) -> SubscriptionSnapshot: ...
    def change_subscription(self, intent: SubscriptionChangeIntent, *,
                            current: SubscriptionSnapshot | None = None,
                            resolve_payment_url: bool = True) -> SubscriptionChangeResult: ...
    def schedule_change(self, intent: SubscriptionChangeIntent, *, now: datetime,
                        current: SubscriptionSnapshot | None = None) -> ScheduledChange: ...
    def cancel_scheduled_change(self, schedule: ProviderReference) -> ProviderOperationOutcome: ...
    def set_cancellation(self, subscription: ProviderReference, *, cancel_at_period_end: bool) -> SubscriptionSnapshot: ...
    def get_invoice(self, reference: ProviderReference) -> InvoiceSnapshot: ...
    def create_portal(self, customer: ProviderReference, *, return_url: str) -> str: ...


class PaymentWebhookDecoder(Protocol):
    def decode(self, payload: bytes, signature: str) -> VerifiedPaymentEvent: ...


@dataclass(frozen=True)
class CustomerPayload:
    """Canonical UTF-8 JSON, not a shallowly frozen dictionary. Never log it."""
    canonical: bytes = field(repr=False)

    def __post_init__(self):
        if type(self.canonical) is not bytes:
            raise ValueError("Immutable canonical bytes required")
        value = json.loads(self.canonical)
        def check(item):
            if isinstance(item, dict):
                for key, child in item.items():
                    if key.lower().replace("-", "_") in {
                        "api_key", "authorization", "password", "secret", "client_secret",
                        "access_token", "refresh_token", "headers", "card", "cvc", "cvv", "pan",
                    }:
                        raise ValueError("Secret/card fields are forbidden")
                    check(child)
            elif isinstance(item, list):
                for child in item:
                    check(child)
        check(value)
        if not isinstance(value, dict) or self._encode(value) != self.canonical:
            raise ValueError("Canonical JSON object required")

    @staticmethod
    def _encode(value):
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")

    @classmethod
    def freeze(cls, value: Mapping):
        return cls(cls._encode(value))

    def unpack(self) -> dict:
        return json.loads(self.canonical)  # Every caller gets its own deep copy.


@dataclass(frozen=True)
class CustomerIntent:
    tenant_id: str
    operation_id: str
    request_identity: str
    binding: GatewayBinding
    email: str = field(repr=False)
    company_name: str = field(repr=False)

    def __post_init__(self):
        _require_binding(self.binding)
        if any(not isinstance(v, str) or not v.strip() for v in (
            self.tenant_id, self.operation_id, self.request_identity, self.email, self.company_name
        )):
            raise ValueError("Explicit Customer intent identity required")

    def logical_request(self) -> CustomerPayload:
        return CustomerPayload.freeze({"email": self.email, "name": self.company_name})


@dataclass(frozen=True)
class FrozenCustomerRequest:
    tenant_id: str
    operation_id: str
    binding: GatewayBinding
    idempotency_key: str
    logical: CustomerPayload = field(repr=False)
    transport: CustomerPayload = field(repr=False)
    encoder_version: str
    api_version: str
    replay_support: CapabilityState = CapabilityState.UNKNOWN
    replay_window_seconds: int = 0
    dispatch_timeout_seconds: int = 5

    def __post_init__(self):
        _require_binding(self.binding)
        if not all(isinstance(v, str) and v.strip() for v in (
            self.tenant_id, self.operation_id, self.idempotency_key, self.encoder_version, self.api_version
        )) or not isinstance(self.logical, CustomerPayload) or not isinstance(self.transport, CustomerPayload):
            raise ValueError("Complete immutable Customer request required")
        if (not isinstance(self.replay_support, CapabilityState)
            or type(self.replay_window_seconds) is not int or self.replay_window_seconds < 0
            or type(self.dispatch_timeout_seconds) is not int or self.dispatch_timeout_seconds <= 0):
            raise ValueError("Explicit replay and dispatch policy required")


@dataclass(frozen=True)
class CustomerSnapshot:
    reference: ProviderReference
    tenant_id: str
    operation_id: str
    evidence_kind: str
    evidence_id: str
    deleted: bool = False

    def __post_init__(self):
        _require_binding(self.reference.binding, self.reference)
        if self.evidence_kind not in {"create_response", "retrieved", "recovered"} or not self.evidence_id:
            raise ValueError("Customer provenance required")


class CustomerRecoveryStatus(str, Enum):
    MATCH = "match"
    INCONCLUSIVE = "inconclusive"
    CONFLICT = "conflict"
    VERIFIED_NON_CREATION = "verified_non_creation"


@dataclass(frozen=True)
class CustomerRecoveryResult:
    status: CustomerRecoveryStatus
    binding: GatewayBinding
    tenant_id: str
    operation_id: str
    snapshot: CustomerSnapshot | None = None
    evidence_id: str | None = None

    def __post_init__(self):
        _require_binding(self.binding)
        if not isinstance(self.status, CustomerRecoveryStatus):
            raise ValueError("Explicit recovery status required")
        if (self.status is CustomerRecoveryStatus.MATCH) != (self.snapshot is not None):
            raise ValueError("A match requires exactly one snapshot")
        if self.snapshot is not None and (
            self.snapshot.reference.binding != self.binding or self.snapshot.tenant_id != self.tenant_id
            or self.snapshot.operation_id != self.operation_id or self.snapshot.deleted
        ):
            raise ValueError("Recovery association mismatch")
        if self.status is CustomerRecoveryStatus.VERIFIED_NON_CREATION and not self.evidence_id:
            raise ValueError("Operation-wide non-creation evidence required")


class DurableCustomerGateway(Protocol):
    """Optional capability, intentionally separate from SubscriptionPaymentGateway.

    Only trusted server adapters implement this boundary. Snapshots are evidence,
    not entitlement authority. Unknown replay guarantees must fail closed.
    """
    binding: GatewayBinding
    def prepare_customer(self, intent: CustomerIntent) -> FrozenCustomerRequest: ...
    def submit_customer(self, request: FrozenCustomerRequest, *, deadline: datetime,
                        authorize: Callable[[], Mapping]) -> CustomerSnapshot: ...
    def retrieve_customer(self, reference: ProviderReference, request: FrozenCustomerRequest) -> CustomerSnapshot: ...
    def recover_customer(self, request: FrozenCustomerRequest) -> CustomerRecoveryResult: ...
