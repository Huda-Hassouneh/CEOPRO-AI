"""Fail-closed bridge to a local-only adapter outside production Docker contexts.

Disabled mode imports no adapter, reads no clock ID and performs no provider/SQL
calls. The adapter under tools/dev is deliberately absent from backend images.
"""
import importlib.util
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

from fastapi import HTTPException


class TestClockError(HTTPException):
    def __init__(self, message):
        super().__init__(503, detail={"reason":"stripe_test_clock_configuration", "message":message})


def adapter():
    flag = os.getenv("STRIPE_TEST_CLOCK_ENABLED", "false").strip().lower()
    if flag in ("false", "0", "no", "off", ""):
        return None
    if flag not in ("true", "1", "yes", "on"):
        raise TestClockError("STRIPE_TEST_CLOCK_ENABLED must be true or false.")
    environments = [os.getenv(k, "").lower() for k in ("ENVIRONMENT", "APP_ENV", "SENTRY_ENVIRONMENT")]
    parsed = urlsplit(os.getenv("DATABASE_URL", ""))
    if (os.getenv("KEEL_DEV_ISOLATED") != "1" or os.getenv("KEEL_LOCAL_TEST_CLOCKS") != "1"
            or os.getenv("SENTRY_ENVIRONMENT") != "development"
            or any(v and v not in ("development", "dev", "test", "testing") for v in environments)
            or os.getenv("RENDER") or os.getenv("KUBERNETES_SERVICE_HOST")
            or parsed.hostname not in ("127.0.0.1", "localhost", "::1")):
        raise TestClockError("Stripe Test Clocks require the checkout-owned local development launcher; production/hosted use is forbidden.")
    if not os.getenv("STRIPE_SECRET_KEY", "").startswith(("sk_test_", "rk_test_")):
        raise TestClockError("Stripe Test Clocks require TEST/sandbox credentials; LIVE keys are forbidden.")
    clock = os.getenv("STRIPE_TEST_CLOCK_ID", "").strip()
    if not re.fullmatch(r"clock_[A-Za-z0-9]+", clock):
        raise TestClockError("Set a valid STRIPE_TEST_CLOCK_ID=clock_... or disable Stripe Test Clocks.")
    path = Path(__file__).resolve().parents[4] / "tools/dev/stripe_test_clock.py"
    if not path.is_file():
        raise TestClockError("The local Stripe Test Clock adapter is absent from this deployment; enabled mode is forbidden.")
    spec = importlib.util.spec_from_file_location("keel_local_stripe_test_clock", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def tenant_now(conn, tenant_id):
    local = adapter()
    if local is None:
        return None
    # This read is already available to the restricted tenant/accounting roles.
    # Never perform a cross-tenant customer lookup or use an administrative DSN.
    with conn.cursor() as cur:
        cur.execute("SELECT stripe_customer_id FROM billing_subscriptions WHERE tenant_id=%s ORDER BY created_at DESC LIMIT 1", (tenant_id,))
        row = cur.fetchone()
    if not row:
        return None
    from src.ai.billing import stripe_api
    return local.customer_time(stripe_api._client(), row[0], tenant_id, require_clock=False)
