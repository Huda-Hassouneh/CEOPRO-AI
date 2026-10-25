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
import time
from decimal import Decimal, InvalidOperation
from src.ai.billing import checkout_attempts, config, promotions, store, stripe_api
from src.ai.billing.stripe_api import PaymentsNotConfigured
from src.ai.core import usage


class BillingError(Exception):
    """A request Billing can't fulfil, with an HTTP status and a stable code."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


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
        return existing
    customer = stripe_api.create_customer(email, company_name, tenant_id, idempotency_key=f"apex-customer-{tenant_id}")
    store.save_customer(sys_conn, tenant_id, customer["id"])
    sys_conn.commit()
    return customer["id"]


def _check_legacy_provider_contracts(conn,sys_conn,tenant_id,attempt):
    if attempt:
        return
    customer_id=store.customer_id(conn,tenant_id)
    if not customer_id:
        return
    remote=stripe_api.customer_subscriptions(customer_id)
    if any(item.get('status') in ('active','trialing','past_due','unpaid','incomplete','paused') for item in remote):
        raise BillingError(409,'checkout_reconciling','Stripe already has a current subscription. Wait for billing reconciliation; do not pay again.')
    pending=[item for item in stripe_api.open_customer_checkouts(customer_id) if item.get('mode')=='subscription']
    if len(pending)>1:
        raise BillingError(409,'checkout_reconciling','Several earlier Checkouts need billing review before another purchase.')
    if pending:
        metadata=pending[0].get('metadata') or {}
        adopted=checkout_attempts.reserve(sys_conn,tenant_id,'legacy:'+pending[0]['id'],metadata.get('plan_key','legacy_unknown'),metadata.get('period_code','legacy_unknown'))
        checkout_attempts.opened(sys_conn,adopted,pending[0])
        raise BillingError(409,'checkout_pending','An earlier Checkout is still open. Close it before selecting a new contract.')


def create_checkout(conn, sys_conn, tenant_id: str, email: str, company_name: str,
                    plan_key: str, period_code: str, promotion_code: str | None = None,
                    actor_user_id: str | None = None) -> dict:
    _require_payments()
    try:
        origin = config.app_base_url()
    except ValueError as exc:
        raise BillingError(503, 'frontend_origin_not_configured', str(exc)) from None
    if store.current_subscription(conn, tenant_id):
        raise BillingError(409, 'subscription_exists', 'Your company already has a subscription. Use Change Plan or payment recovery.')
    _price_or_error(conn, plan_key, period_code)
    request_key = hashlib.sha256(f'{plan_key}:{period_code}:{(promotion_code or "").strip().upper()}:{origin}'.encode()).hexdigest()
    with checkout_attempts.tenant_lock(sys_conn, tenant_id):
        if store.current_subscription(conn, tenant_id):
            raise BillingError(409, 'subscription_exists', 'Your company already has a subscription. Use its plan-change or recovery action.')
        if store.has_custom_contract(conn, tenant_id):
            raise BillingError(409, 'plan_transition_conflict', 'Review the existing Custom contract before starting another subscription.')
        attempt = checkout_attempts.active(sys_conn, tenant_id)
        _check_legacy_provider_contracts(conn,sys_conn,tenant_id,attempt)
        if attempt and attempt['session_id']:
            session = stripe_api.retrieve_checkout_session(attempt['session_id'])
            if session.get('status') == 'expired':
                checkout_attempts.expire(sys_conn, attempt)
                attempt = None
            elif session.get('status') == 'complete':
                if store.checkout_subscription_ended(conn, tenant_id, session.get('subscription')):
                    checkout_attempts.expire(sys_conn, attempt)
                    attempt = None
                else:
                    raise BillingError(409, 'checkout_reconciling', 'Payment confirmation is being reconciled. Do not start another Checkout.')
            elif attempt['request_key'] == request_key and session.get('status') == 'open':
                return {'url':session['url'], 'session_id':session['id']}
            else:
                raise BillingError(409, 'checkout_pending', 'Another Checkout is pending. Complete or cancel it before selecting a different contract.')
        if attempt and attempt['request_key'] != request_key:
            raise BillingError(409, 'checkout_pending', 'Another Checkout request is pending. Reconcile it before changing the selection.')
        if attempt and not attempt['session_id'] and time.time()-attempt['created_at'].timestamp()>23*3600:
            raise BillingError(409, 'checkout_reconciling', 'The previous provider request needs reconciliation before it can be retried safely.')
        attempt = attempt or checkout_attempts.reserve(sys_conn, tenant_id, request_key, plan_key, period_code)
        result = _create_checkout(conn, sys_conn, tenant_id, email, company_name, plan_key, period_code,
                                  promotion_code, actor_user_id, _attempt=attempt)
        if result.get('session_id'):
            checkout_attempts.opened(sys_conn, attempt, {'id':result['session_id']})
        return result


def checkout_status(conn, tenant_id: str, session_id: str) -> dict:
    if not session_id.startswith('cs_') or len(session_id)>255:
        raise BillingError(400,'invalid_checkout_session','Invalid Checkout reference.')
    session = stripe_api.retrieve_checkout_session(session_id)
    metadata = session.get('metadata') or {}
    if metadata.get('tenant_id') != tenant_id or session.get('customer') != store.customer_id(conn,tenant_id):
        raise BillingError(404,'checkout_not_found','This Checkout is not available to your company.')
    sub = store.current_subscription(conn,tenant_id)
    confirmed = bool(sub and sub['stripe_subscription_id']==session.get('subscription')
                     and sub['status'] in config.ACCESS_STATUSES and session.get('status')=='complete'
                     and session.get('payment_status') in ('paid','no_payment_required'))
    return {'state':'confirmed' if confirmed else 'pending', 'subscription_status':sub['status'] if sub else None}


def _create_checkout(conn, sys_conn, tenant_id: str, email: str, company_name: str,
                    plan_key: str, period_code: str, promotion_code: str | None = None,
                    actor_user_id: str | None = None, _attempt=None) -> dict:
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
    customer = _ensure_customer(conn, sys_conn, tenant_id, email, company_name)

    subscription_data = {"metadata": {"tenant_id": tenant_id, "plan_key": plan_key, "period_code": period_code}}
    # A company still inside its free trial keeps those days: billing starts
    # when the trial would have ended. The trial is never granted twice.
    trial = store.trial(conn, tenant_id)
    if trial and trial["ends_at"].timestamp() > time.time() + 48 * 3600:
        subscription_data["trial_end"] = int(trial["ends_at"].timestamp())
        subscription_data["trial_settings"] = {"end_behavior": {"missing_payment_method": "cancel"}}

    base = config.app_base_url()
    params = {
        "mode": "subscription",
        "customer": customer,
        "line_items": [{"price": price["stripe_price_id"], "quantity": 1}],
        "client_reference_id": tenant_id,
        "metadata": {"tenant_id": tenant_id, "plan_key": plan_key, "period_code": period_code},
        "subscription_data": subscription_data,
        "payment_method_collection": "always",
        # Existing Stripe-hosted code entry remains enabled for the legacy
        # checkout path. Managed promotions are mutually exclusive with that
        # entry field so a second Stripe code cannot stack in the same session.
        "allow_promotion_codes": promotion is None,
        "success_url": f"{base}/billing?checkout=success&session_id={{CHECKOUT_SESSION_ID}}",
        "cancel_url": f"{base}/billing?checkout=cancelled",
    }
    if config.automatic_tax():
        params["automatic_tax"] = {"enabled": True}
        params["customer_update"] = {"address": "auto", "name": "auto"}
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
                existing = stripe_api.retrieve_checkout_session(reservation["session_id"])
            except Exception as err:
                raise BillingError(502, "checkout_reconciliation_required",
                                   "The existing checkout could not be verified. Please try again later.") from err
            if existing.get("id") != reservation["session_id"] or existing.get("status") != "open" or not existing.get("url"):
                raise BillingError(409, "checkout_reconciliation_required",
                                   "The existing checkout is no longer open and needs reconciliation.")
            return {"url": existing["url"], "session_id": existing["id"]}
        try:
            promotions.begin_checkout_request(
                sys_conn, tenant_id=tenant_id, redemption_id=reservation["redemption_id"],
            )
            sys_conn.commit()
        except promotions.PromotionError as err:
            sys_conn.rollback()
            raise BillingError(err.status, err.code, err.message) from err
        params["discounts"] = [{"promotion_code": promotion["stripe_promotion_code_id"]}]
        # Stripe rejects the presence of both fields, including an explicit
        # allow_promotion_codes=False. Omit hosted code entry for a bound code.
        params.pop("allow_promotion_codes", None)
        params["metadata"]["keel_promotion_redemption_id"] = reservation["redemption_id"]
        params["subscription_data"]["metadata"]["keel_promotion_redemption_id"] = reservation["redemption_id"]
    try:
        provider_key = f"apex-promo-checkout-{reservation['redemption_id']}" if reservation else f"apex-checkout-{key}"
        if _attempt:
            params = checkout_attempts.freeze(sys_conn, _attempt, params)
        session = stripe_api.create_checkout_session(params, idempotency_key=provider_key)
        if _attempt:
            checkout_attempts.opened(sys_conn, _attempt, session)
    except Exception as err:
        rejected = stripe_api.checkout_request_rejected(err)
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
                session_id=session["id"],
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
    return {"url": session["url"], "session_id": session["id"]}



def create_custom_quote_checkout(conn, sys_conn, tenant_id: str, email: str, company_name: str,
                                quote_id: str, idempotency_key: str) -> dict:
    _require_payments()
    key=f"custom:{quote_id}:{config.app_base_url()}"
    with checkout_attempts.tenant_lock(sys_conn,tenant_id):
        if store.current_subscription(conn,tenant_id):
            raise BillingError(409,'subscription_exists','Your company already has a subscription.')
        shared=checkout_attempts.active(sys_conn,tenant_id)
        _check_legacy_provider_contracts(conn,sys_conn,tenant_id,shared)
        if shared and shared['request_key']!=key:
            raise BillingError(409,'checkout_pending','Another fixed or Custom Checkout is pending for your company.')
        if shared and shared['session_id']:
            prior=stripe_api.retrieve_checkout_session(shared['session_id'])
            if prior.get('status')=='complete':
                raise BillingError(409,'checkout_reconciling','This Custom Checkout is awaiting verified reconciliation.')
            if prior.get('status')=='expired':
                checkout_attempts.expire(sys_conn,shared)
                raise BillingError(409,'checkout_expired','This Custom Checkout expired. Request a new quote-bound attempt.')
        if shared and not shared['session_id'] and time.time()-shared['created_at'].timestamp()>23*3600:
            raise BillingError(409,'checkout_reconciling','The previous provider request needs reconciliation.')
        # Validate terms before reserving: the existing quote authority owns revision and acceptance checks.
        from src.ai.billing import custom_offers
        prepared=custom_offers.custom_checkout_prepare(conn,quote_id=quote_id,idempotency_key=idempotency_key)
        terms=prepared.get('commercial_terms') or {}
        if terms.get('currency')!='USD' or str(terms.get('billingPeriodMonths'))!='1':
            raise BillingError(409,'custom_terms_unsupported','This offer has unsupported billing terms.')
        shared=shared or checkout_attempts.reserve(sys_conn,tenant_id,key,'custom','monthly')
        return _create_custom_quote_checkout(conn,sys_conn,tenant_id,email,company_name,quote_id,idempotency_key,_shared=shared)


def cancel_pending_checkout(conn,sys_conn,tenant_id):
    with checkout_attempts.tenant_lock(sys_conn,tenant_id):
        attempt=checkout_attempts.active(sys_conn,tenant_id)
        if not attempt:return {'state':'no_pending_checkout'}
        if not attempt['session_id']:
            raise BillingError(409,'checkout_reconciling','The previous provider request must be reconciled first.')
        session=stripe_api.retrieve_checkout_session(attempt['session_id'])
        if session.get('status')=='complete':
            raise BillingError(409,'checkout_reconciling','Checkout completed; verify the subscription instead of cancelling it.')
        if session.get('status')=='open':
            stripe_api.expire_checkout_session(attempt['session_id'])
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
    if terms.get("currency") != "USD" or str(terms.get("billingPeriodMonths")) != "1":
        raise BillingError(409, "custom_terms_unsupported", "This Custom offer cannot be checked out with the supported billing terms.")
    try:
        amount = Decimal(str(terms["monthlyPriceUsd"]))
    except (KeyError, InvalidOperation, ValueError):
        raise BillingError(409, "custom_terms_unpriced", "This Custom offer has no valid approved price.") from None
    if not amount.is_finite() or amount <= 0 or amount != amount.quantize(Decimal("0.01")):
        raise BillingError(409, "custom_terms_unpriced", "This Custom offer has no valid approved price.")
    customer = _ensure_customer(conn, sys_conn, tenant_id, email, company_name)
    attempt_id = str(prepared["attempt_id"])
    base = config.app_base_url()
    params = {
        "mode": "subscription", "customer": customer,
        "line_items": [{"price_data": {"currency": "usd", "unit_amount": int(amount * 100),
            "product_data": {"name": "KEEL Custom Plan"},
            "recurring": {"interval": "month", "interval_count": 1}}, "quantity": 1}],
        "client_reference_id": attempt_id,
        "metadata": {"tenant_id": tenant_id, "custom_quote_id": quote_id,
                     "custom_quote_revision_id": str(prepared["revision_id"]),
                     "quote_attempt_id": attempt_id, "billing_kind": "custom_quote"},
        "subscription_data": {"metadata": {"tenant_id": tenant_id,
            "custom_quote_id": quote_id, "custom_quote_revision_id": str(prepared["revision_id"]),
            "quote_attempt_id": attempt_id, "billing_kind": "custom_quote"}},
        "payment_method_collection": "always", "allow_promotion_codes": False,
        "success_url": f"{base}/billing?checkout=success&session_id={{CHECKOUT_SESSION_ID}}",
        "cancel_url": f"{base}/billing?checkout=cancelled",
    }
    try:
        if _shared:
            params = checkout_attempts.freeze(sys_conn, _shared, params)
            if params['metadata']['custom_quote_revision_id'] != str(prepared['revision_id']):
                raise BillingError(409,'checkout_pending','The previous revision Checkout must be reconciled first.')
        session = stripe_api.create_checkout_session(params, idempotency_key=f"keel-custom-checkout-{attempt_id}")
        if _shared:
            checkout_attempts.opened(sys_conn,_shared,session)
        custom_offers.record_custom_checkout_session(conn, attempt_id=attempt_id, session_id=session["id"])
    except Exception:
        # The prepared attempt remains durable. Repeating the same request uses
        # Stripe's stable idempotency key and can safely persist the same session.
        raise
    return {"url": session["url"], "session_id": session["id"], "attempt_id": attempt_id}

def create_portal(conn, tenant_id: str) -> dict:
    _require_payments()
    customer = store.customer_id(conn, tenant_id)
    if not customer:
        raise BillingError(404, "no_billing_account", "There's no billing account yet - choose a plan first.")
    session = stripe_api.create_portal_session(customer, f"{config.app_base_url()}/billing")
    return {"url": session["url"]}


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


def change_plan(conn, sys_conn, tenant_id: str, plan_key: str, period_code: str) -> dict:
    sub, price, is_upgrade, _current, _target = _plan_change_context(conn, tenant_id, plan_key, period_code)
    stripe_sub = stripe_api.retrieve_subscription(sub["stripe_subscription_id"])
    item_id = stripe_sub["items"]["data"][0]["id"]
    schedule_id = stripe_sub.get("schedule")
    schedule_id = schedule_id.get("id") if isinstance(schedule_id, dict) else schedule_id

    if is_upgrade:
        if schedule_id:  # an upgrade replaces any pending downgrade
            stripe_api.release_schedule(schedule_id)
        items = [{"id": item_id, "price": price["stripe_price_id"], "quantity": 1}]
        if stripe_sub.get("status") == "trialing" and stripe_sub.get("trial_end"):
            updated = stripe_api.modify_subscription(
                sub["stripe_subscription_id"], items=items, proration_behavior="none", trial_end=stripe_sub["trial_end"],
            )
        else:
            updated = stripe_api.modify_subscription(
                sub["stripe_subscription_id"], items=items,
                proration_behavior="always_invoice", payment_behavior="pending_if_incomplete",
            )
        store.set_schedule(sys_conn, tenant_id, sub["stripe_subscription_id"], None, None)
        sys_conn.commit()
        if updated.get("pending_update"):
            invoice_id = updated.get("latest_invoice")
            invoice_id = invoice_id.get("id") if isinstance(invoice_id, dict) else invoice_id
            invoice = stripe_api.retrieve_invoice(invoice_id) if invoice_id else {}
            return {"state": "payment_required", "timing": "immediate", "payment_url": invoice.get("hosted_invoice_url")}
        return {"state": "applied", "timing": "immediate"}

    if not schedule_id:
        schedule_id = stripe_api.create_schedule_from_subscription(sub["stripe_subscription_id"])["id"]
    schedule = stripe_api.retrieve_schedule(schedule_id)
    now = int(time.time())
    current = schedule.get("current_phase") or {}
    phases = schedule.get("phases") or []
    phase = next((p for p in phases if p.get("start_date") == current.get("start_date")
                  and p.get("end_date") == current.get("end_date")), None) \
        or next((p for p in phases if (p.get("end_date") or 0) > now), None)
    if not phase:
        raise BillingError(502, "schedule_unavailable", "The payment provider couldn't schedule this change. Try again.")
    current_items = [
        {"price": (i["price"]["id"] if isinstance(i.get("price"), dict) else i["price"]), "quantity": i.get("quantity") or 1}
        for i in phase["items"]
    ]
    stripe_api.modify_schedule(
        schedule_id, end_behavior="release",
        phases=[
            {"start_date": phase["start_date"], "end_date": phase["end_date"], "items": current_items},
            {"items": [{"price": price["stripe_price_id"], "quantity": 1}]},
        ],
    )
    store.set_schedule(sys_conn, tenant_id, sub["stripe_subscription_id"], plan_key, period_code)
    sys_conn.commit()
    return {
        "state": "scheduled", "timing": "period_end",
        "effective_at": sub["current_period_end"].isoformat() if sub["current_period_end"] else None,
    }


def cancel_scheduled_change(conn, sys_conn, tenant_id: str) -> dict:
    _require_payments()
    sub = _live_subscription(conn, tenant_id)
    if not sub["scheduled_plan_key"]:
        raise BillingError(409, "nothing_scheduled", "No plan change is scheduled.")
    stripe_sub = stripe_api.retrieve_subscription(sub["stripe_subscription_id"])
    schedule_id = stripe_sub.get("schedule")
    schedule_id = schedule_id.get("id") if isinstance(schedule_id, dict) else schedule_id
    if schedule_id:
        stripe_api.release_schedule(schedule_id)
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
    if cancel:
        stripe_sub = stripe_api.retrieve_subscription(sub["stripe_subscription_id"])
        schedule_id = stripe_sub.get("schedule")
        schedule_id = schedule_id.get("id") if isinstance(schedule_id, dict) else schedule_id
        if schedule_id:
            stripe_api.release_schedule(schedule_id)
    stripe_api.modify_subscription(sub["stripe_subscription_id"], cancel_at_period_end=cancel)
    return {"state": "cancelling" if cancel else "resumed",
            "access_until": sub["current_period_end"].isoformat() if sub["current_period_end"] else None}


__all__ = [
    "BillingError", "PaymentsNotConfigured", "create_checkout", "create_portal", "change_plan",
    "cancel_scheduled_change", "set_cancellation",
]

