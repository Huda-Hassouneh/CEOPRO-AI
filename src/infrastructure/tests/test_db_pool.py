"""
Offline tests for db_pool.py's PooledTenantConnection/TenantConnectionPool -
the wrapper logic that makes pooled connections RLS-safe (SET LOCAL
re-applied after every commit/rollback, never returning a connection to
the pool mid-transaction, discarding rather than reusing a broken one).
All doubles here mirror psycopg2's real interface closely enough to prove
the wrapper's own logic is correct; the real proof against actual RLS
enforcement under real concurrent pooled reuse is
test_db_pool_integration_db.py (skipped unless AI_TEST_DATABASE_URL and
APP_DB_PASSWORD are set - RLS provides no protection when verified only
against a superuser connection, see test_rls_integration_db.py's own
docstring for why).
"""
import psycopg2
import pytest

from src.infrastructure.db_pool import PooledTenantConnection, TenantConnectionPool


class FakeCursor:
    def __init__(self, calls):
        self._calls = calls

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, query, params=None):
        self._calls.append((" ".join(query.split()), params))


class FakeRawConnection:
    def __init__(self, transaction_status=psycopg2.extensions.TRANSACTION_STATUS_IDLE):
        self.calls = []
        self.autocommit = None
        self.commit_count = 0
        self.rollback_count = 0
        self.closed = False
        self._transaction_status = transaction_status

    def cursor(self):
        return FakeCursor(self.calls)

    def commit(self):
        self.commit_count += 1

    def rollback(self):
        self.rollback_count += 1

    def get_transaction_status(self):
        return self._transaction_status


class FakePool:
    def __init__(self):
        self.putconn_calls = []

    def putconn(self, raw_conn, discard=False):
        self.putconn_calls.append((raw_conn, discard))


def _set_config_calls(raw_conn):
    return [c for c in raw_conn.calls if c[0].startswith("SELECT set_config")]


def test_init_applies_tenant_and_user_context_via_set_local(monkeypatch):
    raw = FakeRawConnection()
    pool = FakePool()

    conn = PooledTenantConnection(pool, raw, tenant_id="tenant-1", user_id="user-1")

    assert raw.autocommit is False
    assert _set_config_calls(raw) == [
        ("SELECT set_config('app.current_tenant_id', %s, true);", ("tenant-1",)),
        ("SELECT set_config('app.current_user_id', %s, true);", ("user-1",)),
    ]
    assert conn is not None  # constructed without error


def test_commit_reapplies_context_for_the_next_transaction():
    """
    The real fix this covers: main.py's upload endpoint commits more than
    once on the SAME connection within one request. A bare SET LOCAL
    issued only at checkout would be wiped out by the FIRST commit,
    silently leaving every later statement with no tenant context.
    """
    raw = FakeRawConnection()
    pool = FakePool()
    conn = PooledTenantConnection(pool, raw, "tenant-1", "user-1")
    initial_call_count = len(raw.calls)

    conn.commit()

    assert raw.commit_count == 1
    assert len(_set_config_calls(raw)) == 4  # 2 from init + 2 re-applied after commit
    assert len(raw.calls) == initial_call_count + 2


def test_rollback_reapplies_context_for_the_next_transaction():
    raw = FakeRawConnection()
    pool = FakePool()
    conn = PooledTenantConnection(pool, raw, "tenant-1", "user-1")

    conn.rollback()

    assert raw.rollback_count == 1
    assert len(_set_config_calls(raw)) == 4


def test_close_returns_idle_connection_to_pool_without_rollback():
    raw = FakeRawConnection(transaction_status=psycopg2.extensions.TRANSACTION_STATUS_IDLE)
    pool = FakePool()
    conn = PooledTenantConnection(pool, raw, "tenant-1", "user-1")

    conn.close()

    assert raw.rollback_count == 0  # nothing to roll back - already idle
    assert pool.putconn_calls == [(raw, False)]  # returned, not discarded


def test_close_rolls_back_a_connection_left_mid_transaction_before_returning_it():
    """
    Never return a connection to the pool with an open transaction - a
    later, unrelated checkout reusing it would inherit whatever
    uncommitted state (and, before this whole redesign, whatever RLS
    context) was left on it.
    """
    raw = FakeRawConnection(transaction_status=psycopg2.extensions.TRANSACTION_STATUS_INTRANS)
    pool = FakePool()
    conn = PooledTenantConnection(pool, raw, "tenant-1", "user-1")

    conn.close()

    assert raw.rollback_count == 1
    assert pool.putconn_calls == [(raw, False)]


def test_close_discards_a_broken_connection_instead_of_returning_it():
    class BrokenRawConnection(FakeRawConnection):
        def get_transaction_status(self):
            raise psycopg2.OperationalError("server closed the connection unexpectedly")

    raw = BrokenRawConnection()
    pool = FakePool()
    conn = PooledTenantConnection(pool, raw, "tenant-1", "user-1")

    conn.close()

    assert pool.putconn_calls == [(raw, True)]  # discard=True - never handed back for reuse


def test_close_is_idempotent():
    raw = FakeRawConnection()
    pool = FakePool()
    conn = PooledTenantConnection(pool, raw, "tenant-1", "user-1")

    conn.close()
    conn.close()

    assert len(pool.putconn_calls) == 1  # the second close() is a no-op, not a double-return


def test_cursor_raises_after_close():
    raw = FakeRawConnection()
    pool = FakePool()
    conn = PooledTenantConnection(pool, raw, "tenant-1", "user-1")
    conn.close()

    with pytest.raises(psycopg2.InterfaceError, match="closed"):
        conn.cursor()


def test_context_manager_closes_on_exit():
    raw = FakeRawConnection()
    pool = FakePool()

    with PooledTenantConnection(pool, raw, "tenant-1", "user-1") as conn:
        assert conn is not None

    assert pool.putconn_calls == [(raw, False)]


def test_get_tenant_connection_retries_once_on_a_stale_pooled_connection(monkeypatch):
    """A pool doesn't validate connections on checkout - a stale one
    (server-side idle timeout, a network blip) is a real, expected
    occurrence, not a rare edge case worth leaving unhandled."""
    stale_raw = FakeRawConnection()
    fresh_raw = FakeRawConnection()
    connections = iter([stale_raw, fresh_raw])

    pool = TenantConnectionPool.__new__(TenantConnectionPool)  # skip __init__'s real psycopg2.pool creation
    pool._pool = type("FakeInnerPool", (), {
        "getconn": lambda self: next(connections),
        "putconn": lambda self, c, close=False: None,
    })()
    pool._exhaustion_retry_attempts = 1
    pool._exhaustion_retry_backoff_seconds = 0

    call_count = {"n": 0}
    real_apply = PooledTenantConnection._apply_tenant_context

    def flaky_apply(self):
        call_count["n"] += 1
        if self._raw is stale_raw:
            raise psycopg2.OperationalError("server closed the connection unexpectedly")
        return real_apply(self)

    monkeypatch.setattr(PooledTenantConnection, "_apply_tenant_context", flaky_apply)

    conn = pool.get_tenant_connection("tenant-1", "user-1")

    assert conn._raw is fresh_raw  # the stale one was discarded, a fresh one used instead
    assert call_count["n"] == 2


def test_get_tenant_connection_propagates_a_second_consecutive_failure(monkeypatch):
    """Two failures in a row is a real outage, not a one-off stale
    connection - must not retry forever or hide the failure."""
    pool = TenantConnectionPool.__new__(TenantConnectionPool)
    pool._pool = type("FakeInnerPool", (), {
        "getconn": lambda self: FakeRawConnection(),
        "putconn": lambda self, c, close=False: None,
    })()
    pool._exhaustion_retry_attempts = 1
    pool._exhaustion_retry_backoff_seconds = 0

    def always_fails(self):
        raise psycopg2.OperationalError("server closed the connection unexpectedly")

    monkeypatch.setattr(PooledTenantConnection, "_apply_tenant_context", always_fails)

    with pytest.raises(psycopg2.OperationalError):
        pool.get_tenant_connection("tenant-1", "user-1")


def test_checkout_retries_with_backoff_on_transient_pool_exhaustion(monkeypatch):
    """
    A genuine psycopg2.pool.ThreadedConnectionPool limitation: getconn()
    raises PoolError immediately when exhausted rather than waiting -
    confirmed the hard way under real concurrent load in
    test_db_pool_integration_db.py before this retry existed. A brief
    burst above maxconn should wait briefly for a connection to free up,
    not fail instantly.
    """
    import psycopg2.pool

    pool = TenantConnectionPool.__new__(TenantConnectionPool)
    attempts = {"n": 0}

    def flaky_getconn(self):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise psycopg2.pool.PoolError("connection pool exhausted")
        return FakeRawConnection()

    pool._pool = type("FakeInnerPool", (), {"getconn": flaky_getconn})()
    pool._exhaustion_retry_attempts = 5
    pool._exhaustion_retry_backoff_seconds = 0  # no real delay in the test suite

    raw = pool._checkout()

    assert attempts["n"] == 3  # succeeded on the third attempt, not the first
    assert isinstance(raw, FakeRawConnection)


def test_checkout_propagates_pool_error_after_exhausting_retries(monkeypatch):
    """A pool that stays exhausted for the whole retry window is a real
    capacity problem, not a brief burst - must fail loudly, not hang or
    silently give up with an unrelated error."""
    import psycopg2.pool

    pool = TenantConnectionPool.__new__(TenantConnectionPool)
    attempts = {"n": 0}

    def always_exhausted(self):
        attempts["n"] += 1
        raise psycopg2.pool.PoolError("connection pool exhausted")

    pool._pool = type("FakeInnerPool", (), {"getconn": always_exhausted})()
    pool._exhaustion_retry_attempts = 3
    pool._exhaustion_retry_backoff_seconds = 0

    with pytest.raises(psycopg2.pool.PoolError):
        pool._checkout()
    assert attempts["n"] == 3  # tried exactly the configured number of times, not fewer or more
