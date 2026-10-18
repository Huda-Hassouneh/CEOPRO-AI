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
from src.ai.billing import config, store, stripe_api
from src.ai.billing.stripe_api import PaymentsNotConfigured


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


def create_checkout(conn, sys_conn, tenant_id: str, email: str, company_name: str,
                    plan_key: str, period_code: str) -> dict:
    _require_payments()
    if store.current_subscription(conn, tenant_id):
        raise BillingError(409, "subscription_exists", "Your company already has a subscription. Change plan instead.")
    price = _price_or_error(conn, plan_key, period_code)
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
        "allow_promotion_codes": True,
        "success_url": f"{base}/billing?checkout=success&session_id={{CHECKOUT_SESSION_ID}}",
        "cancel_url": f"{base}/billing?checkout=cancelled",
    }
    if config.automatic_tax():
        params["automatic_tax"] = {"enabled": True}
        params["customer_update"] = {"address": "auto", "name": "auto"}
    # Same company, plan and period within ~10 minutes -> the same session,
    # so a double click never opens two checkouts.
    bucket = int(time.time() // 600)
    key = hashlib.sha256(f"{tenant_id}:{plan_key}:{period_code}:{bucket}".encode()).hexdigest()[:40]
    session = stripe_api.create_checkout_session(params, idempotency_key=f"apex-checkout-{key}")
    return {"url": session["url"], "session_id": session["id"]}


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


def change_plan(conn, sys_conn, tenant_id: str, plan_key: str, period_code: str) -> dict:
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

    current_tier = store.plan_tier(conn, sub["plan_key"])
    current_price = store.current_price(conn, sub["plan_key"], sub["period_code"]) or {}
    is_upgrade = price["tier_level"] > current_tier or (
        price["tier_level"] == current_tier and price["amount"] >= current_price.get("amount", 0)
    )

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

