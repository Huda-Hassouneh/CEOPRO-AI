"""Billing settings, read from the environment each time (tests and
operators can change them without a restart of the module)."""
import os

ACCESS_STATUSES = ("active", "trialing")
CURRENT_STATUSES = ("trialing", "active", "past_due", "pending", "payment_failed", "paused")
TRIAL_PLAN_KEY_DEFAULT = "growth"  # plan catalog: Growth has the 14-day trial for new companies


def stripe_secret_key() -> str:
    return (os.getenv("STRIPE_SECRET_KEY") or "").strip()


def webhook_secret() -> str:
    return (os.getenv("STRIPE_WEBHOOK_SECRET") or "").strip()


def payments_enabled() -> bool:
    return bool(stripe_secret_key())


def app_base_url() -> str:
    from src.infrastructure.public_urls import frontend_origin
    return frontend_origin()


def trial_plan_key() -> str:
    return os.getenv("TRIAL_PLAN_KEY", TRIAL_PLAN_KEY_DEFAULT)


def automatic_tax() -> bool:
    return os.getenv("STRIPE_AUTOMATIC_TAX", "false").lower() == "true"
