"""External subscription-payment capabilities, independent of SDKs and persistence.

Callers own authorization, commercial decisions, locks, durable attempts and
transactions. A provider snapshot or verified notification never grants rights.
"""
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Mapping, Protocol


@dataclass(frozen=True)
class ProviderReference:
    provider: str
    opaque_id: str

    def __post_init__(self):
        if (not isinstance(self.provider, str) or not isinstance(self.opaque_id, str)
                or not self.provider.strip() or not self.opaque_id.strip()):
            raise ValueError("Provider and opaque identifier are required")


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
