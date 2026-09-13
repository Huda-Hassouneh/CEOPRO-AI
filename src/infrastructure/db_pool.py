"""
CEOPRO AI - Pooled, RLS-safe tenant-scoped Postgres connections.

Production-hardening audit finding (flagged, not silently fixed, in the
prior pass): every tenant-scoped DB call in this codebase - src/ai/
db.py::app_role_connection() and src/market_scraper/data_access.py::
get_tenant_connection() - opened a brand-new psycopg2.connect() per call
and closed it when done. Real cost at scale: every request/worker
message pays full TCP-handshake-plus-Postgres-backend-fork latency
before doing any actual work, and concurrent request throughput is
capped by how fast Postgres can spin up new backend processes rather
than by real query work.

The obvious fix - reuse pooled connections - has a real, non-obvious
danger specific to this codebase's RLS design: app_role_connection()/
get_tenant_connection() set app.current_tenant_id/app.current_user_id
via a SESSION-scoped set_config(..., is_local=false) call, which
persists for the connection's entire session. That is exactly correct
for a connection that is opened fresh and closed once per request/
message (the old design) - the session dies with the tenant context.
It is NOT safe for a pooled, reused connection: if connection X served
tenant A's request and is then handed back to the pool and checked out
again for tenant B's request WITHOUT resetting the session variable,
tenant B's queries would run under tenant A's RLS context until
something explicitly resets it - a real, silent cross-tenant data
exposure window that depends entirely on remembering to reset state on
every checkout, with no structural guarantee against forgetting.

The fix here is TRANSACTION-scoped context instead: set_config(...,
is_local=true) - equivalent to SQL's SET LOCAL - which Postgres
guarantees reverts automatically the instant the current transaction
ends (COMMIT or ROLLBACK), with zero possibility of surviving past that
boundary even if calling code has a bug. This is the actual mechanism
that makes pooling safe here, not just application-level discipline:
even in the worst case (this module's own code has a bug and fails to
re-apply the context on some path), the failure mode is the NEXT
transaction on that connection running with NO tenant context set at
all - which every Final_schema.sql RLS policy already treats as "see
zero rows" (get_current_tenant() returns NULL when the GUC is unset;
`tenant_id = NULL` is never true in SQL). It can never silently produce
a DIFFERENT tenant's data. Verified directly against
Final_schema.sql::get_current_tenant() before this design was chosen -
see test_db_pool_integration_db.py for the live proof.

The real complication this file exists to solve: several call sites
(src/ai/main.py's endpoints in particular) call conn.commit() more than
once on the SAME connection within one logical request (e.g. commit
after creating an ingestion job, do more work, commit again on
completion). A bare SET LOCAL issued once at checkout would be wiped
out by that FIRST commit, silently leaving every later statement on
that same connection running with no tenant context - a correctness
regression, not just a missed optimization, if it went unnoticed.
PooledTenantConnection below re-applies the SET LOCAL pair immediately
after every commit()/rollback() it forwards to the real connection,
so a caller doing five commits and a rollback across one request still
has correct RLS context for every single statement in between,
exactly as the old session-scoped design did - transparently, without
any call site needing to change at all.
"""

import logging
import os
import time

import psycopg2
import psycopg2.pool

logger = logging.getLogger("CEOPRO_AI_DB_POOL")


class PooledTenantConnection:
    """
    Duck-types the subset of a psycopg2 connection every call site in
    this codebase actually uses - cursor()/commit()/rollback()/close(),
    plus context-manager support - while being backed by a connection
    borrowed from a pool rather than a fresh socket. No caller needs to
    change: this is a drop-in replacement for what psycopg2.connect()
    used to return here.
    """

    def __init__(self, pool: "TenantConnectionPool", raw_conn, tenant_id: str, user_id: str):
        self._pool = pool
        self._raw = raw_conn
        self._tenant_id = str(tenant_id)
        self._user_id = str(user_id)
        self._closed = False
        self._raw.autocommit = False
        self._apply_tenant_context()

    def _apply_tenant_context(self) -> None:
        """
        SET LOCAL via set_config(..., is_local=true) - see this module's
        own docstring for why LOCAL (transaction-scoped, not session-
        scoped) is the actual safety mechanism pooling depends on here.
        Issued as the first statements of a fresh transaction (right
        after connect, and again immediately after every commit/
        rollback below) so it's always in effect for whatever the
        caller does next on this connection.
        """
        with self._raw.cursor() as cursor:
            cursor.execute("SELECT set_config('app.current_tenant_id', %s, true);", (self._tenant_id,))
            cursor.execute("SELECT set_config('app.current_user_id', %s, true);", (self._user_id,))

    def cursor(self, *args, **kwargs):
        if self._closed:
            raise psycopg2.InterfaceError("PooledTenantConnection already closed/returned to the pool")
        return self._raw.cursor(*args, **kwargs)

    def commit(self) -> None:
        self._raw.commit()
        self._apply_tenant_context()

    def rollback(self) -> None:
        self._raw.rollback()
        self._apply_tenant_context()

    def close(self) -> None:
        """
        Returns the underlying connection to the pool instead of closing
        the socket - the entire point of pooling. Never returns a
        connection to the pool mid-transaction (a leftover uncommitted
        transaction on a connection some LATER, unrelated checkout then
        reuses would be a real correctness hazard well beyond RLS), and
        discards rather than reuses a connection that turns out to be
        broken (server-side idle timeout, network blip) so the pool
        doesn't keep handing out a dead connection to every subsequent
        caller.
        """
        if self._closed:
            return
        self._closed = True
        discard = False
        try:
            status = self._raw.get_transaction_status()
            if status != psycopg2.extensions.TRANSACTION_STATUS_IDLE:
                self._raw.rollback()
        except psycopg2.Error:
            discard = True
        self._pool.putconn(self._raw, discard=discard)

    def __enter__(self) -> "PooledTenantConnection":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


class TenantConnectionPool:
    """
    Thin wrapper around psycopg2.pool.ThreadedConnectionPool (thread-safe -
    matches both a FastAPI process's synchronous request thread-pool
    executor and a multi-threaded worker) that hands out
    PooledTenantConnection wrappers instead of bare connections.

    Created lazily by each service's own module (src/ai/db.py,
    src/market_scraper/data_access.py) on first real use, not at import
    time - so importing either module never requires a reachable
    database, exactly as before this change (psycopg2.connect() was
    only ever attempted when a connection was actually requested).

    minconn eagerly opens that many real connections the first time a
    connection is requested (psycopg2.pool's own behavior); maxconn
    bounds how many this process will ever hold open at once - the
    correct backpressure signal under real load, not a bug to work
    around here.

    A genuine limitation of psycopg2.pool.ThreadedConnectionPool worth
    being explicit about: getconn() beyond maxconn raises
    psycopg2.pool.PoolError ("connection pool exhausted") IMMEDIATELY -
    it does not block/wait for a connection to free up the way a
    request-queueing pool (e.g. a database-side pooler, or a different
    Python pool implementation) would. Left unhandled, a brief legitimate
    burst of concurrent requests above maxconn would surface as hard
    failures rather than callers simply waiting a moment - confirmed
    directly under real concurrent load in
    test_db_pool_integration_db.py before this retry existed (8 real
    threads against maxconn=4 killed several threads outright on the
    unhandled PoolError). get_tenant_connection() below retries checkout
    with a short backoff before giving up, converting a brief burst into
    a short wait instead of an immediate failure - still bounded, so a
    genuinely undersized pool under sustained load fails loudly rather
    than hanging forever.
    """

    def __init__(
        self, dsn: str, minconn: int = 1, maxconn: int = 10,
        exhaustion_retry_attempts: int = 5, exhaustion_retry_backoff_seconds: float = 0.05,
    ):
        self._dsn = dsn
        self._pool = psycopg2.pool.ThreadedConnectionPool(minconn, maxconn, dsn)
        self._exhaustion_retry_attempts = exhaustion_retry_attempts
        self._exhaustion_retry_backoff_seconds = exhaustion_retry_backoff_seconds

    def _checkout(self):
        last_exc = None
        for attempt in range(self._exhaustion_retry_attempts):
            try:
                return self._pool.getconn()
            except psycopg2.pool.PoolError as exc:
                last_exc = exc
                if attempt < self._exhaustion_retry_attempts - 1:
                    time.sleep(self._exhaustion_retry_backoff_seconds * (attempt + 1))
                    continue
        raise last_exc

    def get_tenant_connection(self, tenant_id: str, user_id: str) -> PooledTenantConnection:
        """
        One retry on a genuinely dead connection the pool handed back
        (server-side idle timeout, a network blip since it was last
        used) - psycopg2 pools don't validate connections on checkout,
        so a stale one surfacing here is a real, expected occurrence at
        scale, not a rare edge case worth leaving unhandled. Discards
        the dead connection (never returns it to the pool) and asks the
        pool for a fresh one; a second consecutive failure is treated as
        a real outage and propagates.
        """
        for attempt in range(2):
            raw_conn = self._checkout()
            try:
                return PooledTenantConnection(self, raw_conn, tenant_id, user_id)
            except psycopg2.OperationalError:
                if attempt == 0:
                    logger.warning("pooled connection was stale, discarding and retrying once")
                    self._pool.putconn(raw_conn, close=True)
                    continue
                raise

    def putconn(self, raw_conn, discard: bool = False) -> None:
        self._pool.putconn(raw_conn, close=discard)

    def closeall(self) -> None:
        """Test/shutdown hook - not on any production request path."""
        self._pool.closeall()
