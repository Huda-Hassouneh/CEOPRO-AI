"""
Stripe webhooks: the source of truth for a company's subscription.

Ported from the reference project's webhook service (read-only reference:
src/modules/subscription/service/stripe-webhook.service.ts and
src/utils/webhook.ts / "webhook handlers.ts" on the reference project's `backend` branch):
signature checked on the raw body, every event stored once by its id and
marked processed only after it succeeds (Stripe retries failures), the same
event set and status mapping.

Improvements over that implementation:
- The event row is claimed with INSERT ... ON CONFLICT and a row lock, so
  two deliveries of one event can't both run.
- Subscription events never trust the (possibly stale) payload: the
  subscription is always re-read from Stripe before it is stored, so an old
  event delivered late can't overwrite newer state.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from src.ai.billing import promotions, store, stripe_api
from src.ai.core import entitlements

logger = logging.getLogger("APEX_BILLING_WEBHOOKS")

SUBSCRIPTION_EVENTS = {
    "customer.subscription.created", "customer.subscription.updated", "customer.subscription.deleted",
    "customer.subscription.paused", "customer.subscription.resumed", "customer.subscription.trial_will_end",
    "customer.subscription.pending_update_applied", "customer.subscription.pending_update_expired",
}
INVOICE_EVENTS = {"invoice.paid", "invoice.payment_succeeded", "invoice.payment_failed"}
SCHEDULE_EVENTS = {
    "subscription_schedule.released", "subscription_schedule.completed",
    "subscription_schedule.canceled", "subscription_schedule.aborted",
}


class WebhookRetry(Exception):
    """Processing failed in a way Stripe should retry (500 to Stripe)."""


def _id(value) -> Optional[str]:
    if isinstance(value, dict):
        return value.get("id")
    return value


def _invoice_subscription_id(invoice: dict) -> Optional[str]:
    parent = (invoice.get("parent") or {}).get("subscription_details") or {}
    return _id(parent.get("subscription")) or _id((invoice.get("subscription_details") or {}).get("subscription")) \
        or _id(invoice.get("subscription"))


def _invoice_tenant_hint(invoice: dict) -> Optional[str]:
    parent = (invoice.get("parent") or {}).get("subscription_details") or {}
    for metadata in (invoice.get("metadata"), parent.get("metadata"), (invoice.get("subscription_details") or {}).get("metadata")):
        if metadata and metadata.get("tenant_id"):
            return metadata["tenant_id"]
    return None


def _resolve_tenant(sys_conn, stripe_sub: dict, hint: Optional[str] = None) -> Optional[str]:
    """Which company a subscription belongs to: our own records first (they
    were written by us), then the metadata we put on the checkout."""
    return (
        store.tenant_for_subscription(sys_conn, stripe_sub["id"])
        or store.tenant_for_customer(sys_conn, _id(stripe_sub.get("customer")) or "")
        or (stripe_sub.get("metadata") or {}).get("tenant_id")
        or hint
    )

def sync_subscription(sys_conn, subscription_id: str, event_created: datetime, hint: Optional[str] = None,
                     *, custom_payment_verified: bool = False, invoice_id: Optional[str] = None,
                     provider_event_id: Optional[str] = None) -> Optional[str]:
    """Re-reads the subscription from Stripe and stores it. Returns the tenant."""
    # Serialize snapshots for one subscription across distinct event IDs.
    with sys_conn.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0));",
                       ("keel_stripe_subscription:" + subscription_id,))
    stripe_sub = stripe_api.retrieve_subscription(subscription_id)
    if stripe_sub.get("id") != subscription_id:
        raise WebhookRetry("subscription identity does not match the requested object")
    tenant_id = _resolve_tenant(sys_conn, stripe_sub, hint)
    if not tenant_id:
        # Not one of ours (yet): fail so Stripe retries once checkout's own
        # event has linked the customer.
        raise WebhookRetry(f"no company found for subscription {subscription_id}")
    sub_metadata = stripe_sub.get("metadata") or {}
    if sub_metadata.get("billing_kind") == "custom_quote":
        return _sync_custom_quote_subscription(
            sys_conn, stripe_sub, tenant_id, event_created,
            payment_verified=custom_payment_verified, invoice_id=invoice_id,
            provider_event_id=provider_event_id,
        )
    price_id = store.subscription_price_id(stripe_sub)
    resolved = store.resolve_price(sys_conn, price_id) if price_id else None
    if not resolved:
        raise WebhookRetry(f"price {price_id} is not in the plan catalog")
    plan_key, period_code = resolved
    customer = _id(stripe_sub.get("customer"))
    customer_tenant = store.tenant_for_customer(sys_conn, customer) if customer else None
    if customer_tenant and str(customer_tenant) != str(tenant_id):
        raise WebhookRetry("subscription customer belongs to another company")
    if customer and not customer_tenant:
        store.save_customer(sys_conn, tenant_id, customer)
    store.apply_subscription(sys_conn, tenant_id, stripe_sub, plan_key, period_code, event_created)
    entitlements.forget(tenant_id)  # the new plan's modules apply at once
    return tenant_id

def _sync_custom_quote_subscription(sys_conn, stripe_sub: dict, tenant_id: str, event_created: datetime,
                                    *, payment_verified: bool, invoice_id: Optional[str],
                                    provider_event_id: Optional[str]) -> str:
    """Keep custom access pending until this verified webhook has a paid invoice."""
    from decimal import Decimal
    from src.ai.billing import admin
    metadata = stripe_sub.get("metadata") or {}
    attempt_id = metadata.get("quote_attempt_id")
    quote_id = metadata.get("custom_quote_id")
    revision_id = metadata.get("custom_quote_revision_id")
    if not all((attempt_id, quote_id, revision_id)):
        raise WebhookRetry("Custom subscription is missing quote correlation metadata")
    customer = _id(stripe_sub.get("customer"))
    with sys_conn.cursor() as cursor:
        cursor.execute("""
            SELECT q.tenant_id,q.quote_id,q.current_revision_id,q.state,r.revision_id,r.state,
                   r.feature_quantities,r.configuration,r.commercial_terms,r.valid_until,r.approved_by_user_id,
                   a.attempt_id,a.stripe_checkout_session_id,a.stripe_subscription_id,
                   EXISTS(SELECT 1 FROM public.billing_custom_contract_activations x
                     WHERE x.stripe_subscription_id=%s) AS already_activated
              FROM public.billing_custom_quotes q
              JOIN public.billing_custom_quote_revisions r ON r.tenant_id=q.tenant_id AND r.quote_id=q.quote_id
              JOIN public.billing_custom_quote_checkout_attempts a ON a.tenant_id=q.tenant_id AND a.quote_id=q.quote_id
               AND a.revision_id=r.revision_id
             WHERE q.quote_id=%s AND r.revision_id=%s AND a.attempt_id=%s
        """, (stripe_sub["id"], quote_id, revision_id, attempt_id))
        row = cursor.fetchone()
    if not row or str(row[0]) != str(tenant_id) or str(row[2]) != str(revision_id) or row[3] != "accepted" or row[5] != "accepted":
        raise WebhookRetry("Custom quote, tenant or current revision does not match the subscription")
    if customer and str(store.tenant_for_customer(sys_conn, customer)) != str(tenant_id):
        raise WebhookRetry("Custom subscription customer belongs to another tenant")
    if row[12] is None:
        raise WebhookRetry("Custom checkout session has not been persisted")
    if row[14]:
        # Renewal/cancellation events update only the existing subscription;
        # they cannot provision the contract a second time.
        store.apply_subscription(sys_conn, tenant_id, stripe_sub, "custom", "monthly", event_created)
        entitlements.forget(tenant_id)
        return tenant_id
    if not payment_verified or not invoice_id or not provider_event_id:
        # A Checkout redirect, session completion, or subscription.created
        # event alone never grants custom entitlements.
        return tenant_id
    with sys_conn.cursor() as cursor:
        cursor.execute("""SELECT status FROM public.billing_payments
          WHERE tenant_id=%s AND stripe_invoice_id=%s AND stripe_subscription_id=%s""",
          (tenant_id, invoice_id, stripe_sub["id"]))
        payment = cursor.fetchone()
    if not payment or payment[0] != "succeeded":
        raise WebhookRetry("Custom subscription has no verified settled initial invoice")
    with sys_conn.cursor() as cursor:
        cursor.execute("""SELECT 1 FROM public.billing_subscriptions WHERE tenant_id=%s
          AND stripe_subscription_id<>%s AND status IN ('active','trialing','past_due','pending','payment_failed','paused')""",
          (tenant_id, stripe_sub["id"]))
        if cursor.fetchone():
            raise WebhookRetry("another current subscription exists; refusing overlapping Custom contract activation")
    invoice = stripe_api.retrieve_invoice(invoice_id)
    terms = row[8] or {}
    try:
        expected_minor = int(Decimal(str(terms["monthlyPriceUsd"])) * 100)
    except Exception as exc:
        raise WebhookRetry("Approved Custom quote has invalid commercial terms") from exc
    if (invoice.get("id") != invoice_id or invoice.get("currency", "").lower() != "usd"
            or int(invoice.get("amount_paid") or 0) != expected_minor
            or invoice.get("billing_reason") != "subscription_create"):
        raise WebhookRetry("Paid Custom invoice does not match the approved USD quote")
    paid_epoch = (invoice.get("status_transitions") or {}).get("paid_at")
    if paid_epoch and datetime.fromtimestamp(int(paid_epoch), tz=timezone.utc) > row[9]:
        raise WebhookRetry("Custom offer expired before payment was completed")
    limits = row[6] or {}
    reference = f"custom-quote:{quote_id}:{revision_id}"
    admin.set_custom_contract(
        sys_conn, tenant_id=tenant_id, contract_ref=reference,
        approved_by=str(row[10]), reason=f"Verified Stripe invoice {invoice_id}; webhook {provider_event_id}",
        limits={str(key): int(value) for key, value in limits.items()},
        monthly_price=Decimal(str(terms["monthlyPriceUsd"])), currency="USD", trial_days=0,
        data_sources=(row[7] or {}).get("dataSources", []),
        included_features=(row[7] or {}).get("enabledFeatures", []),
        refresh_frequency=(row[7] or {}).get("refreshFrequency"), period_months=1,
    )
    store.apply_subscription(sys_conn, tenant_id, stripe_sub, "custom", "monthly", event_created)
    with sys_conn.cursor() as cursor:
        cursor.execute("""INSERT INTO public.billing_custom_contract_activations
          (tenant_id,quote_id,revision_id,attempt_id,stripe_subscription_id,stripe_invoice_id,provider_event_id,invoice_paid_at)
          VALUES(%s,%s,%s,%s,%s,%s,%s,to_timestamp(%s))
          ON CONFLICT DO NOTHING""",
          (tenant_id, quote_id, revision_id, attempt_id, stripe_sub["id"], invoice_id, provider_event_id, paid_epoch or int(event_created.timestamp())))
        if cursor.rowcount != 1:
            raise WebhookRetry("Custom contract activation identity already exists; reconcile before retry")
        cursor.execute("""UPDATE public.billing_custom_quote_checkout_attempts
          SET stripe_subscription_id=%s,stripe_invoice_id=%s,provider_event_id=%s,provider_outcome='settled',
              state='settled',updated_at=clock_timestamp() WHERE attempt_id=%s AND tenant_id=%s""",
          (stripe_sub["id"], invoice_id, provider_event_id, attempt_id, tenant_id))
        cursor.execute("""INSERT INTO public.billing_custom_quote_events
          (tenant_id,quote_id,revision_id,actor_user_id,action,idempotency_key,evidence)
          VALUES(%s,%s,%s,NULL,'contract_activated',%s,jsonb_build_object('invoice_id',%s,'subscription_id',%s))""",
          (tenant_id, quote_id, revision_id, provider_event_id, invoice_id, stripe_sub["id"]))
    entitlements.forget(tenant_id)
    return tenant_id

def _record_custom_checkout_session(sys_conn, session: dict, tenant_id: str, event_id: str) -> None:
    """Bind a signature-verified Checkout event to its durable quote attempt.

    This runs only in the existing system-connection webhook transaction. The
    session must match the accepted current revision, the locally prepared
    session identity (when already persisted), and the tenant metadata placed
    by the Python Checkout service.
    """
    metadata = session.get("metadata") or {}
    attempt_id = metadata.get("quote_attempt_id")
    quote_id = metadata.get("custom_quote_id")
    revision_id = metadata.get("custom_quote_revision_id")
    session_id = session.get("id")
    subscription_id = _id(session.get("subscription"))
    if (metadata.get("billing_kind") != "custom_quote" or metadata.get("tenant_id") != str(tenant_id)
            or not all((attempt_id, quote_id, revision_id, session_id, subscription_id))
            or session.get("mode") != "subscription"
            or session.get("client_reference_id") != attempt_id):
        raise WebhookRetry("Custom Checkout session is missing valid quote correlation")
    with sys_conn.cursor() as cursor:
        cursor.execute("""
          SELECT q.current_revision_id,q.state,r.state,r.valid_until,a.stripe_checkout_session_id,
                 a.stripe_subscription_id,a.state
            FROM public.billing_custom_quotes q
            JOIN public.billing_custom_quote_revisions r ON r.tenant_id=q.tenant_id AND r.quote_id=q.quote_id
            JOIN public.billing_custom_quote_checkout_attempts a ON a.tenant_id=q.tenant_id AND a.quote_id=q.quote_id
             AND a.revision_id=r.revision_id
           WHERE q.tenant_id=%s AND q.quote_id=%s AND r.revision_id=%s AND a.attempt_id=%s
           FOR UPDATE OF q,r,a
        """, (tenant_id, quote_id, revision_id, attempt_id))
        row = cursor.fetchone()
        if (not row or str(row[0]) != str(revision_id) or row[1] != "accepted" or row[2] != "accepted"
                or (row[4] and row[4] != session_id) or (row[5] and row[5] != subscription_id)):
            raise WebhookRetry("Custom Checkout session does not match the accepted current quote attempt")
        # If a paid-invoice event was delivered first, activation already bound
        # this exact session/subscription. A late session event is a harmless
        # duplicate even when its delivery occurs after the offer expiry.
        if row[6] == "settled":
            return
        if (not row[3] or row[3] <= datetime.now(timezone.utc)
                or row[6] not in {"prepared", "session_created"}):
            raise WebhookRetry("Custom Checkout session does not match the accepted current quote attempt")
        cursor.execute("""
          UPDATE public.billing_custom_quote_checkout_attempts
             SET stripe_checkout_session_id=COALESCE(stripe_checkout_session_id,%s),
                 stripe_subscription_id=COALESCE(stripe_subscription_id,%s),
                 provider_event_id=%s,state='session_created',updated_at=clock_timestamp()
           WHERE tenant_id=%s AND attempt_id=%s
        """, (session_id, subscription_id, event_id, tenant_id, attempt_id))
        cursor.execute("""
          INSERT INTO public.billing_custom_quote_events
            (tenant_id,quote_id,revision_id,actor_user_id,action,idempotency_key,evidence)
          VALUES(%s,%s,%s,NULL,'checkout_identity_updated',%s,
                 jsonb_build_object('attempt_id',%s,'checkout_session_id',%s,'subscription_id',%s))
          ON CONFLICT (tenant_id,quote_id,action,idempotency_key) DO NOTHING
        """, (tenant_id, quote_id, revision_id, event_id, attempt_id, session_id, subscription_id))


def _failure_reason(invoice: dict) -> str:
    error = invoice.get("last_finalization_error") or {}
    return error.get("message") or "The payment could not be collected."


_LOCK_WAIT = "30s"


def _lock_event(sys_conn, event_id: str) -> None:
    """Serialises everything done for one Stripe event id. claim_event's row
    lock is released by the commit that follows it, so without this two
    simultaneous deliveries of the same event (Stripe retries, or a replay)
    could both see it unprocessed and both run. A session-level advisory lock
    survives those commits; the second delivery waits here, then finds the
    event already processed and acknowledges it as a duplicate."""
    import psycopg2

    try:
        with sys_conn.cursor() as cursor:
            cursor.execute(f"SET lock_timeout = '{_LOCK_WAIT}';")
            cursor.execute("SELECT pg_advisory_lock(hashtextextended(%s, 0));", ("keel_stripe_event:" + event_id,))
            cursor.execute("RESET lock_timeout;")
        sys_conn.commit()  # a session-level lock outlives commits and rollbacks
    except psycopg2.errors.LockNotAvailable as err:
        sys_conn.rollback()
        raise WebhookRetry(f"event {event_id} is still being processed by another delivery") from err


def _unlock_event(sys_conn, event_id: str) -> None:
    try:
        sys_conn.rollback()  # a failed transaction cannot run the unlock
        with sys_conn.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_unlock(hashtextextended(%s, 0));", ("keel_stripe_event:" + event_id,))
        sys_conn.commit()
    except Exception:  # noqa: BLE001 - a dead connection drops its session locks anyway
        logger.warning("could not release the lock for Stripe event %s", event_id)


def handle_event(sys_conn, event: dict) -> dict:
    """Processes one verified event, at most once at a time per event id.
    Returns {"duplicate": bool}."""
    _lock_event(sys_conn, event["id"])
    try:
        return _handle_locked(sys_conn, event)
    finally:
        _unlock_event(sys_conn, event["id"])


def _handle_locked(sys_conn, event: dict) -> dict:
    created = datetime.fromtimestamp(int(event.get("created") or 0), tz=timezone.utc)
    if not store.claim_event(sys_conn, event["id"], event["type"], created, event):
        sys_conn.commit()
        return {"duplicate": True}
    sys_conn.commit()

    event_type, obj = event["type"], (event.get("data") or {}).get("object") or {}
    tenant_id = None
    try:
        if event_type == "checkout.session.completed":
            if obj.get("mode") == "subscription" and obj.get("subscription"):
                metadata = obj.get("metadata") or {}
                custom_quote = metadata.get("billing_kind") == "custom_quote"
                hint = metadata.get("tenant_id") if custom_quote else (
                    obj.get("client_reference_id") or metadata.get("tenant_id"))
                if obj.get("customer") and hint and not store.tenant_for_customer(sys_conn, obj["customer"]):
                    store.save_customer(sys_conn, hint, obj["customer"])
                tenant_id = sync_subscription(sys_conn, _id(obj["subscription"]), created, hint)
                if custom_quote:
                    _record_custom_checkout_session(sys_conn, obj, tenant_id, event["id"])
                else:
                    promotions.checkout_completed(sys_conn, session=obj, tenant_id=tenant_id, stripe_event_id=event["id"])
        elif event_type == "checkout.session.expired":
            promotions.checkout_expired(sys_conn, session=obj, stripe_event_id=event["id"])
        elif event_type in SUBSCRIPTION_EVENTS:
            tenant_id = sync_subscription(sys_conn, obj["id"], created)
        elif event_type in INVOICE_EVENTS:
            # Authenticated event snapshots can still be stale. Fetch current
            # invoice truth while serialized against other invoice events.
            invoice_id = obj["id"]
            with sys_conn.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0));",
                               ("keel_stripe_invoice:" + invoice_id,))
            invoice = stripe_api.retrieve_invoice(invoice_id)
            if invoice.get("id") != invoice_id:
                raise WebhookRetry("invoice identity does not match the requested object")
            subscription_id = _invoice_subscription_id(invoice)
            event_subscription = _invoice_subscription_id(obj)
            if event_subscription and event_subscription != subscription_id:
                raise WebhookRetry("invoice subscription identity changed")
            if subscription_id:
                tenant_id = sync_subscription(sys_conn, subscription_id, created, _invoice_tenant_hint(invoice))
                customer = _id(invoice.get("customer"))
                if customer and str(store.tenant_for_customer(sys_conn, customer)) != str(tenant_id):
                    raise WebhookRetry("invoice customer belongs to another company")
                if invoice.get("status") == "paid" or invoice.get("paid") is True:
                    store.record_payment(sys_conn, tenant_id, invoice, subscription_id, "succeeded")
                    fresh_sub = stripe_api.retrieve_subscription(subscription_id)
                    if (fresh_sub.get("metadata") or {}).get("billing_kind") == "custom_quote":
                        tenant_id = sync_subscription(sys_conn, subscription_id, created,
                            _invoice_tenant_hint(invoice), custom_payment_verified=True,
                            invoice_id=invoice_id, provider_event_id=event["id"])
                    promotions.invoice_event(
                        sys_conn, tenant_id=tenant_id, invoice=invoice, subscription_id=subscription_id,
                        stripe_event_id=event["id"], payment_succeeded=True,
                    )
                elif event_type == "invoice.payment_failed":
                    store.record_payment(sys_conn, tenant_id, invoice, subscription_id, "failed", _failure_reason(invoice))
                    promotions.invoice_event(
                        sys_conn, tenant_id=tenant_id, invoice=invoice, subscription_id=subscription_id,
                        stripe_event_id=event["id"], payment_succeeded=False,
                    )
                else:
                    raise WebhookRetry("paid invoice is not yet reconciled by the provider")
        elif event_type in SCHEDULE_EVENTS:
            subscription_id = _id(obj.get("released_subscription")) or _id(obj.get("subscription"))
            if subscription_id:
                tenant_id = sync_subscription(sys_conn, subscription_id, created)
                store.set_schedule(sys_conn, tenant_id, subscription_id, None, None)
        # Any other event type is stored for the record and acknowledged.
        store.finish_event(sys_conn, event["id"], tenant_id)
        sys_conn.commit()
        return {"duplicate": False}
    except Exception as err:
        sys_conn.rollback()
        logger.exception("Stripe event %s (%s) failed", event.get("id"), event_type)
        store.finish_event(sys_conn, event["id"], tenant_id, error=str(err)[:1000])
        sys_conn.commit()
        raise WebhookRetry(str(err)) from err