"""Focused regression cases for authentication and platform stabilization."""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import jwt
import pytest
from fastapi import HTTPException
from psycopg2 import OperationalError

from src.ai.core import pending_registration, security
from src.ai.platform import service
from src.ai.routers import auth


def test_login_does_not_upgrade_an_old_password_to_a_new_credential_version(api, monkeypatch):
    conn = MagicMock()
    monkeypatch.setattr(auth.db, "auth_lookup_connection", lambda: conn)
    monkeypatch.setattr(
        auth,
        "_fetch_login_identity",
        lambda *args: ("u", "old-hash", "Owner", "en", 0),
        raising=False,
    )
    monkeypatch.setattr(auth, "verify_password", lambda *args: True)
    monkeypatch.setattr(auth, "_fetch_user_memberships", lambda *args: [("t", "owner", "Shop")])
    monkeypatch.setattr(auth, "_email_verified", lambda *args: True)
    monkeypatch.setattr(auth, "_credential_version", lambda *args: 1)

    result = api.post("/auth/login", json={"email": "a@example.test", "password": "old-password"})

    assert result.status_code == 200
    claims = jwt.decode(result.json()["access_token"], security._JWT_SECRET, algorithms=["HS256"])
    assert claims["cv"] == 0


def test_refresh_cannot_cross_a_concurrent_password_reset(monkeypatch):
    conn = MagicMock()
    monkeypatch.setattr(auth.db, "auth_lookup_connection", lambda: conn)
    monkeypatch.setattr(auth, "_fetch_user_memberships", lambda *args: [("t", "owner", "Shop")])
    monkeypatch.setattr(auth, "_email_verified", lambda *args: True)
    monkeypatch.setattr(auth, "_credential_version", lambda *args: 1)
    ctx = SimpleNamespace(
        tenant_id="t",
        user_id="u",
        credential_version=0,
        auth_time=datetime.now(timezone.utc).timestamp(),
    )

    with pytest.raises(HTTPException) as error:
        auth.refresh(ctx)

    assert error.value.status_code == 401


def test_workspace_session_cannot_upgrade_a_stale_credential_version(monkeypatch):
    conn = MagicMock()
    monkeypatch.setattr(auth.db, "auth_lookup_connection", lambda: conn)
    monkeypatch.setattr(auth, "_email_verified", lambda *args: True)
    monkeypatch.setattr(auth, "_credential_version", lambda *args: 2)

    with pytest.raises(HTTPException) as error:
        auth._session("t", "u", "owner", "Shop", "Owner", "en", credential_version=1)

    assert error.value.status_code == 401


def test_logout_receipt_covers_the_entire_signed_token_lifetime(monkeypatch):
    now = 1000.75

    class Clock:
        @staticmethod
        def now(*args):
            return datetime.fromtimestamp(now, timezone.utc)

        @staticmethod
        def fromtimestamp(value, *args):
            return datetime.fromtimestamp(value, timezone.utc)

    monkeypatch.setattr(security, "datetime", Clock)
    store = MagicMock()
    store.set.return_value = True
    receipt = []
    monkeypatch.setattr(security, "_revocation_store", lambda: store)
    monkeypatch.setattr(
        security,
        "_durable_revocation",
        lambda token, expiry: (receipt.append(expiry) or True),
    )

    assert security.revoke_token("signed-jti", 1002) is True
    assert receipt[0].timestamp() >= 1002
    assert store.set.call_args.kwargs["ex"] >= 2


def test_negative_durable_write_acknowledgment_is_not_a_successful_logout(monkeypatch):
    store = MagicMock()
    store.set.return_value = True
    monkeypatch.setattr(security, "_revocation_store", lambda: store)
    monkeypatch.setattr(security, "_durable_revocation", lambda *args: False)

    with pytest.raises(HTTPException) as error:
        security.revoke_token("jti", None)

    assert error.value.status_code == 503
    assert not store.set.called


@pytest.mark.parametrize("target", ["pending", "platform"])
def test_database_connection_failure_has_retryable_contract(api, monkeypatch, token, target):
    def unavailable(*args):
        raise OperationalError("fixture DB unavailable")

    if target == "pending":
        monkeypatch.setattr(pending_registration.db, "auth_lookup_connection", unavailable)
        result = api.post(
            "/auth/signup",
            json={
                "email": "a@example.test",
                "password": "StrongPass1!",
                "full_name": "Name",
                "business_name": "Shop",
                "country_code": "JO",
                "primary_currency": "JOD",
            },
        )
    else:
        monkeypatch.setattr(service.db, "app_role_connection", unavailable)
        result = api.get("/platform/overview", headers=token)

    assert result.status_code == 503


def test_operator_invitation_preserves_password_bytes(api, monkeypatch):
    plain = "  StrongPass1!  "
    seen = []

    def accept(token, payload=None):
        seen.append(payload)
        return {
            "tenant_id": "t",
            "user_id": "u",
            "business_name": "Platform",
            "full_name": "Name",
            "email": "x@example.test",
        }

    monkeypatch.setattr(service, "invitation", accept)
    monkeypatch.setattr(auth, "_session", lambda *args: {"access_token": "python"})

    result = api.post(
        "/platform/invitations/nonce/accept",
        json={"full_name": " Name ", "password": plain},
    )

    assert result.status_code == 200
    assert security.verify_password(plain, seen[0]["password_hash"])
    assert seen[0]["full_name"] == "Name"


def test_membership_restore_reads_existing_entitlement_authority_under_transaction(monkeypatch):
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchone.side_effect = [({"tenant_id": "customer"},), ({"active": True},)]
    monkeypatch.setattr(service.db, "app_role_connection", lambda *args: conn)
    calls = []
    monkeypatch.setattr(
        auth,
        "_seat_limit",
        lambda tenant_id: (calls.append((tenant_id, conn.commit.call_count)) or 3),
    )
    ctx = SimpleNamespace(tenant_id="platform", user_id="operator")

    result = service.command(
        ctx,
        "membership_status",
        {"id": "member", "active": True, "reason": "restore"},
    )

    assert result["active"] is True
    assert calls == [("customer", 0)]
    assert cursor.execute.call_args_list[-1].args[1][1].adapted["_seat_limit"] == 3
    conn.commit.assert_called_once()


def test_membership_restore_refusal_is_audited_without_domain_mutation(monkeypatch):
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = ({"tenant_id": "customer"},)
    monkeypatch.setattr(service.db, "app_role_connection", lambda *args: conn)

    def inactive(*args):
        raise HTTPException(402, "Existing subscription inactive")

    monkeypatch.setattr(auth, "_seat_limit", inactive)
    ctx = SimpleNamespace(tenant_id="p", user_id="u")

    with pytest.raises(HTTPException) as error:
        service.command(
            ctx,
            "membership_status",
            {"id": "member", "active": True, "reason": "restore"},
        )

    assert error.value.status_code == 402
    assert "keel_platform_record_attempt" in cursor.execute.call_args.args[0]
    conn.commit.assert_called_once()


def test_real_context_keeps_validated_credential_version(monkeypatch):
    raw, _ = security.create_access_token("t", "u", credential_version=4)
    monkeypatch.setattr(security, "is_token_revoked", lambda *args: False)
    seen = []
    monkeypatch.setattr(security, "assert_active_principal", lambda *args: seen.append(args))

    ctx = security.get_tenant_context(authorization="Bearer " + raw)

    assert ctx.credential_version == 4
    assert seen == [("t", "u", 4)]
