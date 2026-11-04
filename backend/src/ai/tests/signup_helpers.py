from unittest.mock import patch
from contextlib import contextmanager


@contextmanager
def _disposable_connection():
    """Explicit fixtures never fall back to the normal application database."""
    import os
    import psycopg2
    from scripts.billing_verification import validate_test_environment

    conn = psycopg2.connect(validate_test_environment(dict(os.environ), database=True))
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def install_paid_plan_fixture(session, plan_key, *, onboarding_complete=False):
    """Arrange access for feature tests, separately from real verified signup.

    This is synthetic paid/manual state, not a fresh trial or provider acceptance.
    The public signup helper below deliberately continues to grant zero access.
    """
    with _disposable_connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO tenant_plan_assignments(tenant_id,plan_key,status,source,current_period_start,current_period_end) "
            "VALUES(%s,%s,'active','manual',CURRENT_DATE,(CURRENT_DATE+INTERVAL '1 month')::date)",
            (session['tenant_id'], plan_key),
        )
        if onboarding_complete:
            cursor.execute("UPDATE companies SET onboarding_completed_at=now() WHERE tenant_id=%s", (session['tenant_id'],))


def install_historical_trial_fixture(session, plan_key):
    """Represent an already-issued trial; never a new customer activation path."""
    from src.ai.billing import store

    with _disposable_connection() as conn:
        assert store.start_trial(conn, session['tenant_id'],
                                 started_by_user_id=session['user_id'], plan_key=plan_key)


def create_verified_test_account(client, payload):
    """Exercise the current pending-registration and email-verification flow."""
    sent_codes = []
    with patch(
        "src.ai.core.notifications.send_email_verification_email",
        side_effect=lambda _email, code: sent_codes.append(code) or True,
    ):
        pending = client.post("/auth/signup", json=payload)

    assert pending.status_code == 202, pending.text
    registration = pending.json()
    assert registration["status"] == "pending_verification"
    assert registration["delivery"] == "sent"
    assert sent_codes

    response = client.post(
        "/auth/email/verify",
        json={
            "email": registration["email"],
            "registration_token": registration["registration_token"],
            "code": sent_codes[-1],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()
