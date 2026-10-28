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
import re
import threading

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


def _settings(calls):
    """Each set_config in the given statements as {name: value}, in order (one
    statement may set several)."""
    settings = []
    for query, params in calls:
        if query.startswith("SELECT set_config"):
            names = re.findall(r"set_config\('([^']+)', %s, true\)", query)
            settings.extend(zip(names, params))
    return settings


@pytest.fixture(autouse=True)
def _no_cached_time_zones():
    from src.infrastructure import db_pool

    db_pool._tenant_timezones.clear()
    yield
    db_pool._tenant_timezones.clear()


def test_init_applies_tenant_and_user_context_via_set_local(monkeypatch):
    raw = FakeRawConnection()
    pool = FakePool()

    conn = PooledTenantConnection(pool, raw, tenant_id="tenant-1", user_id="user-1")

    assert raw.autocommit is False
    assert _settings(raw.calls) == [
        ("app.current_tenant_id", "tenant-1"),
        ("app.current_user_id", "user-1"),
        ("app.lang", "en"),
        # No companies row behind this fake connection: the business
        # calendar falls back to UTC.
        ("TimeZone", "UTC"),
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
    with conn.cursor() as cursor:  # the next statement of the next transaction
        cursor.execute("SELECT 1;")

    assert raw.commit_count == 1
    after_commit = raw.calls[initial_call_count:-1]
    assert dict(_settings(after_commit)) == {"app.current_tenant_id": "tenant-1", "app.current_user_id": "user-1",
                                             "app.lang": "en", "TimeZone": "UTC"}
    # The time zone is cached per tenant, so re-applying is one round trip.
    assert len(after_commit) == 1


def test_rollback_reapplies_context_for_the_next_transaction():
    raw = FakeRawConnection()
    pool = FakePool()
    conn = PooledTenantConnection(pool, raw, "tenant-1", "user-1")

    conn.rollback()
    conn.cursor()

    assert raw.rollback_count == 1
    assert [name for name, _ in _settings(raw.calls)].count("app.current_tenant_id") == 2


def test_the_context_is_applied_before_the_next_statement_not_at_commit():
    """Most connections are closed right after their last commit: applying the
    context at once cost a round trip, and the transaction it opened a
    rollback in close()."""
    raw = FakeRawConnection()
    pool = FakePool()
    conn = PooledTenantConnection(pool, raw, "tenant-1", "user-1")
    applied_at_checkout = len(raw.calls)

    conn.commit()
    conn.close()

    assert len(raw.calls) == applied_at_checkout  # nothing more was sent
    assert raw.rollback_count == 0 and pool.putconn_calls == [(raw, False)]


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
    pool._slots = threading.BoundedSemaphore(2)
    pool._checkout_wait_seconds = 0

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
    pool._slots = threading.BoundedSemaphore(2)
    pool._checkout_wait_seconds = 0

    def always_fails(self):
        raise psycopg2.OperationalError("server closed the connection unexpectedly")

    monkeypatch.setattr(PooledTenantConnection, "_apply_tenant_context", always_fails)

    with pytest.raises(psycopg2.OperationalError):
        pool.get_tenant_connection("tenant-1", "user-1")


def test_get_tenant_connection_returns_the_connection_on_the_final_failed_attempt(monkeypatch):
    """
    Real leak this guards: the retry loop's LAST attempt used to just
    `raise` psycopg2.OperationalError without ever giving the raw
    connection it had already checked out back to the pool - every
    occurrence of two consecutive stale/broken connections permanently
    shrank the pool by one, below its configured maxconn, until enough
    of these had happened to exhaust it entirely (psycopg2.pool.PoolError:
    connection pool exhausted) even under otherwise-normal load. Both
    checkouts across the two attempts must be accounted for - the pool
    must never end up down a connection just because establishing tenant
    context failed.
    """
    putconn_calls = []
    checked_out = [FakeRawConnection(), FakeRawConnection()]
    connections = iter(checked_out)

    pool = TenantConnectionPool.__new__(TenantConnectionPool)
    pool._pool = type("FakeInnerPool", (), {
        "getconn": lambda self: next(connections),
        "putconn": lambda self, c, close=False: putconn_calls.append((c, close)),
    })()
    pool._slots = threading.BoundedSemaphore(2)
    pool._checkout_wait_seconds = 0

    def always_fails(self):
        raise psycopg2.OperationalError("server closed the connection unexpectedly")

    monkeypatch.setattr(PooledTenantConnection, "_apply_tenant_context", always_fails)

    with pytest.raises(psycopg2.OperationalError):
        pool.get_tenant_connection("tenant-1", "user-1")

    # Both the discarded-and-retried first connection AND the final
    # attempt's connection must be returned (discarded) - neither lost.
    assert putconn_calls == [(checked_out[0], True), (checked_out[1], True)]


def test_get_tenant_connection_returns_the_connection_on_a_non_operational_error(monkeypatch):
    """
    Real leak this guards: only psycopg2.OperationalError was caught
    here, so any OTHER failure while establishing tenant context (e.g.
    psycopg2.InterfaceError, "connection already closed" - a realistic
    outcome for a pooled connection the server closed after an idle
    timeout, and NOT a subclass of OperationalError) fell straight
    through uncaught, permanently losing the connection this method had
    already checked out. Must still propagate the real error (API
    contract unchanged - a caller still sees the failure), just without
    leaking the connection.
    """
    putconn_calls = []
    raw = FakeRawConnection()

    pool = TenantConnectionPool.__new__(TenantConnectionPool)
    pool._pool = type("FakeInnerPool", (), {
        "getconn": lambda self: raw,
        "putconn": lambda self, c, close=False: putconn_calls.append((c, close)),
    })()
    pool._slots = threading.BoundedSemaphore(2)
    pool._checkout_wait_seconds = 0

    def raises_interface_error(self):
        raise psycopg2.InterfaceError("connection already closed")

    monkeypatch.setattr(PooledTenantConnection, "_apply_tenant_context", raises_interface_error)

    with pytest.raises(psycopg2.InterfaceError):
        pool.get_tenant_connection("tenant-1", "user-1")

    assert putconn_calls == [(raw, True)]  # discarded, not leaked - and not silently retried either


def _waiting_pool(maxconn, wait):
    pool = TenantConnectionPool.__new__(TenantConnectionPool)
    pool._pool = type("FakeInnerPool", (), {
        "getconn": lambda self: FakeRawConnection(),
        "putconn": lambda self, c, close=False: None,
    })()
    pool._slots = threading.BoundedSemaphore(maxconn)
    pool._checkout_wait_seconds = wait
    return pool


def test_checkout_waits_for_a_connection_another_request_returns():
    """psycopg2's pool raises PoolError the moment it is exhausted; a burst
    above maxconn must instead wait its turn. A load test (70 users against
    maxconn=10) failed 16% of requests before checkout waited."""
    import time

    pool = _waiting_pool(maxconn=1, wait=5)
    held = pool._checkout()
    threading.Timer(0.2, lambda: pool.putconn(held)).start()
    started = time.monotonic()
    assert isinstance(pool._checkout(), FakeRawConnection)
    assert 0.15 < time.monotonic() - started < 2


def test_checkout_gives_up_with_pool_error_after_the_wait():
    """A pool that stays exhausted for the whole wait is a real capacity
    problem: fail (the API answers 503), never hang."""
    import psycopg2.pool

    pool = _waiting_pool(maxconn=1, wait=0.1)
    pool._checkout()
    with pytest.raises(psycopg2.pool.PoolError):
        pool._checkout()
    no_wait = _waiting_pool(maxconn=1, wait=0)   # wait=0: fail at once (used by a lifecycle test)
    no_wait._checkout()
    with pytest.raises(psycopg2.pool.PoolError):
        no_wait._checkout()


def test_a_failed_checkout_or_a_discarded_connection_frees_its_slot():
    import psycopg2

    pool = _waiting_pool(maxconn=1, wait=0)
    pool._pool.getconn = lambda: (_ for _ in ()).throw(psycopg2.OperationalError("down"))
    with pytest.raises(psycopg2.OperationalError):
        pool._checkout()
    pool._pool.getconn = lambda: FakeRawConnection()
    raw = pool._checkout()            # the failed attempt didn't keep the only slot
    pool.putconn(raw, discard=True)
    assert isinstance(pool._checkout(), FakeRawConnection)


def test_context_carries_the_request_language():
    from src.infrastructure.request_language import reset_request_language, set_request_language

    token = set_request_language("ar-JO")
    try:
        raw = FakeRawConnection()
        PooledTenantConnection(FakePool(), raw, "tenant-1", "user-1")
    finally:
        reset_request_language(token)
    assert ("app.lang", "ar") in _settings(raw.calls)


def test_a_returned_connection_is_kept_for_reuse_up_to_maxconn(monkeypatch):
    """psycopg2 closes every returned connection beyond minconn; with
    minconn=1 that meant a new connection (and password authentication) for
    nearly every concurrent request. Up to maxconn are now kept."""
    opened = []

    class Conn:
        closed = False
        info = type("Info", (), {"transaction_status": psycopg2.extensions.TRANSACTION_STATUS_IDLE})()

        def close(self):
            self.closed = True

    def connect(*_a, **_k):
        opened.append(Conn())
        return opened[-1]

    monkeypatch.setattr(psycopg2.pool.psycopg2, "connect", connect)
    pool = TenantConnectionPool("dsn", minconn=1, maxconn=3)
    assert len(opened) == 1  # still only minconn opened up front
    held = [pool._checkout() for _ in range(3)]
    for conn in held:
        pool.putconn(conn)
    assert len(opened) == 3 and not any(c.closed for c in opened)
    again = [pool._checkout() for _ in range(3)]
    assert len(opened) == 3  # all three reused, none opened
    for conn in again:
        pool.putconn(conn)
