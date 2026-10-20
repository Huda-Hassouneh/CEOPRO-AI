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

from src.ai.billing import store, stripe_api
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


def sync_subscription(sys_conn, subscription_id: str, event_created: datetime, hint: Optional[str] = None) -> Optional[str]:
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
                hint = obj.get("client_reference_id") or (obj.get("metadata") or {}).get("tenant_id")
                if obj.get("customer") and hint and not store.tenant_for_customer(sys_conn, obj["customer"]):
                    store.save_customer(sys_conn, hint, obj["customer"])
                tenant_id = sync_subscription(sys_conn, _id(obj["subscription"]), created, hint)
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
                elif event_type == "invoice.payment_failed":
                    store.record_payment(sys_conn, tenant_id, invoice, subscription_id, "failed", _failure_reason(invoice))
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
