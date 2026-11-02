"""
Subscription actions a company takes from Billing: checkout, the Stripe
customer portal, changing plan, cancelling and resuming.

Ported from the reference project's Stripe billing service (read-only reference:
src/modules/subscription/service/subscription.service.ts, plans.service.ts and
client/payment-providers/stripe/stripe.client.ts on the reference project's
`backend` branch). Same rules:
- Checkout is a hosted Stripe Checkout Session in subscription mode with one
  line item; nothing is written locally until Stripe's webhook confirms it.
- Upgrades apply immediately and invoice the difference; a trialing
  subscription keeps its original trial end and isn't charged until then.
- Downgrades take effect at the end of the paid period through a two-phase
  subscription schedule.
- Cancelling sets cancel_at_period_end; access lasts until the period ends.
Closed gaps from that implementation: the stored Stripe customer is reused
(not looked up by email), checkout carries an idempotency key, and a company
with a live subscription can't open a second checkout.
"""
import hashlib
from datetime import datetime, timezone
import time
from decimal import Decimal, InvalidOperation
from src.ai.billing import checkout_attempts, config, promotions, store, test_clock, self_service, trial_checkouts
from src.ai.billing.payment_contracts import (
    CheckoutIntent, CheckoutState, FrozenCheckoutRequest, Money, PaymentProviderError,
    PaymentState, ProviderOperationOutcome, ProviderReference,
    SubscriptionChangeIntent, SubscriptionPaymentGateway, SubscriptionSnapshot, SubscriptionState,
)
from src.ai.billing.stripe_gateway import StripeGateway
from src.ai.billing.stripe_api import PaymentsNotConfigured
from src.ai.core import usage


class BillingError(Exception):
    """A request Billing can't fulfil, with an HTTP status and a stable code."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def payment_gateway() -> SubscriptionPaymentGateway:
    """Explicit launch-provider composition; existing DB references are Stripe's.

    No runtime provider selection or persistence migration in this phase.
    Tests can substitute the same small contract at this boundary.
    """
    return StripeGateway()


def _provider_reference(identifier):
    return ProviderReference(payment_gateway().provider, identifier)


def _send_checkout(gateway, intent, sys_conn, attempt, *, quote_revision=None):
    # Never encode a new request over frozen legacy evidence, even if today's
    # catalog, quote or transport encoder has changed since the first attempt.
    if attempt and attempt.get("params") is not None:
        request = FrozenCheckoutRequest(gateway.provider, intent.idempotency_key, attempt["params"])
    else:
        request = gateway.prepare_checkout(intent)
    if attempt:
        try:
            request = checkout_attempts.freeze_payment_request(
                sys_conn, attempt, request, quote_revision=quote_revision)
        except checkout_attempts.FrozenCheckoutConflict as error:
            raise BillingError(409, "checkout_pending", str(error)) from None
    return gateway.submit_checkout(request)


def _require_payments():
    if not config.payments_enabled():
        raise BillingError(
            503, "payments_not_configured",
            "Online payment isn't set up on this server yet. Contact us to change your plan.",
        )


def _price_or_error(conn, plan_key: str, period_code: str) -> dict:
    price = store.current_price(conn, plan_key, period_code)
    if not price or not price["is_active"]:
        raise BillingError(404, "plan_not_available", "This plan or billing period isn't available.")
    if not price["self_serve"]:
        raise BillingError(400, "contact_sales", "This plan is arranged with our team, not bought online.")
    if not price["stripe_price_id"]:
        raise BillingError(503, "price_not_synced", "This plan can't be bought online yet. Please contact us.")
    return price


def _ensure_customer(conn, sys_conn, tenant_id: str, email: str, company_name: str) -> str:
    existing = store.customer_id(conn, tenant_id)
    if existing:
        payment_gateway().customer_time(_provider_reference(existing), tenant_reference=tenant_id, require_clock=True)
        return existing
    customer = payment_gateway().create_customer(email=email, company_name=company_name,
        tenant_reference=tenant_id, idempotency_key=f"apex-customer-{tenant_id}")
    store.save_customer(sys_conn, tenant_id, customer.opaque_id)
    sys_conn.commit()
    return customer.opaque_id


def _check_clock_customer(conn, tenant_id):
    if test_clock.adapter() is not None:
        customer = store.customer_id(conn, tenant_id)
        if customer:
            payment_gateway().customer_time(_provider_reference(customer), tenant_reference=tenant_id, require_clock=True)


def _check_legacy_provider_contracts(conn,sys_conn,tenant_id,attempt):
    if attempt:
        return
    customer_id=store.customer_id(conn,tenant_id)
    if not customer_id:
        return
    gateway = payment_gateway()
    remote = gateway.list_customer_subscriptions(_provider_reference(customer_id))
    if any(item.state in (SubscriptionState.ACTIVE, SubscriptionState.TRIALING, SubscriptionState.PAST_DUE,
                          SubscriptionState.PAYMENT_FAILED, SubscriptionState.PENDING, SubscriptionState.PAUSED) for item in remote):
        raise BillingError(409,'checkout_reconciling','Stripe already has a current subscription. Wait for billing reconciliation; do not pay again.')
    pending = [item for item in gateway.list_open_checkouts(_provider_reference(customer_id)) if item.is_subscription]
    if len(pending)>1:
        raise BillingError(409,'checkout_reconciling','Several earlier Checkouts need billing review before another purchase.')
    if pending:
        metadata = pending[0].metadata
        adopted=checkout_attempts.reserve(sys_conn,tenant_id,'legacy:'+pending[0].reference.opaque_id,metadata.get('plan_key','legacy_unknown'),metadata.get('period_code','legacy_unknown'))
        checkout_attempts.opened(sys_conn, adopted, {'id': pending[0].reference.opaque_id})
        raise BillingError(409,'checkout_pending','An earlier Checkout is still open. Close it before selecting a new contract.')


def create_checkout(conn, sys_conn, tenant_id: str, email: str, company_name: str,
                    plan_key: str, period_code: str, promotion_code: str | None = None,
                    actor_user_id: str | None = None, *, trial_requested: bool = False) -> dict:
    _require_payments()
    try:
        origin = config.app_base_url()
    except ValueError as exc:
        raise BillingError(503, 'frontend_origin_not_configured', str(exc)) from None
    if store.current_subscription(conn, tenant_id):
        raise BillingError(409, 'subscription_exists', 'Your company already has a subscription. Use Change Plan or payment recovery.')
    _price_or_error(conn, plan_key, period_code)
    request_key = hashlib.sha256(f'{plan_key}:{period_code}:{(promotion_code or "").strip().upper()}:{origin}'.encode()).hexdigest()
    trial_request_key = hashlib.sha256((request_key + ':selected-plan-trial').encode()).hexdigest()
    # The generic Continue action may resume an already authorized trial
    # Checkout. Starting a trial must never resume a paid/no-trial Checkout.
    resume_keys = {request_key, trial_request_key} if not trial_requested else {trial_request_key}
    if trial_requested:
        request_key = trial_request_key
    with checkout_attempts.tenant_lock(sys_conn, tenant_id):
        _check_clock_customer(conn, tenant_id)
        if store.current_subscription(conn, tenant_id):
            raise BillingError(409, 'subscription_exists', 'Your company already has a subscription. Use its plan-change or recovery action.')
        if store.has_custom_contract(conn, tenant_id):
            raise BillingError(409, 'plan_transition_conflict', 'Review the existing Custom contract before starting another subscription.')
        if trial_requested:
            if not actor_user_id:
                raise BillingError(400,'trial_identity_required','An authenticated trial owner is required.')
            reason=store.trial_eligibility(sys_conn,tenant_id,plan_key,actor_user_id)
            if reason:
                raise BillingError(409,reason,'This plan is not eligible for a new trial. Review your current trial or pending checkout.')
        attempt = checkout_attempts.active(sys_conn, tenant_id)
        _check_legacy_provider_contracts(conn,sys_conn,tenant_id,attempt)
        if attempt and not attempt['session_id'] and attempt['params'] is None and attempt['request_key'] != request_key:
            # No Checkout can have been submitted: the immutable provider
            # request is committed before any submit. The tenant lock excludes
            # an in-flight creator. Retain the expired row as audit evidence.
            checkout_attempts.expire(sys_conn, attempt)
            attempt = None
        if attempt and attempt['session_id']:
            try:
                session = payment_gateway().get_checkout(_provider_reference(attempt['session_id']))
            except PaymentProviderError as error:
                if error.outcome != ProviderOperationOutcome.NOT_FOUND:
                    raise
                session = None  # Definitively absent; transient failures stay reserved.
            if session is None or session.state == CheckoutState.EXPIRED:
                checkout_attempts.expire(sys_conn, attempt)
                attempt = None
            elif session.state == CheckoutState.COMPLETE:
                if store.checkout_subscription_ended(conn, tenant_id, session.subscription.opaque_id if session.subscription else None):
                    checkout_attempts.expire(sys_conn, attempt)
                    attempt = None
                else:
                    raise BillingError(409, 'checkout_reconciling', 'Payment confirmation is being reconciled. Do not start another Checkout.')
            elif attempt['request_key'] in resume_keys and session.state == CheckoutState.OPEN and session.url:
                return {'url': session.url, 'session_id': session.reference.opaque_id}
            else:
                raise BillingError(409, 'checkout_pending', 'Another Checkout is pending. Complete or cancel it before selecting a different contract.')
        if attempt and attempt['request_key'] != request_key:
            raise BillingError(409, 'checkout_pending', 'Another Checkout request is pending. Reconcile it before changing the selection.')
        if attempt and not attempt['session_id'] and time.time()-attempt['created_at'].timestamp()>23*3600:
            raise BillingError(409, 'checkout_reconciling', 'The previous provider request needs reconciliation before it can be retried safely.')
        attempt = attempt or checkout_attempts.reserve(sys_conn, tenant_id, request_key, plan_key, period_code)
        try:
            result = _create_checkout(conn, sys_conn, tenant_id, email, company_name, plan_key, period_code,
                                      promotion_code, actor_user_id, _attempt=attempt, trial_requested=trial_requested)
        except Exception:
            # Failures before prepare/freeze (customer setup, promo validation)
            # cannot leave a provider Checkout behind. Never release a frozen
            # request after a timeout/unknown outcome: retry its original key.
            sys_conn.rollback()
            pending = checkout_attempts.active(sys_conn, tenant_id)
            if pending and str(pending['attempt_id']) == str(attempt['attempt_id']) and not pending['session_id'] and pending['params'] is None:
                checkout_attempts.expire(sys_conn, pending)
            raise
        if result.get('session_id'):
            checkout_attempts.opened(sys_conn, attempt, {'id':result['session_id']})
        return result


def checkout_status(conn, tenant_id: str, session_id: str) -> dict:
    if not session_id.startswith('cs_') or len(session_id)>255:
        raise BillingError(400,'invalid_checkout_session','Invalid Checkout reference.')
    session = payment_gateway().get_checkout(_provider_reference(session_id))
    metadata = session.metadata
    if metadata.get('tenant_id') != tenant_id:
        raise BillingError(404,'checkout_not_found','This Checkout is not available to your company.')
    customer_id = store.customer_id(conn, tenant_id)
    if not customer_id or session.customer != _provider_reference(customer_id):
        raise BillingError(404,'checkout_not_found','This Checkout is not available to your company.')
    sub = store.current_subscription(conn,tenant_id)
    confirmed = bool(sub and session.subscription and sub['stripe_subscription_id'] == session.subscription.opaque_id
                     and sub['status'] in config.ACCESS_STATUSES and session.state == CheckoutState.COMPLETE
                     and session.payment_state in (PaymentState.PAID, PaymentState.NOT_REQUIRED))
    return {'state':'confirmed' if confirmed else 'pending', 'subscription_status':sub['status'] if sub else None}


def checkout_trial_end(trial, now=None):
    """Preserve the issued trial's UTC cutoff, shared with the review DTO.

    start_trial/billing_setup_trial already used usage_plans.trial_days when
    issuing this trial. A later Checkout or plan choice cannot grant that
    duration again. The 48-hour threshold is Checkout's minimum remaining
    window, not a plan's trial length. Integer seconds match provider precision.
    """
    now = time.time() if now is None else now
    return int(trial["ends_at"].timestamp()) if trial and trial["ends_at"].timestamp() > now + 48 * 3600 else None


def _create_checkout(conn, sys_conn, tenant_id: str, email: str, company_name: str,
                    plan_key: str, period_code: str, promotion_code: str | None = None,
                    actor_user_id: str | None = None, _attempt=None, trial_requested: bool = False) -> dict:
    _require_payments()
    if store.current_subscription(conn, tenant_id):
        raise BillingError(409, "subscription_exists", "Your company already has a subscription. Change plan instead.")
    price = _price_or_error(conn, plan_key, period_code)
    promotion = None
    reservation = None
    if promotion_code:
        try:
            promotion = promotions.require_checkout_eligibility(
                conn, tenant_id, promotion_code, plan_key, period_code,
            )
        except promotions.PromotionError as err:
            raise BillingError(err.status, err.code, err.message) from err
    fresh_trial = None
    if trial_requested:
        if not _attempt:
            raise BillingError(409,'trial_checkout_required','A durable subscription checkout is required.')
        try:
            fresh_trial = trial_checkouts.reserve(sys_conn,tenant_id,actor_user_id,_attempt,plan_key,period_code)
        except trial_checkouts.TrialCheckoutError as err:
            raise BillingError(409,str(err),'This trial cannot be started. Review your existing trial or pending checkout.') from err
    customer = _ensure_customer(conn, sys_conn, tenant_id, email, company_name)

    gateway = payment_gateway()
    metadata = {"tenant_id": tenant_id, "plan_key": plan_key, "period_code": period_code}
    if fresh_trial:
        metadata['keel_trial_attempt_id'] = str(_attempt['attempt_id'])
    # A company still inside its free trial keeps those days: billing starts
    # when the trial would have ended. The trial is never granted twice.
    trial = store.trial(conn, tenant_id)
    simulated = gateway.customer_time(_provider_reference(customer), tenant_reference=tenant_id)
    trial_end = checkout_trial_end(trial, now=simulated.timestamp() if simulated else None)

    base = config.app_base_url()
    # Same company, plan and period within ~10 minutes -> the same session,
    # so a double click never opens two checkouts.
    bucket = int(time.time() // 600)
    promotion_id = promotion["promotion_id"] if promotion else "legacy"
    key = hashlib.sha256(f"{tenant_id}:{plan_key}:{period_code}:{promotion_id}:{bucket}".encode()).hexdigest()[:40]
    if _attempt:
        key = str(_attempt["attempt_id"])
    if promotion:
        reservation_key = "checkout:" + key
        try:
            reservation = promotions.reserve(
                sys_conn, tenant_id=tenant_id, actor_user_id=actor_user_id or "",
                code=promotion_code, plan_key=plan_key, period_code=period_code,
                request_key=reservation_key,
            )
            sys_conn.commit()
        except promotions.PromotionError as err:
            sys_conn.rollback()
            raise BillingError(err.status, err.code, err.message) from err
        if reservation.get("session_id"):
            try:
                existing = gateway.get_checkout(_provider_reference(reservation["session_id"]))
            except Exception as err:
                raise BillingError(502, "checkout_reconciliation_required",
                                   "The existing checkout could not be verified. Please try again later.") from err
            if existing.reference.opaque_id != reservation["session_id"] or existing.state != CheckoutState.OPEN or not existing.url:
                raise BillingError(409, "checkout_reconciliation_required",
                                   "The existing checkout is no longer open and needs reconciliation.")
            return {"url": existing.url, "session_id": existing.reference.opaque_id}
        try:
            promotions.begin_checkout_request(
                sys_conn, tenant_id=tenant_id, redemption_id=reservation["redemption_id"],
            )
            sys_conn.commit()
        except promotions.PromotionError as err:
            sys_conn.rollback()
            raise BillingError(err.status, err.code, err.message) from err
        metadata["keel_promotion_redemption_id"] = reservation["redemption_id"]
    try:
        provider_key = f"apex-promo-checkout-{reservation['redemption_id']}" if reservation else f"apex-checkout-{key}"
        intent = CheckoutIntent(
            customer=_provider_reference(customer), price=_provider_reference(price["stripe_price_id"]),
            idempotency_key=provider_key, client_reference=tenant_id,
            metadata=metadata, subscription_metadata=metadata,
            trial_end=datetime.fromtimestamp(trial_end, timezone.utc) if trial_end else None,
            trial_duration_days=fresh_trial['trial_duration_days'] if fresh_trial else None,
            require_payment_method_before_activation=True,
            promotion=_provider_reference(promotion["stripe_promotion_code_id"]) if promotion else None,
            automatic_tax=config.automatic_tax(),
            success_url=f"{base}/billing?checkout=success&session_id={{checkout_reference}}",
            cancel_url=f"{base}/billing?checkout=cancelled",
        )
        session = _send_checkout(gateway, intent, sys_conn, _attempt)
        if _attempt:
            checkout_attempts.opened(sys_conn, _attempt, {'id': session.reference.opaque_id, 'url': session.url})
    except Exception as err:
        rejected = isinstance(err, PaymentProviderError) and err.outcome == ProviderOperationOutcome.REJECTED
        if reservation:
            try:
                outcome = promotions.provider_request_rejected if rejected else promotions.provider_outcome_unknown
                outcome(
                    sys_conn, tenant_id=tenant_id, redemption_id=reservation["redemption_id"],
                )
                sys_conn.commit()
            except Exception:
                sys_conn.rollback()
        if rejected and _attempt:
            checkout_attempts.expire(sys_conn, _attempt)
        raise
    if reservation:
        try:
            promotions.attach_checkout(
                sys_conn, tenant_id=tenant_id, redemption_id=reservation["redemption_id"],
                session_id=session.reference.opaque_id,
            )
            sys_conn.commit()
        except Exception:
            sys_conn.rollback()
            # Stripe created a session, but local identity was not durably
            # attached. Do not issue a second provider action or free the slot.
            try:
                promotions.provider_outcome_unknown(
                    sys_conn, tenant_id=tenant_id, redemption_id=reservation["redemption_id"],
                )
                sys_conn.commit()
            except Exception:
                sys_conn.rollback()
            raise
    return {"url": session.url, "session_id": session.reference.opaque_id}



def create_custom_quote_checkout(conn, sys_conn, tenant_id: str, email: str, company_name: str,
                                quote_id: str, idempotency_key: str) -> dict:
    _require_payments()
    key=f"custom:{quote_id}:{config.app_base_url()}"
    with checkout_attempts.tenant_lock(sys_conn,tenant_id):
        _check_clock_customer(conn, tenant_id)
        if store.current_subscription(conn,tenant_id):
            raise BillingError(409,'subscription_exists','Your company already has a subscription.')
        shared=checkout_attempts.active(sys_conn,tenant_id)
        _check_legacy_provider_contracts(conn,sys_conn,tenant_id,shared)
        if shared and shared['request_key']!=key:
            raise BillingError(409,'checkout_pending','Another fixed or Custom Checkout is pending for your company.')
        if shared and shared['session_id']:
            prior = payment_gateway().get_checkout(_provider_reference(shared['session_id']))
            if prior.state == CheckoutState.COMPLETE:
                raise BillingError(409,'checkout_reconciling','This Custom Checkout is awaiting verified reconciliation.')
            if prior.state == CheckoutState.EXPIRED:
                checkout_attempts.expire(sys_conn,shared)
                raise BillingError(409,'checkout_expired','This Custom Checkout expired. Request a new quote-bound attempt.')
        if shared and not shared['session_id'] and time.time()-shared['created_at'].timestamp()>23*3600:
            raise BillingError(409,'checkout_reconciling','The previous provider request needs reconciliation.')
        # Validate terms before reserving: the existing quote authority owns revision and acceptance checks.
        from src.ai.billing import custom_offers
        prepared=custom_offers.custom_checkout_prepare(conn,quote_id=quote_id,idempotency_key=idempotency_key)
        terms=prepared.get('commercial_terms') or {}
        if terms.get('currency') not in ('USD', 'JOD') or (terms.get('currency') == 'USD' and str(terms.get('billingPeriodMonths')) != '1'):
            raise BillingError(409,'custom_terms_unsupported','This offer has unsupported billing terms.')
        try:
            _, _, period = self_service.checkout_terms(terms)
        except (ValueError, KeyError):
            raise BillingError(409, 'custom_terms_unsupported', 'Frozen Custom payment terms are invalid.') from None
        shared=shared or checkout_attempts.reserve(sys_conn,tenant_id,key,'custom',period)
        return _create_custom_quote_checkout(conn,sys_conn,tenant_id,email,company_name,quote_id,idempotency_key,_shared=shared)


def cancel_pending_checkout(conn,sys_conn,tenant_id):
    with checkout_attempts.tenant_lock(sys_conn,tenant_id):
        attempt=checkout_attempts.active(sys_conn,tenant_id)
        if not attempt:return {'state':'no_pending_checkout'}
        if not attempt['session_id']:
            if attempt['params'] is None:
                checkout_attempts.expire(sys_conn,attempt)
                return {'state':'checkout_cancelled'}
            raise BillingError(409,'checkout_reconciling','The previous provider request must be reconciled first.')
        try:
            session = payment_gateway().get_checkout(_provider_reference(attempt['session_id']))
        except PaymentProviderError as error:
            if error.outcome != ProviderOperationOutcome.NOT_FOUND:
                raise
            checkout_attempts.expire(sys_conn,attempt)
            return {'state':'checkout_cancelled'}
        if session.state == CheckoutState.COMPLETE:
            raise BillingError(409,'checkout_reconciling','Checkout completed; verify the subscription instead of cancelling it.')
        if session.state == CheckoutState.OPEN:
            session = payment_gateway().expire_checkout(_provider_reference(attempt['session_id']))
        if session.state != CheckoutState.EXPIRED:
            raise BillingError(409,'checkout_reconciling','The previous Checkout could not be confirmed closed. Try again after reconciliation.')
        checkout_attempts.expire(sys_conn,attempt)
        return {'state':'checkout_cancelled'}


def _create_custom_quote_checkout(conn, sys_conn, tenant_id: str, email: str, company_name: str,
                                quote_id: str, idempotency_key: str, _shared=None) -> dict:
    """Start a recurring USD Checkout for an accepted, current Custom offer.

    Price, quote revision and customer identity come from the database; the
    caller supplies only the quote ID and retry key. Activation remains owned
    by the signed webhook path.
    """
    _require_payments()
    from src.ai.billing import custom_offers
    if store.current_subscription(conn, tenant_id):
        raise BillingError(409, "subscription_exists", "Your company already has a subscription.")
    prepared = custom_offers.custom_checkout_prepare(
        conn, quote_id=quote_id, idempotency_key=idempotency_key)
    terms = prepared.get("commercial_terms") or {}
    if terms.get("currency") not in ("USD", "JOD") or (terms.get("currency") == "USD" and str(terms.get("billingPeriodMonths")) != "1"):
        raise BillingError(409, "custom_terms_unsupported", "This Custom offer cannot be checked out with the supported billing terms.")
    try:
        amount, months, _period = self_service.checkout_terms(terms)
    except (KeyError, InvalidOperation, ValueError):
        raise BillingError(409, "custom_terms_unpriced", "This Custom offer has no valid approved price.") from None
    if not amount.is_finite() or amount <= 0 or amount != amount.quantize(Decimal("0.01")):
        raise BillingError(409, "custom_terms_unpriced", "This Custom offer has no valid approved price.")
    # The shared reservation freezes this attempt ID in provider parameters.
    # Keep that identity durable if the provider response is uncertain.
    conn.commit()
    customer = _ensure_customer(conn, sys_conn, tenant_id, email, company_name)
    attempt_id = str(prepared["attempt_id"])
    base = config.app_base_url()
    metadata = {
        "tenant_id": tenant_id, "custom_quote_id": quote_id,
        "custom_quote_revision_id": str(prepared["revision_id"]),
        "quote_attempt_id": attempt_id, "billing_kind": "custom_quote",
    }
    intent = CheckoutIntent(
        customer=_provider_reference(customer), recurring_amount=Money(amount, "USD"),
        interval_months=months, product_name="KEEL Custom Plan", client_reference=attempt_id,
        idempotency_key=f"keel-custom-checkout-{attempt_id}",
        metadata=metadata, subscription_metadata=metadata, allow_promotion_entry=False,
        success_url=f"{base}/billing?checkout=success&session_id={{checkout_reference}}",
        cancel_url=f"{base}/billing?checkout=cancelled",
    )
    try:
        session = _send_checkout(payment_gateway(), intent, sys_conn, _shared,
                                 quote_revision=str(prepared["revision_id"]))
        if _shared:
            checkout_attempts.opened(sys_conn, _shared, {'id': session.reference.opaque_id})
        custom_offers.record_custom_checkout_session(conn, attempt_id=attempt_id, session_id=session.reference.opaque_id)
    except Exception:
        # The prepared attempt remains durable. Repeating the same request uses
        # Stripe's stable idempotency key and can safely persist the same session.
        raise
    return {"url": session.url, "session_id": session.reference.opaque_id, "attempt_id": attempt_id}

def create_portal(conn, tenant_id: str) -> dict:
    _require_payments()
    customer = store.customer_id(conn, tenant_id)
    if not customer:
        raise BillingError(404, "no_billing_account", "There's no billing account yet - choose a plan first.")
    url = payment_gateway().create_portal(_provider_reference(customer), return_url=f"{config.app_base_url()}/billing")
    return {"url": url}


def _live_subscription(conn, tenant_id: str) -> dict:
    sub = store.current_subscription(conn, tenant_id)
    if not sub:
        raise BillingError(404, "no_subscription", "Your company doesn't have a paid subscription yet.")
    return sub


def _classify_rights_change(current: dict, target: dict) -> tuple[str, tuple[str, ...]]:
    """Compare only explicitly configured rights; never infer a missing limit."""
    gains = losses = False
    uncertain = []

    current_entitlements = set(current.get("entitlements", ()))
    target_entitlements = set(target.get("entitlements", ()))
    gains |= bool(target_entitlements - current_entitlements)
    losses |= bool(current_entitlements - target_entitlements)

    current_features = current.get("features", {})
    target_features = target.get("features", {})
    for code in sorted(set(current_features) | set(target_features)):
        old = current_features.get(code)
        new = target_features.get(code)
        if old is None or new is None:
            uncertain.append(code)
            continue
        metadata = ("unit", "aggregation_type", "reset_cycle")
        if any(old.get(key) != new.get(key) for key in metadata):
            uncertain.append(code)
            continue
        old_limit, new_limit = old.get("limit"), new.get("limit")
        if old_limit == new_limit:
            continue
        # NULL is unlimited in the established usage_plan_limits schema.
        # Zero and positive values retain their distinct configured meaning.
        if old_limit is None:
            losses = True
        elif new_limit is None:
            gains = True
        elif new_limit > old_limit:
            gains = True
        else:
            losses = True

    if uncertain:
        return "unclassified", tuple(uncertain)
    if gains and losses:
        return "mixed", ()
    if gains:
        return "gain", ()
    if losses:
        return "loss", ()
    return "unchanged", ()


def _plan_change_context(conn, tenant_id: str, plan_key: str, period_code: str) -> dict:
    """Upgrade now (to a higher tier, or the same tier with a longer period)
    or downgrade at the end of the paid period."""
    _require_payments()
    sub = _live_subscription(conn, tenant_id)
    if sub["status"] not in config.ACCESS_STATUSES:
        raise BillingError(409, "payment_required", "Settle the outstanding payment before changing plan.")
    if sub["cancel_at_period_end"]:
        raise BillingError(409, "cancellation_pending", "Resume your subscription before changing plan.")
    if (plan_key, period_code) == (sub["plan_key"], sub["period_code"]):
        if sub["scheduled_plan_key"]:
            raise BillingError(409, "downgrade_scheduled", "This is already your plan; cancel the scheduled change instead.")
        raise BillingError(409, "already_on_plan", "This is already your plan.")
    if (plan_key, period_code) == (sub["scheduled_plan_key"], sub["scheduled_period_code"]):
        raise BillingError(409, "already_scheduled", "This change is already scheduled.")
    price = _price_or_error(conn, plan_key, period_code)

    if store.has_custom_contract(conn, tenant_id):
        raise BillingError(
            409, "plan_transition_unclassified",
            "This plan change needs review because the existing private contract has terms outside the public catalog.",
        )

    current_rights = usage.get_plan(conn, tenant_id)
    # An active Stripe subscription and a different effective manual/offline
    # assignment are an unresolved overlapping-grant case. Compare the
    # current rights to the Stripe plan without assigning precedence; if they
    # differ, require review before any provider mutation. A normal Stripe
    # trial remains on the Stripe assignment and follows the existing path.
    legitimate_trial = sub["status"] == "trialing" and current_rights.get("source") == "trial"
    if current_rights.get("source") != "stripe" and not legitimate_trial:
        stripe_rights = store.configured_plan_rights(
            conn, tenant_id, sub["plan_key"], trialing=sub["status"] == "trialing",
        )
        overlap, _ = _classify_rights_change(stripe_rights, current_rights)
        if overlap != "unchanged":
            raise BillingError(
                409, "plan_transition_conflict",
                "This plan change needs review because the effective assignment conflicts with the active subscription.",
            )
    target_rights = store.configured_plan_rights(
        conn, tenant_id, plan_key, trialing=sub["status"] == "trialing",
    )
    transition, _uncertain_features = _classify_rights_change(current_rights, target_rights)
    if transition == "unclassified":
        raise BillingError(
            409, "plan_transition_unclassified",
            "This plan change needs review because one or more feature limits are not comparable.",
        )

    current_tier = store.plan_tier(conn, sub["plan_key"])
    current_price = store.current_price(conn, sub["plan_key"], sub["period_code"]) or {}
    # Rights decide any gain/loss transition. Preserve the established
    # tier/price rule only when the configured rights vector is unchanged,
    # such as a billing-period-only change.
    is_upgrade = transition == "gain" or (
        transition == "unchanged" and (
            price["tier_level"] > current_tier or
            (price["tier_level"] == current_tier and price["amount"] >= current_price.get("amount", 0))
        )
    )

    return sub, price, is_upgrade, current_rights, target_rights


def preview_plan_change(conn, tenant_id: str, plan_key: str, period_code: str) -> dict:
    sub, price, upgrade, current, target = _plan_change_context(conn, tenant_id, plan_key, period_code)
    used = {item['feature_code']: item['current_usage'] for item in usage.current_usage(conn, tenant_id, current)}
    changes = []
    for code in sorted(set(current['features']) | set(target['features'])):
        if code in ('web_searches','rag_assistant','tracked_competitors'):
            continue
        before = current['features'].get(code, {}).get('limit', 'not_included')
        after = target['features'].get(code, {}).get('limit', 'not_included')
        if before != after:
            changes.append({'feature_code':code,'before':before,'after':after,
                            'unit':target['features'].get(code,{}).get('unit'),
                            'over_limit':isinstance(after,(int,float)) and used.get(code,0)>after})
    for code in sorted(set(current.get('entitlements',[])) ^ set(target.get('entitlements',[]))):
        changes.append({'feature_code':code,'before':code in current.get('entitlements',[]),'after':code in target.get('entitlements',[]),'over_limit':False})
    trial = sub['status']=='trialing'
    return {'eligible':True, 'direction':'upgrade' if upgrade else 'downgrade',
            'timing':'immediate' if upgrade else 'period_end',
            'effective_at':None if upgrade else sub['current_period_end'].isoformat(),
            'trial_end':sub.get('trial_end').isoformat() if sub.get('trial_end') else None,
            'payment_policy':'preserve_trial' if upgrade and trial else 'stripe_proration' if upgrade else 'next_period_price',
            'immediate_amount':None, 'currency':price['currency'], 'new_period_price':price['amount'],
            'feature_changes':changes, 'activation':'verified_webhook', 'deletes_data':False}


def _validate_transition_snapshot(local: dict, remote: SubscriptionSnapshot, tenant_id: str):
    """Missing/delayed reconciliation must not drive a provider action from stale rights."""
    if (remote.reference != _provider_reference(local["stripe_subscription_id"])
            or remote.state.value != local["status"]
            or remote.period_start != local.get("current_period_start") or remote.period_end != local.get("current_period_end")
            or remote.trial_end != local.get("trial_end")):
        raise BillingError(409, "billing_reconciling", "Subscription state is awaiting verified billing reconciliation. Try again after it completes.")
    simulated = payment_gateway().customer_time(remote.customer, tenant_reference=tenant_id)
    now = simulated.timestamp() if simulated else time.time()
    if remote.state == SubscriptionState.TRIALING and (not remote.trial_end or remote.trial_end.timestamp() <= now):
        raise BillingError(409, "payment_required", "The trial has ended. Wait for verified payment or use payment recovery.")
    return now


def change_plan(conn, sys_conn, tenant_id: str, plan_key: str, period_code: str) -> dict:
    # Serialize provider actions without holding a row lock across network calls.
    with checkout_attempts.tenant_lock(sys_conn, "plan-transition:" + tenant_id):
        return _change_plan_locked(conn, sys_conn, tenant_id, plan_key, period_code)


def _change_plan_locked(conn, sys_conn, tenant_id: str, plan_key: str, period_code: str) -> dict:
    sub, price, is_upgrade, _current, _target = _plan_change_context(conn, tenant_id, plan_key, period_code)
    gateway = payment_gateway()
    remote = gateway.get_subscription(_provider_reference(sub["stripe_subscription_id"]))
    transition_now = _validate_transition_snapshot(sub, remote, tenant_id)
    intent = SubscriptionChangeIntent(remote.reference, _provider_reference(price["stripe_price_id"]),
        remote.trial_end if remote.state == SubscriptionState.TRIALING else None)

    if is_upgrade:
        # Preserve the existing commit boundary: clear the local pending change
        # after the provider update, before optional payment-recovery lookup.
        updated = gateway.change_subscription(intent, current=remote, resolve_payment_url=False)
        store.set_schedule(sys_conn, tenant_id, sub["stripe_subscription_id"], None, None)
        sys_conn.commit()
        if updated.payment_required:
            invoice = updated.subscription.latest_invoice
            try:
                payment_url = gateway.get_invoice(invoice).payment_url if invoice else None
            except PaymentProviderError:
                # The subscription write already happened. A subsequent read
                # failure is not evidence that the approved change was rejected.
                raise PaymentProviderError(ProviderOperationOutcome.OUTCOME_UNKNOWN) from None
            return {"state": "payment_required", "timing": "immediate", "payment_url": payment_url}
        return {"state": "applied", "timing": "immediate"}

    try:
        scheduled = gateway.schedule_change(intent, now=datetime.fromtimestamp(transition_now, timezone.utc), current=remote)
    except PaymentProviderError as error:
        if error.reason == "additional_invoice_items":
            raise BillingError(409, "plan_transition_unclassified", "This schedule contains additional invoice items and needs billing review before changing plan.") from None
        if error.reason == "trial_boundary_mismatch":
            raise BillingError(409, "billing_reconciling", "The schedule trial boundary does not match the subscription.") from None
        if error.reason == "schedule_unavailable":
            raise BillingError(502, "schedule_unavailable", "The payment provider couldn't schedule this change. Try again.") from None
        raise
    store.set_schedule(sys_conn, tenant_id, sub["stripe_subscription_id"], plan_key, period_code)
    sys_conn.commit()
    return {
        "state": "scheduled", "timing": "period_end",
        "effective_at": scheduled.effective_at.isoformat(),
    }


def cancel_scheduled_change(conn, sys_conn, tenant_id: str) -> dict:
    with checkout_attempts.tenant_lock(sys_conn, "plan-transition:" + tenant_id):
        return _cancel_scheduled_change_locked(conn, sys_conn, tenant_id)


def _cancel_scheduled_change_locked(conn, sys_conn, tenant_id: str) -> dict:
    _require_payments()
    sub = _live_subscription(conn, tenant_id)
    if not sub["scheduled_plan_key"]:
        raise BillingError(409, "nothing_scheduled", "No plan change is scheduled.")
    gateway = payment_gateway()
    remote = gateway.get_subscription(_provider_reference(sub["stripe_subscription_id"]))
    _validate_transition_snapshot(sub, remote, tenant_id)
    if remote.schedule:
        gateway.cancel_scheduled_change(remote.schedule)
    store.set_schedule(sys_conn, tenant_id, sub["stripe_subscription_id"], None, None)
    sys_conn.commit()
    return {"state": "cancelled"}


def set_cancellation(conn, tenant_id: str, cancel: bool) -> dict:
    """Cancel at period end, or undo that. Stripe's webhook updates the
    local record (the provider is the source of truth)."""
    _require_payments()
    sub = _live_subscription(conn, tenant_id)
    if cancel and sub["cancel_at_period_end"]:
        raise BillingError(409, "already_cancelling", "Your subscription is already set to end.")
    if not cancel and not sub["cancel_at_period_end"]:
        raise BillingError(409, "not_cancelling", "Your subscription isn't set to end.")
    payment_gateway().set_cancellation(_provider_reference(sub["stripe_subscription_id"]), cancel_at_period_end=cancel)
    return {"state": "cancelling" if cancel else "resumed",
            "access_until": sub["current_period_end"].isoformat() if sub["current_period_end"] else None}


__all__ = [
    "BillingError", "PaymentsNotConfigured", "create_checkout", "create_portal", "change_plan",
    "cancel_scheduled_change", "set_cancellation",
]

