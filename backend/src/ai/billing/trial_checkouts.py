"""KEEL's provider-backed trial policy; no provider SDK or transport parameters.

Pending reservations serialize eligibility without granting rights or consuming
the trial. Only verified reconciliation records the one-time issued boundary.
"""
from datetime import timedelta
from uuid import UUID

from src.ai.billing.payment_contracts import SubscriptionState


class TrialCheckoutError(ValueError):
    pass


def reserve(conn, tenant_id, user_id, attempt, plan_key, period_code):
    if not user_id:
        raise TrialCheckoutError('trial_identity_required')
    with conn.cursor() as cur:
        # Compatibility for trusted manual deployments; local runtime uses the
        # scoped setup role, which already carries the authenticated context.
        if not getattr(conn, 'billing_setup_only', False):
            cur.execute("SELECT set_config('app.current_tenant_id',%s,true),set_config('app.current_user_id',%s,true)",
                        (str(tenant_id),str(user_id)))
        cur.execute('SELECT public.billing_reserve_trial_checkout(%s,%s,%s)',
                    (str(attempt['attempt_id']),plan_key,period_code))
        result = cur.fetchone()[0]
    if result.get('reason'):
        raise TrialCheckoutError(result['reason'])
    conn.commit()
    return result


def release(conn, attempt):
    with conn.cursor() as cur:
        if not getattr(conn,'billing_setup_only',False):
            cur.execute('SELECT tenant_id FROM billing_checkout_attempts WHERE attempt_id=%s',(str(attempt['attempt_id']),))
            row=cur.fetchone()
            if not row:
                return
            cur.execute("SELECT set_config('app.current_tenant_id',%s,true)",(str(row[0]),))
        cur.execute('SELECT public.billing_release_trial_checkout(%s)', (str(attempt['attempt_id']),))


def expired(conn, session, event_id):
    """Release only the matching, authenticated terminal Checkout notification."""
    reference = session.metadata.get('keel_trial_attempt_id')
    if not reference:
        return None
    try:
        reference = str(UUID(reference))
    except (ValueError, TypeError, AttributeError):
        raise TrialCheckoutError('invalid_trial_checkout_identity') from None
    from src.ai.billing import store
    tenant = store.tenant_for_customer(conn, session.customer.opaque_id) if session.customer else None
    if not tenant or session.metadata.get('tenant_id') != str(tenant):
        raise TrialCheckoutError('trial_checkout_customer_conflict')
    if getattr(conn, 'verified_webhook_only', False):
        conn.bind_tenant(tenant)
    else:
        with conn.cursor() as cur:
            cur.execute("UPDATE billing_webhook_events SET tenant_id=%s,error=NULL WHERE stripe_event_id=%s AND processed_at IS NULL AND (tenant_id IS NULL OR tenant_id=%s)", (tenant,event_id,tenant))
            cur.execute("SELECT set_config('app.current_tenant_id',%s,true),set_config('app.billing_event_id',%s,true)", (str(tenant),event_id))
    with conn.cursor() as cur:
        cur.execute('SELECT public.billing_expire_trial_checkout(%s,%s)', (reference, session.reference.opaque_id))
    return tenant


def reconcile(conn, tenant_id, subscription, plan_key, period_code, *, previous, issued_trial, event_id):
    """Validate authorized initial terms before any subscription/assignment write.

    Replays and later plan changes retain the original eligibility consumption.
    Historical local trials are read-only and keep their fixed cutoff.
    """
    reference = subscription.metadata.get('keel_trial_attempt_id')
    if not reference:
        if not previous and not issued_trial and subscription.state == SubscriptionState.TRIALING:
            raise TrialCheckoutError('trial_checkout_authorization_required')
        if not previous and issued_trial and subscription.state == SubscriptionState.TRIALING:
            if not subscription.trial_end or int(subscription.trial_end.timestamp()) != int(issued_trial['ends_at'].timestamp()):
                raise TrialCheckoutError('existing_trial_boundary_conflict')
        return None
    try:
        reference = str(UUID(reference))
    except (ValueError,TypeError,AttributeError):
        raise TrialCheckoutError('invalid_trial_checkout_identity') from None
    with conn.cursor() as cur:
        if not getattr(conn,'verified_webhook_only',False):
            # A trusted legacy connection still needs the same durable receipt.
            if not event_id:
                raise TrialCheckoutError('verified_trial_event_required')
            cur.execute("UPDATE billing_webhook_events SET tenant_id=%s,error=NULL WHERE stripe_event_id=%s AND processed_at IS NULL AND (tenant_id IS NULL OR tenant_id=%s)",
                        (tenant_id,event_id,tenant_id))
            cur.execute("SELECT set_config('app.current_tenant_id',%s,true),set_config('app.billing_event_id',%s,true)",
                        (str(tenant_id),event_id))
        cur.execute('SELECT plan_key,period_code,trial_duration_days,state,provider,provider_subscription_id,provider_price_id FROM billing_trial_checkouts WHERE tenant_id=%s AND attempt_id=%s',
                    (tenant_id,reference))
        claim = cur.fetchone()
    if not claim:
        raise TrialCheckoutError('trial_checkout_not_found')
    plan, period, days, state, provider, subscription_id, price = claim
    if state == 'activated':
        if (provider,subscription_id) != (subscription.reference.provider,subscription.reference.opaque_id):
            raise TrialCheckoutError('trial_subscription_identity_conflict')
        return issued_trial
    if state != 'pending' or (plan,period) != (plan_key,period_code):
        raise TrialCheckoutError('trial_checkout_terms_conflict')
    from src.ai.billing import store
    if (subscription.metadata.get('tenant_id') != str(tenant_id)
            or store.customer_id(conn, tenant_id) != subscription.customer.opaque_id):
        raise TrialCheckoutError('trial_checkout_customer_conflict')
    if (subscription.recurring_payment_method_ready is not True
            or subscription.state not in (SubscriptionState.TRIALING,SubscriptionState.ACTIVE,SubscriptionState.CANCELLED,SubscriptionState.EXPIRED)
            or not subscription.trial_start or not subscription.trial_end
            or subscription.trial_end-subscription.trial_start != timedelta(days=days)
            or len(subscription.items)!=1 or subscription.items[0].quantity!=1
            or subscription.items[0].price.opaque_id != price):
        raise TrialCheckoutError('trial_payment_setup_not_confirmed')
    with conn.cursor() as cur:
        cur.execute('SELECT public.billing_confirm_trial_checkout(%s,%s,%s,%s,%s)',
                    (reference,subscription.reference.provider,subscription.reference.opaque_id,
                     subscription.trial_start,subscription.trial_end))
    return {'plan_key':plan,'started_at':subscription.trial_start,'ends_at':subscription.trial_end}
