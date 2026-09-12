"""
CEOPRO AI - Scheduled worker for both connector types (direct-database and
generic API/POS/ERP) - the real running process that was missing entirely
until now. connector_sync.py's DB-connector sync path
(run_due_connector_syncs()) was fully built and tested but never called
by anything in the deployed system; api_connector_sync.py (this same
session) is new and had the identical gap baked in from day one had this
worker not been built alongside it. This is the exact same "built but
never wired into the live system" pattern this codebase's own production-
hardening audit already fixed once for tenant_discovery.py - closed here
for both connector types at once, in one worker, rather than two
near-identical processes.

Cross-tenant discovery (which tenants even HAVE an active connector
configured) uses list_tenants_with_active_connectors() (migration
20260912000000_add_connector_discovery_function.sql), a SECURITY DEFINER
function - see that migration's own docstring for why a plain query
can't do this under data_sources' FORCE ROW LEVEL SECURITY, and why a
superuser connection is deliberately never used here (this service only
ever holds SCRAPER_DATABASE_URL, the restricted ceopro_app role, same as
every other market_scraper service - see docker-compose.yml). The actual
sync work for each tenant then runs on a real, tenant-scoped, RLS-
respecting pooled connection (data_access.get_tenant_connection()) - the
discovery step never reads or touches a tenant's own collector_config or
credentials, only which tenant_ids exist.

Polling, not event-driven: unlike this codebase's Redis Streams consumers
(worker.py, analysis_worker.py, forecasting/consumer.py), there is no
event to react to here - a client's own POS/ERP database or API doesn't
notify CEOPRO AI when it changes, so periodically checking is the only
option, exactly the model connector_sync.py's own module docstring
already describes (DEFAULT_SYNC_INTERVAL_MINUTES). DEFAULT_POLL_INTERVAL_
SECONDS below governs how often this worker re-runs discovery + the
per-tenant due-check, not how often any individual source is actually
synced - that's still governed entirely by each source's own
sync_frequency_minutes via is_due_for_sync(), unchanged.
"""
import logging
import os
import time

from src.market_scraper import api_connector_sync, connector_sync, data_access

logger = logging.getLogger("CEOPRO_AI_CONNECTOR_WORKER")

DEFAULT_POLL_INTERVAL_SECONDS = 300

# Not a real tenant - list_tenants_with_active_connectors() is SECURITY
# DEFINER and ignores app.current_tenant_id entirely (verified directly
# against a real Postgres instance: it returns every tenant with an
# active connector regardless of which, or whether any, tenant context
# is set on the calling session). This value only exists because
# data_access.get_tenant_connection() needs SOME tenant_id to construct a
# real connection through - set_config() doesn't validate that a tenant
# with this ID actually exists, and this discovery call never queries
# any RLS-guarded table directly, so an all-zeros placeholder is safe
# and never resolves to real tenant data.
_DISCOVERY_CONTEXT_TENANT_ID = "00000000-0000-0000-0000-000000000000"

_CONNECTOR_COLLECTOR_KEYS = [
    connector_sync.DB_CONNECTOR_COLLECTOR_KEY,
    api_connector_sync.API_CONNECTOR_COLLECTOR_KEY,
]


def discover_tenants_with_connectors() -> list:
    conn = data_access.get_tenant_connection(_DISCOVERY_CONTEXT_TENANT_ID)
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM list_tenants_with_active_connectors(%s);",
                (_CONNECTOR_COLLECTOR_KEYS,),
            )
            rows = cursor.fetchall()
        return [str(row[0]) for row in rows]
    finally:
        conn.close()


def run_connector_syncs_for_tenant(tenant_id: str) -> dict:
    """
    Runs every due source of both connector types for one tenant, on one
    real RLS-scoped connection. Each connector type's own run_due_*_
    connector_syncs() already isolates one source's failure from another
    within that type; this isolates the two connector TYPES from each
    other the same way - an API connector outage must never block an
    otherwise-healthy DB connector sync for the same tenant, or vice
    versa.
    """
    conn = data_access.get_tenant_connection(tenant_id)
    try:
        db_results = connector_sync.run_due_connector_syncs(conn, tenant_id)
    except Exception as e:  # noqa: BLE001 - the API connector type must still get its turn
        logger.warning("db connector sync batch failed for tenant=%s: %s", tenant_id, e)
        db_results = [{"error": str(e)}]
    try:
        api_results = api_connector_sync.run_due_api_connector_syncs(conn, tenant_id)
    except Exception as e:  # noqa: BLE001 - see above, symmetrically
        logger.warning("api connector sync batch failed for tenant=%s: %s", tenant_id, e)
        api_results = [{"error": str(e)}]
    finally:
        conn.close()
    return {"db_connector": db_results, "api_connector": api_results}


def run_once() -> dict:
    """One full discovery + per-tenant sync pass. Exposed separately from
    run_forever() for testability and for a caller that wants to trigger
    a pass on demand rather than waiting for the next poll tick."""
    results = {}
    for tenant_id in discover_tenants_with_connectors():
        try:
            results[tenant_id] = run_connector_syncs_for_tenant(tenant_id)
        except Exception as e:  # noqa: BLE001 - one tenant's failure must never block another's
            logger.exception("connector sync failed for tenant=%s", tenant_id)
            results[tenant_id] = {"error": str(e)}
    return results


def run_forever():
    logging.basicConfig(level=logging.INFO)
    interval = int(os.getenv("CONNECTOR_WORKER_POLL_INTERVAL_SECONDS", str(DEFAULT_POLL_INTERVAL_SECONDS)))
    logger.info("Connector worker online. Poll interval=%ss", interval)
    while True:
        try:
            result = run_once()
            if result:
                logger.info("connector sync pass complete: %s", result)
        except Exception:
            logger.exception("connector discovery pass failed")
        time.sleep(interval)


if __name__ == "__main__":
    run_forever()
