"""Pooled pre-authentication lookups (db.auth_lookup_session) against a real Postgres."""
import os

import psycopg2
import pytest

DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL or not os.getenv("APP_DB_PASSWORD"),
                                reason="AI_TEST_DATABASE_URL/APP_DB_PASSWORD not set - skipping live-DB test")

from src.ai import db  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_pool(monkeypatch):
    monkeypatch.setenv("AUTH_LOOKUP_POOL_MAX_SIZE", "2")
    monkeypatch.setattr(db, "_AUTH_LOOKUP_POOL", None)
    yield
    if db._AUTH_LOOKUP_POOL is not None:
        db._AUTH_LOOKUP_POOL.closeall()


def _backend_pid(conn):
    with conn.cursor() as cursor:
        cursor.execute("SELECT pg_backend_pid(), current_user, current_setting('app.auth_lookup', true), "
                       "current_setting('app.current_tenant', true);")
        return cursor.fetchone()


def test_connections_are_reused_with_the_restricted_role_and_no_tenant_context():
    with db.auth_lookup_session() as conn:
        first = _backend_pid(conn)
    with db.auth_lookup_session() as conn:
        second = _backend_pid(conn)
    assert first[0] == second[0], "the second request reused the pooled connection"
    assert second[1] == "ceopro_app" and second[2] == "on" and not second[3]


def test_a_connection_the_server_closed_is_replaced_transparently():
    with db.auth_lookup_session() as conn:
        pid = _backend_pid(conn)[0]
    with psycopg2.connect(DATABASE_URL) as admin, admin.cursor() as cursor:
        cursor.execute("SELECT pg_terminate_backend(%s);", (pid,))
    with db.auth_lookup_session() as conn:  # e.g. an idle timeout or a database restart
        assert _backend_pid(conn)[0] != pid


def test_a_full_pool_falls_back_to_a_fresh_connection_instead_of_waiting():
    sessions = [db.auth_lookup_session() for _ in range(3)]
    conns = [s.__enter__() for s in sessions]
    try:
        assert len({_backend_pid(c)[0] for c in conns}) == 3
        assert [s._pooled for s in sessions] == [True, True, False]
    finally:
        for s in sessions:
            s.__exit__(None, None, None)
    assert conns[2].closed, "the overflow connection is closed, not pooled"


def test_an_uncommitted_change_is_rolled_back_before_reuse():
    with db.auth_lookup_session() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT set_config('app.current_tenant', '00000000-0000-0000-0000-00000000abcd', true);")
    with db.auth_lookup_session() as conn:
        assert not _backend_pid(conn)[3]
