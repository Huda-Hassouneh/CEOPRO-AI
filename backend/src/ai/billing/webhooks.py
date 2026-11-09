"""
KEEL reconciliation of verified payment notifications and fresh provider state.

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
  subscription is always re-read through the gateway before it is stored, so an old
  event delivered late can't overwrite newer state.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from src.ai.billing import promotions, store, self_service
from src.ai.billing.payment_runtime import payment_gateway
from src.ai.billing.payment_contracts import (
    CheckoutSnapshot, InvoiceSnapshot, PaymentEventKind as Kind, PaymentState,
    ProviderReference, SubscriptionSnapshot, SubscriptionState, VerifiedPaymentEvent,
)
from src.ai.core import entitlements

logger = logging.getLogger("APEX_BILLING_WEBHOOKS")

class WebhookRetry(Exception):
    """Processing failed in a way Stripe should retry (500 to Stripe)."""


def _resolve_tenant(sys_conn, subscription: SubscriptionSnapshot, hint: Optional[str] = None) -> Optional[str]:
    """Which company a subscription belongs to: our own records first (they
    were written by us), then the metadata we put on the checkout."""
    return (
        store.tenant_for_subscription(sys_conn, subscription.reference.opaque_id)
        or store.tenant_for_customer(sys_conn, subscription.customer.opaque_id)
        or subscription.metadata.get("tenant_id")
        or hint
    )

def sync_subscription(sys_conn, subscription_ref: ProviderReference, event_created: datetime, hint: Optional[str] = None,
                     *, custom_payment_verified: bool = False, invoice_id: Optional[str] = None,
                     provider_event_id: Optional[str] = None) -> Optional[str]:
    """Re-read current provider state under the existing lock, then apply KEEL rules."""
    subscription_id = subscription_ref.opaque_id
    # Serialize snapshots for one subscription across distinct event IDs.
    with sys_conn.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0));",
                       ("keel_stripe_subscription:" + subscription_id,))
    gateway = payment_gateway()
    subscription = gateway.get_subscription(subscription_ref)
    if subscription.reference != subscription_ref:
        raise WebhookRetry("subscription identity does not match the requested object")
    from src.ai.billing.journey_webhooks import protected
    if protected(sys_conn, customer=subscription.customer.opaque_id, subscription=subscription_id, metadata=subscription.metadata):
        raise WebhookRetry('Protected journey requires trusted reconciliation')
    tenant_id = _resolve_tenant(sys_conn, subscription, hint)
    if not tenant_id:
        # Not one of ours (yet): fail so Stripe retries once checkout's own
        # event has linked the customer.
        raise WebhookRetry(f"no company found for subscription {subscription_id}")
    if getattr(sys_conn, "verified_webhook_only", False):
        sys_conn.bind_tenant(tenant_id)
    sub_metadata = subscription.metadata
    if sub_metadata.get("billing_kind") == "custom_quote":
        return _sync_custom_quote_subscription(
            sys_conn, subscription, tenant_id, event_created,
            payment_verified=custom_payment_verified, invoice_id=invoice_id,
            provider_event_id=provider_event_id,
        )
    price_id = subscription.items[0].price.opaque_id if subscription.items else None
    resolved = store.resolve_price(sys_conn, price_id) if price_id else None
    if not resolved:
        raise WebhookRetry(f"price {price_id} is not in the plan catalog")
    plan_key, period_code = resolved
    customer = subscription.customer.opaque_id
    customer_tenant = store.tenant_for_customer(sys_conn, customer) if customer else None
    if customer_tenant and str(customer_tenant) != str(tenant_id):
        raise WebhookRetry("subscription customer belongs to another company")
    if customer and not customer_tenant:
        store.save_customer(sys_conn, tenant_id, customer)
    previous = store.current_subscription(sys_conn, tenant_id)
    trial_payment_verified = False
    if (previous and previous["stripe_subscription_id"] == subscription_id
            and previous.get("trial_end") and previous["status"] != "active"
            and subscription.state == SubscriptionState.ACTIVE):
        start = subscription.period_start
        # Invalid trial boundaries are rejected by apply_subscription without
        # querying an unrelated invoice. An 'active' label alone is not proof
        # of the first post-trial payment, including during invoice finalization.
        if start and start >= previous["trial_end"] and subscription.trial_end == previous["trial_end"]:
            latest = subscription.latest_invoice
            invoice = gateway.get_invoice(latest) if latest else None
            trial_payment_verified = bool(
                invoice and invoice.reference == latest and invoice.settlement_confirmed
                and invoice.subscription == subscription_ref
                and invoice.customer == subscription.customer
                and any(begin is not None and end is not None and begin <= start < end
                        for begin, end in invoice.coverage)
            )
    store.apply_subscription(sys_conn, tenant_id, subscription, plan_key, period_code, event_created,
                             trial_payment_verified=trial_payment_verified)
    entitlements.forget(tenant_id)  # the new plan's modules apply at once
    return tenant_id

def _sync_custom_quote_subscription(sys_conn, subscription: SubscriptionSnapshot, tenant_id: str, event_created: datetime,
                                    *, payment_verified: bool, invoice_id: Optional[str],
                                    provider_event_id: Optional[str]) -> str:
    """Keep custom access pending until this verified webhook has a paid invoice."""
    from decimal import Decimal
    from src.ai.billing import admin
    metadata = subscription.metadata
    attempt_id = metadata.get("quote_attempt_id")
    quote_id = metadata.get("custom_quote_id")
    revision_id = metadata.get("custom_quote_revision_id")
    if not all((attempt_id, quote_id, revision_id)):
        raise WebhookRetry("Custom subscription is missing quote correlation metadata")
    customer = subscription.customer.opaque_id
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
        """, (subscription.reference.opaque_id, quote_id, revision_id, attempt_id))
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
        # Older activations stored only selected overrides and accidentally
        # inherited the legacy Custom catalog's broad defaults. Fill omissions
        # only for this exact existing paid contract, preserving explicit owner
        # adjustments and any newer/different manual contract.
        current = store.current_subscription(sys_conn, tenant_id)
        if current and current["stripe_subscription_id"] == subscription.reference.opaque_id:
            admin.fill_missing_quote_limits(
                sys_conn, tenant_id=tenant_id, contract_ref=f"custom-quote:{quote_id}:{revision_id}",
                selected=row[6] or {}, approved_by=str(row[10]),
                reason=f"Verified paid quote reconciliation; webhook {provider_event_id}")
        store.apply_subscription(sys_conn, tenant_id, subscription, "custom", "monthly" if (row[8] or {}).get("currency") == "USD" else row[8]["periodCode"], event_created)
        entitlements.forget(tenant_id)
        return tenant_id
    if not payment_verified or not invoice_id or not provider_event_id:
        # A Checkout redirect, session completion, or subscription.created
        # event alone never grants custom entitlements.
        return tenant_id
    with sys_conn.cursor() as cursor:
        cursor.execute("""SELECT status FROM public.billing_payments
          WHERE tenant_id=%s AND stripe_invoice_id=%s AND stripe_subscription_id=%s""",
          (tenant_id, invoice_id, subscription.reference.opaque_id))
        payment = cursor.fetchone()
    if not payment or payment[0] != "succeeded":
        raise WebhookRetry("Custom subscription has no verified settled initial invoice")
    with sys_conn.cursor() as cursor:
        cursor.execute("""SELECT 1 FROM public.billing_subscriptions WHERE tenant_id=%s
          AND stripe_subscription_id<>%s AND status IN ('active','trialing','past_due','pending','payment_failed','paused')""",
          (tenant_id, subscription.reference.opaque_id))
        if cursor.fetchone():
            raise WebhookRetry("another current subscription exists; refusing overlapping Custom contract activation")
    invoice_ref = ProviderReference(subscription.reference.provider, invoice_id)
    invoice = payment_gateway().get_invoice(invoice_ref)
    terms = row[8] or {}
    try:
        payment_amount, months, period = self_service.checkout_terms(terms)
    except Exception as exc:
        raise WebhookRetry("Approved Custom quote has invalid commercial terms") from exc
    if (invoice.reference != invoice_ref or not invoice.currency_explicit or invoice.amount_paid.currency != "USD"
            or invoice.amount_paid.amount != payment_amount
            or invoice.initial_subscription_invoice is not True):
        raise WebhookRetry("Paid Custom invoice does not match the approved USD quote")
    paid_epoch = int(invoice.paid_at.timestamp()) if invoice.paid_at else None
    if invoice.paid_at and invoice.paid_at > row[9]:
        raise WebhookRetry("Custom offer expired before payment was completed")
    limits = row[6] or {}
    reference = f"custom-quote:{quote_id}:{revision_id}"
    admin.set_custom_contract(
        sys_conn, tenant_id=tenant_id, contract_ref=reference,
        approved_by=str(row[10]), reason=f"Verified Stripe invoice {invoice_id}; webhook {provider_event_id}",
        limits=admin.closed_quote_limits(limits),
        legacy_quote_limits=True,  # Honor the verified immutable pre-retirement quote.
        monthly_price=Decimal(str(terms.get("monthlyPrice", terms.get("monthlyPriceUsd")))), currency=terms["currency"], trial_days=0,
        data_sources=(row[7] or {}).get("dataSources", []),
        included_features=(row[7] or {}).get("enabledFeatures", []),
        refresh_frequency=(row[7] or {}).get("refreshFrequency"), period_months=months,
    )
    store.apply_subscription(sys_conn, tenant_id, subscription, "custom", "monthly" if (row[8] or {}).get("currency") == "USD" else row[8]["periodCode"], event_created)
    with sys_conn.cursor() as cursor:
        cursor.execute("""INSERT INTO public.billing_custom_contract_activations
          (tenant_id,quote_id,revision_id,attempt_id,stripe_subscription_id,stripe_invoice_id,provider_event_id,invoice_paid_at)
          VALUES(%s,%s,%s,%s,%s,%s,%s,to_timestamp(%s))
          ON CONFLICT DO NOTHING""",
          (tenant_id, quote_id, revision_id, attempt_id, subscription.reference.opaque_id, invoice_id, provider_event_id, paid_epoch or int(event_created.timestamp())))
        if cursor.rowcount != 1:
            raise WebhookRetry("Custom contract activation identity already exists; reconcile before retry")
        cursor.execute("""UPDATE public.billing_custom_quote_checkout_attempts
          SET stripe_subscription_id=%s,stripe_invoice_id=%s,provider_event_id=%s,provider_outcome='settled',
              state='settled',updated_at=clock_timestamp() WHERE attempt_id=%s AND tenant_id=%s""",
          (subscription.reference.opaque_id, invoice_id, provider_event_id, attempt_id, tenant_id))
        cursor.execute("""INSERT INTO public.billing_custom_quote_events
          (tenant_id,quote_id,revision_id,actor_user_id,action,idempotency_key,evidence)
          VALUES(%s,%s,%s,NULL,'contract_activated',%s,jsonb_build_object('invoice_id',%s,'subscription_id',%s))""",
          (tenant_id, quote_id, revision_id, provider_event_id, invoice_id, subscription.reference.opaque_id))
    entitlements.forget(tenant_id)
    return tenant_id

def _record_custom_checkout_session(sys_conn, session: CheckoutSnapshot, tenant_id: str, event_id: str) -> None:
    """Bind a signature-verified Checkout event to its durable quote attempt.

    This runs only in the existing system-connection webhook transaction. The
    session must match the accepted current revision, the locally prepared
    session identity (when already persisted), and the tenant metadata placed
    by the Python Checkout service.
    """
    metadata = session.metadata
    attempt_id = metadata.get("quote_attempt_id")
    quote_id = metadata.get("custom_quote_id")
    revision_id = metadata.get("custom_quote_revision_id")
    session_id = session.reference.opaque_id
    subscription_id = session.subscription.opaque_id if session.subscription else None
    if (metadata.get("billing_kind") != "custom_quote" or metadata.get("tenant_id") != str(tenant_id)
            or not all((attempt_id, quote_id, revision_id, session_id, subscription_id))
            or not session.is_subscription
            or session.client_reference != attempt_id):
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


def _failure_reason(invoice: InvoiceSnapshot) -> str:
    return invoice.failure_reason or "The payment could not be collected."


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


def handle_event(sys_conn, event: VerifiedPaymentEvent, *, journey_handler=None) -> dict:
    """Processes one verified event, at most once at a time per event id.
    Returns {"duplicate": bool}."""
    if not isinstance(event, VerifiedPaymentEvent):
        raise TypeError("Reconciliation requires a verified payment event")
    from src.ai.billing.journey_webhooks import classify
    try:
        cohort = classify(sys_conn, event)
        sys_conn.commit()  # No cohort lookup transaction spans provider reads.
    except Exception:
        sys_conn.rollback()
        raise WebhookRetry('Journey classification unavailable') from None
    if cohort:
        if journey_handler is None:
            raise WebhookRetry('Protected journey reconciliation unavailable')
        try:
            return journey_handler(event)
        except Exception:
            raise WebhookRetry('Protected journey reconciliation pending') from None
    _lock_event(sys_conn, event.event_id)
    try:
        return _handle_locked(sys_conn, event)
    finally:
        _unlock_event(sys_conn, event.event_id)


def _handle_locked(sys_conn, event: VerifiedPaymentEvent) -> dict:
    created = event.occurred_at
    if not store.claim_payment_event(sys_conn, event):
        sys_conn.commit()
        return {"duplicate": True}
    sys_conn.commit()

    kind = event.kind
    tenant_id = None
    try:
        if kind == Kind.CHECKOUT_COMPLETED:
            session = event.checkout_snapshot
            if session and session.is_subscription and session.subscription:
                metadata = session.metadata
                custom_quote = metadata.get("billing_kind") == "custom_quote"
                hint = metadata.get("tenant_id") if custom_quote else (
                    session.client_reference or metadata.get("tenant_id"))
                if session.customer and hint and not store.tenant_for_customer(sys_conn, session.customer.opaque_id):
                    store.save_customer(sys_conn, hint, session.customer.opaque_id)
                tenant_id = sync_subscription(sys_conn, session.subscription, created, hint)
                if custom_quote:
                    _record_custom_checkout_session(sys_conn, session, tenant_id, event.event_id)
                else:
                    promotions.checkout_completed(sys_conn, session=session, tenant_id=tenant_id, stripe_event_id=event.event_id)
        elif kind == Kind.CHECKOUT_EXPIRED:
            session = event.checkout_snapshot
            if session is None:
                raise WebhookRetry("Checkout notification is missing its verified snapshot")
            if getattr(sys_conn, "verified_webhook_only", False):
                redemption = promotions._metadata_redemption(session)
                if redemption:
                    with sys_conn.cursor() as cur:
                        cur.execute("SELECT public.billing_provider_tenant(%s,%s)", ("promotion",redemption))
                        routed = cur.fetchone()[0]
                    if routed:
                        tenant_id = str(routed)
                        sys_conn.bind_tenant(tenant_id)
            promotions.checkout_expired(sys_conn, session=session, stripe_event_id=event.event_id)
        elif kind == Kind.SUBSCRIPTION_CHANGED:
            tenant_id = sync_subscription(sys_conn, event.subscription, created)
        elif kind in (Kind.INVOICE_SETTLED, Kind.INVOICE_FAILED):
            # Authenticated event snapshots can still be stale. Fetch current
            # invoice truth while serialized against other invoice events.
            invoice_id = event.invoice.opaque_id
            with sys_conn.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0));",
                               ("keel_stripe_invoice:" + invoice_id,))
            gateway = payment_gateway()
            invoice = gateway.get_invoice(event.invoice)
            if invoice.reference != event.invoice:
                raise WebhookRetry("invoice identity does not match the requested object")
            subscription_ref = invoice.subscription
            if event.subscription and event.subscription != subscription_ref:
                raise WebhookRetry("invoice subscription identity changed")
            if subscription_ref:
                subscription_id = subscription_ref.opaque_id
                tenant_id = sync_subscription(sys_conn, subscription_ref, created, invoice.tenant_hint)
                customer = invoice.customer.opaque_id if invoice.customer else None
                if customer and str(store.tenant_for_customer(sys_conn, customer)) != str(tenant_id):
                    raise WebhookRetry("invoice customer belongs to another company")
                if invoice.payment_state == PaymentState.PAID:
                    store.record_payment(sys_conn, tenant_id, invoice, subscription_id, "succeeded")
                    fresh_sub = gateway.get_subscription(subscription_ref)
                    if fresh_sub.metadata.get("billing_kind") == "custom_quote":
                        tenant_id = sync_subscription(sys_conn, subscription_ref, created,
                            invoice.tenant_hint, custom_payment_verified=True,
                            invoice_id=invoice_id, provider_event_id=event.event_id)
                    promotions.invoice_event(
                        sys_conn, tenant_id=tenant_id, invoice=invoice, subscription_id=subscription_id,
                        stripe_event_id=event.event_id, payment_succeeded=True,
                    )
                elif kind == Kind.INVOICE_FAILED:
                    store.record_payment(sys_conn, tenant_id, invoice, subscription_id, "failed", _failure_reason(invoice))
                    promotions.invoice_event(
                        sys_conn, tenant_id=tenant_id, invoice=invoice, subscription_id=subscription_id,
                        stripe_event_id=event.event_id, payment_succeeded=False,
                    )
                else:
                    raise WebhookRetry("paid invoice is not yet reconciled by the provider")
        elif kind == Kind.SCHEDULE_ENDED:
            if event.subscription:
                tenant_id = sync_subscription(sys_conn, event.subscription, created)
                store.set_schedule(sys_conn, tenant_id, event.subscription.opaque_id, None, None)
        # Any other event type is stored for the record and acknowledged.
        store.finish_event(sys_conn, event.event_id, tenant_id)
        sys_conn.commit()
        return {"duplicate": False}
    except Exception as err:
        sys_conn.rollback()
        logger.exception("Payment event %s (%s) failed", event.event_id, kind.value)
        store.finish_event(sys_conn, event.event_id, tenant_id, error=str(err)[:1000])
        sys_conn.commit()
        raise WebhookRetry(str(err)) from err
