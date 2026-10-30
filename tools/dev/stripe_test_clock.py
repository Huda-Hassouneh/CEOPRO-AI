"""Optional local adapter. Never copied into the backend production images.

No clock creation/advancement here: those remain explicit Stripe CLI operations.
No wall-clock patching, global tenant time, SQL writes, secrets in logs or fallback
customer creation when clock validation fails.
"""
from datetime import datetime, timezone
import os
import time

from src.ai.billing.test_clock import TestClockError


def plain(value):
    return value.to_dict() if hasattr(value, "to_dict") else value


def clock(client):
    clock_id = os.environ["STRIPE_TEST_CLOCK_ID"].strip()
    try:
        balance = plain(client.Balance.retrieve())
        result = plain(client.test_helpers.TestClock.retrieve(clock_id))
    except Exception:
        raise TestClockError("The configured Test Clock cannot be verified in this Stripe TEST account. Check the sandbox and clock ID.") from None
    if balance.get("livemode") is not False or result.get("livemode") is not False:
        raise TestClockError("Stripe returned LIVE or unverified mode; Test Clock operation refused.")
    if result.get("id") != clock_id or result.get("status") != "ready" or not isinstance(result.get("frozen_time"), int):
        raise TestClockError("The configured Test Clock must exist and be ready. Wait for advancement to finish before retrying.")
    return result


def creation_options(client):
    value = clock(client)
    # Signup trial dates are issued by the real database clock. Never attach
    # a new signup to already-advanced future time and silently skip its trial.
    # Past clock origins are allowed; the original absolute cutoff is retained.
    if value["frozen_time"] > time.time():
        raise TestClockError("This Test Clock is ahead of current UTC. New KEEL signups need a fresh clock; existing clock customers may continue after advancement.")
    return {"test_clock": value["id"]}


def validate_customer(customer, tenant_id, *, require_clock=True):
    customer = plain(customer)
    if (customer.get("deleted") or customer.get("livemode") is not False
            or (customer.get("metadata") or {}).get("tenant_id") != str(tenant_id)):
        raise TestClockError("Stripe Customer identity, tenant or TEST mode could not be verified.")
    attached = customer.get("test_clock")
    attached = attached.get("id") if isinstance(attached, dict) else attached
    if attached is None and not require_clock:
        return False
    if attached != os.environ["STRIPE_TEST_CLOCK_ID"].strip():
        raise TestClockError("Existing Stripe Customer has no matching Test Clock. Use a fresh KEEL test tenant; existing customers are never reassigned.")
    return True


def customer_time(client, customer_id, tenant_id, *, require_clock=True):
    try:
        customer = plain(client.Customer.retrieve(customer_id))
    except Exception:
        raise TestClockError("The existing Stripe Customer cannot be verified in this TEST account.") from None
    if customer.get("id") != customer_id:
        raise TestClockError("Stripe Customer identity mismatch; refusing Test Clock use.")
    if not validate_customer(customer, tenant_id, require_clock=require_clock):
        return None
    return datetime.fromtimestamp(clock(client)["frozen_time"], timezone.utc)
