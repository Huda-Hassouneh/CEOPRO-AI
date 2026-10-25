from datetime import datetime, timedelta, timezone

import pytest

from src.ai.billing import webhooks


class Cursor:
    def __init__(self, rows):
        self.rows = rows
        self.statements = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, query, params):
        self.statements.append((query, params))

    def fetchone(self):
        return self.rows.pop(0)


class Connection:
    def __init__(self, rows):
        self._cursor = Cursor(rows)

    def cursor(self):
        return self._cursor


def test_verified_custom_checkout_session_binds_only_current_accepted_attempt():
    expiry = datetime.now(timezone.utc) + timedelta(days=1)
    conn = Connection([("revision-1", "accepted", "accepted", expiry,
                        "cs_test_expected", None, "session_created")])
    session = {
        "id": "cs_test_expected", "mode": "subscription", "subscription": "sub_expected",
        "client_reference_id": "attempt-1",
        "metadata": {"billing_kind": "custom_quote", "tenant_id": "tenant-1",
                     "custom_quote_id": "quote-1", "custom_quote_revision_id": "revision-1",
                     "quote_attempt_id": "attempt-1"},
    }
    webhooks._record_custom_checkout_session(conn, session, "tenant-1", "evt_verified")
    statements = conn._cursor.statements
    assert len(statements) == 3
    assert "UPDATE public.billing_custom_quote_checkout_attempts" in statements[1][0]
    assert statements[1][1][:3] == ("cs_test_expected", "sub_expected", "evt_verified")
    assert "INSERT INTO public.billing_custom_quote_events" in statements[2][0]


def test_custom_checkout_session_rejects_mismatched_tenant_before_database_access():
    conn = Connection([])
    session = {"mode": "subscription", "id": "cs_test_x", "subscription": "sub_x",
               "client_reference_id": "attempt-1",
               "metadata": {"billing_kind": "custom_quote", "tenant_id": "other-tenant",
                            "custom_quote_id": "quote-1", "custom_quote_revision_id": "revision-1",
                            "quote_attempt_id": "attempt-1"}}
    with pytest.raises(webhooks.WebhookRetry):
        webhooks._record_custom_checkout_session(conn, session, "tenant-1", "evt_verified")
    assert conn._cursor.statements == []
