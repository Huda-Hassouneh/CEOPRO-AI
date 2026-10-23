import hashlib
import hmac
import json
import time
from datetime import UTC, datetime, timedelta

import pytest
from src.ai.billing import config, service, store, stripe_api
from stripe import SignatureVerificationError


def signed(payload, secret, timestamp=None):
    timestamp = int(time.time()) if timestamp is None else timestamp
    digest = hmac.new(
        secret.encode(), str(timestamp).encode() + b"." + payload, hashlib.sha256
    ).hexdigest()
    return f"t={timestamp},v1={digest}"


def test_signed_event_is_verified_by_the_actual_stripe_sdk():
    payload = json.dumps(
        {"id": "evt_offline", "object": "event", "type": "ping", "livemode": False}
    ).encode()
    event = stripe_api.construct_event(
        payload, signed(payload, "whsec_offline"), "whsec_offline"
    )
    assert event["id"] == "evt_offline"


@pytest.mark.parametrize("kind", ["wrong_secret", "tampered_body", "expired"])
def test_signature_rejects_invalid_body_or_timestamp(kind):
    payload = b'{"id":"evt_offline","object":"event"}'
    header = signed(
        payload,
        "whsec_wrong" if kind == "wrong_secret" else "whsec_offline",
        int(time.time()) - 1000 if kind == "expired" else None,
    )
    if kind == "tampered_body":
        payload += b" "
    with pytest.raises(SignatureVerificationError):
        stripe_api.construct_event(payload, header, "whsec_offline")


@pytest.mark.parametrize("header", [None, "invalid"])
def test_webhook_rejects_missing_or_invalid_signature_before_database(
    client, monkeypatch, header
):
    from src.ai import db

    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_offline")
    monkeypatch.setattr(
        db,
        "system_connection",
        lambda: pytest.fail("Bad signature reached the database"),
    )
    response = client.post(
        "/billing/webhook",
        content=b"{}",
        headers={"Stripe-Signature": header} if header else {},
    )
    assert response.status_code == 400


def test_webhook_not_configured_is_503(client, monkeypatch):
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
    assert client.post("/billing/webhook", content=b"{}").status_code == 503


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/billing/subscription"),
        ("post", "/billing/checkout"),
        ("post", "/billing/cancel"),
        ("post", "/billing/resume"),
        ("get", "/billing/invoices"),
    ],
)
def test_existing_billing_routes_require_authentication(client, method, path):
    response = (
        getattr(client, method)(
            path, json={"plan_key": "growth", "period_code": "monthly"}
        )
        if method == "post"
        else client.get(path)
    )
    assert response.status_code == 401
    assert "detail" in response.json()


def test_checkout_preserves_existing_contract_and_provider_idempotency(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_offline")
    monkeypatch.setenv("APP_BASE_URL", "https://keel.example.test")
    monkeypatch.setattr(store, "current_subscription", lambda *args: None)
    monkeypatch.setattr(
        store,
        "current_price",
        lambda *args: {
            "is_active": True,
            "self_serve": True,
            "stripe_price_id": "price_existing",
        },
    )
    monkeypatch.setattr(store, "customer_id", lambda *args: "cus_existing")
    monkeypatch.setattr(store, "trial", lambda *args: None)
    calls = []
    monkeypatch.setattr(
        stripe_api,
        "create_checkout_session",
        lambda params, idempotency_key: (
            calls.append((params, idempotency_key))
            or {"id": "cs_test_offline", "url": "https://checkout.stripe.com/offline"}
        ),
    )
    monkeypatch.setattr(service.time, "time", lambda: 1800000000)
    one = service.create_checkout(
        None,
        None,
        "tenant-existing",
        "owner@example.test",
        "Store",
        "growth",
        "monthly",
    )
    two = service.create_checkout(
        None,
        None,
        "tenant-existing",
        "owner@example.test",
        "Store",
        "growth",
        "monthly",
    )
    assert (
        one
        == two
        == {
            "url": "https://checkout.stripe.com/offline",
            "session_id": "cs_test_offline",
        }
    )
    assert calls[0] == calls[1]
    params = calls[0][0]
    assert params["customer"] == "cus_existing"
    assert params["subscription_data"]["metadata"]["tenant_id"] == "tenant-existing"
    assert params["line_items"] == [{"price": "price_existing", "quantity": 1}]
    assert params["allow_promotion_codes"] is True
    assert params["success_url"].startswith(
        "https://keel.example.test/billing?checkout=success"
    )


def test_checkout_does_not_create_a_second_current_subscription(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_offline")
    monkeypatch.setattr(
        store, "current_subscription", lambda *args: {"status": "active"}
    )
    with pytest.raises(service.BillingError) as error:
        service.create_checkout(
            None, None, "tenant", "owner@example.test", "Store", "growth", "monthly"
        )
    assert error.value.code == "subscription_exists"


def test_missing_stripe_key_has_controlled_failure(monkeypatch):
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    assert not config.payments_enabled()
    with pytest.raises(service.BillingError) as error:
        service.create_checkout(
            None, None, "tenant", "owner@example.test", "Store", "growth", "monthly"
        )
    assert (error.value.status, error.value.code) == (503, "payments_not_configured")


@pytest.mark.parametrize("trialing", [False, True])
def test_existing_upgrade_preserves_trial_or_waits_for_payment(monkeypatch, trialing):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_offline")
    monkeypatch.setattr(store, "has_custom_contract", lambda *a: False)
    plan_rights = {
        "source": "stripe",
        "features": {
            "test_feature": {
                "unit": "items",
                "aggregation_type": "sum",
                "reset_cycle": "billing_period",
                "limit": 10,
            }
        },
        "entitlements": set(),
    }
    monkeypatch.setattr(service.usage, "get_plan", lambda *a: plan_rights)
    monkeypatch.setattr(store, "configured_plan_rights", lambda *a, **kw: plan_rights)
    sub = {
        "stripe_subscription_id": "sub_existing",
        "plan_key": "growth",
        "period_code": "monthly",
        "status": "trialing" if trialing else "active",
        "cancel_at_period_end": False,
        "scheduled_plan_key": None,
        "scheduled_period_code": None,
    }
    monkeypatch.setattr(store, "current_subscription", lambda *a: sub)
    monkeypatch.setattr(
        store,
        "current_price",
        lambda conn, key, period: {
            "is_active": True,
            "self_serve": True,
            "stripe_price_id": "price_target"
            if key == "enterprise"
            else "price_current",
            "tier_level": 3 if key == "enterprise" else 2,
            "amount": 350 if key == "enterprise" else 140,
        },
    )
    monkeypatch.setattr(store, "plan_tier", lambda *a: 2)
    live = {
        "status": sub["status"],
        "trial_end": 1900000000 if trialing else None,
        "schedule": None,
        "items": {"data": [{"id": "si_existing"}]},
    }
    monkeypatch.setattr(stripe_api, "retrieve_subscription", lambda sid: live)
    calls = []
    monkeypatch.setattr(
        stripe_api,
        "modify_subscription",
        lambda sid, **kw: (
            calls.append(kw)
            or (
                {
                    "pending_update": {"expires_at": 1900000000},
                    "latest_invoice": "in_action",
                }
                if not trialing
                else {}
            )
        ),
    )
    monkeypatch.setattr(
        stripe_api,
        "retrieve_invoice",
        lambda iid: {"hosted_invoice_url": "https://invoice.stripe.com/test"},
    )
    monkeypatch.setattr(store, "set_schedule", lambda *a: None)

    class Connection:
        def commit(self):
            pass

    result = service.change_plan(None, Connection(), "tenant", "enterprise", "monthly")
    if trialing:
        assert (
            calls[0]["trial_end"] == 1900000000
            and calls[0]["proration_behavior"] == "none"
        )
        assert result["state"] == "applied"
    else:
        assert calls[0]["payment_behavior"] == "pending_if_incomplete"
        assert calls[0]["proration_behavior"] == "always_invoice"
        assert result["state"] == "payment_required" and result[
            "payment_url"
        ].startswith("https://invoice.stripe.com/")


def test_existing_downgrade_is_scheduled_without_replacing_paid_period(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_offline")
    monkeypatch.setattr(store, "has_custom_contract", lambda *a: False)
    plan_rights = {
        "source": "stripe",
        "features": {
            "test_feature": {
                "unit": "items",
                "aggregation_type": "sum",
                "reset_cycle": "billing_period",
                "limit": 10,
            }
        },
        "entitlements": set(),
    }
    monkeypatch.setattr(service.usage, "get_plan", lambda *a: plan_rights)
    monkeypatch.setattr(store, "configured_plan_rights", lambda *a, **kw: plan_rights)
    end = datetime.now(UTC) + timedelta(days=20)
    sub = {
        "stripe_subscription_id": "sub_existing",
        "plan_key": "enterprise",
        "period_code": "monthly",
        "status": "active",
        "cancel_at_period_end": False,
        "scheduled_plan_key": None,
        "scheduled_period_code": None,
        "current_period_end": end,
    }
    monkeypatch.setattr(store, "current_subscription", lambda *a: sub)
    monkeypatch.setattr(
        store,
        "current_price",
        lambda conn, key, period: {
            "is_active": True,
            "self_serve": True,
            "stripe_price_id": "price_target",
            "tier_level": 1 if key == "starter" else 3,
            "amount": 55 if key == "starter" else 350,
        },
    )
    monkeypatch.setattr(store, "plan_tier", lambda *a: 3)
    monkeypatch.setattr(
        stripe_api,
        "retrieve_subscription",
        lambda sid: {"schedule": None, "items": {"data": [{"id": "si_existing"}]}},
    )
    monkeypatch.setattr(
        stripe_api,
        "create_schedule_from_subscription",
        lambda sid: {"id": "sched_test"},
    )
    phase = {
        "start_date": int(time.time()) - 10,
        "end_date": int(end.timestamp()),
        "items": [{"price": {"id": "price_current"}, "quantity": 1}],
    }
    monkeypatch.setattr(
        stripe_api,
        "retrieve_schedule",
        lambda sid: {"current_phase": phase, "phases": [phase]},
    )
    calls = []
    monkeypatch.setattr(
        stripe_api, "modify_schedule", lambda sid, **kw: calls.append(kw)
    )
    schedules = []
    monkeypatch.setattr(store, "set_schedule", lambda *a: schedules.append(a))

    class Connection:
        def commit(self):
            pass

    result = service.change_plan(None, Connection(), "tenant", "starter", "monthly")
    assert result["state"] == "scheduled" and result["timing"] == "period_end"
    assert calls[0]["phases"][0]["end_date"] == int(end.timestamp())
    assert calls[0]["phases"][1]["items"] == [{"price": "price_target", "quantity": 1}]
    assert schedules[0][-2:] == ("starter", "monthly")


def test_revoked_main_token_is_rejected_before_billing_database(client, monkeypatch):
    import uuid

    from src.ai import db
    from src.ai.core import security

    token, _ = security.create_access_token(
        str(uuid.uuid4()), str(uuid.uuid4()), email_verified=True
    )
    monkeypatch.setattr(
        security,
        "is_token_revoked",
        lambda token_id, fail_closed=False: True,
    )
    monkeypatch.setattr(
        db,
        "app_role_connection",
        lambda *args: pytest.fail("Revoked token reached billing"),
    )
    response = client.get(
        "/billing/invoices", headers={"Authorization": "Bearer " + token}
    )
    assert response.status_code == 401


def test_invalid_main_token_is_rejected_before_billing_database(client, monkeypatch):
    from src.ai import db

    monkeypatch.setattr(
        db,
        "app_role_connection",
        lambda *args: pytest.fail("Invalid token reached billing"),
    )
    assert (
        client.get(
            "/billing/invoices", headers={"Authorization": "Bearer invalid-test-token"}
        ).status_code
        == 401
    )
