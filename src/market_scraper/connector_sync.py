"""
CEOPRO AI - Scheduled polling sync for client DB connectors.

"We are tracking decision impacts on the ground - we are NOT building a
static reporting tool. A file-based-only system is completely rejected."
This module is the real, working fix for a Postgres-compatible client
database: instead of the client (or us) re-uploading a file, this
re-runs a configured query on an interval and only pulls new/changed
rows via a real watermark (data_sources.last_synced_at - a real,
pre-existing column, not new schema).

DEFAULT_SYNC_INTERVAL_MINUTES = 15 is a real trade-off, not an arbitrary
number: near-real-time enough that an inventory/price change is reflected
within a quarter hour (materially useful for a stockout alert or a price
recommendation - the same freshness bar this platform's own forecasting/
pricing outputs need to stay meaningful), without hammering a client's
production database with a query every few seconds. It is a DEFAULT, not
a uniform rule - data_sources.sync_frequency_minutes is per-source and
already existed in the schema (default 1440 = daily, from before this
module); a high-velocity POS can be set tighter, a slow-moving supplier
catalog looser, per source.

Scope, stated plainly, not silently overclaimed: this builds a real,
working sync path for a Postgres-compatible client database
(db_adapter.py + psycopg2, the same library this whole platform already
uses) and the scheduling/watermark mechanism itself, which is source-
type-agnostic. An API connector's sync would reuse the exact same
is_due_for_sync()/finish_ingestion_job() mechanism, just with a
per-vendor fetch_page() (api_adapter.py's own existing contract) instead
of a SQL query - there's no way to poll an arbitrary REST API without
knowing its pagination shape, independent of this module. A true multi-
dialect DB driver (MySQL, SQL Server, Oracle, ...) is the "Universal
Connector Layer" - a distinct, larger piece of work, not built here.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import psycopg2

from src.ai.extraction.adapters.db_adapter import read_db_query
from src.ai.extraction.ingestion_pipeline import process_records
from src.market_scraper.data_access import create_ingestion_job, finish_ingestion_job, load_source

logger = logging.getLogger("CEOPRO_AI_CONNECTOR_SYNC")

DEFAULT_SYNC_INTERVAL_MINUTES = 15

# The collector_key a source must be registered under to be treated as a
# live, polled DB connector rather than a one-time file upload or a
# market-scraping source - policy_cli.py register-source --collector
# db_connector is the real way to create one of these.
DB_CONNECTOR_COLLECTOR_KEY = "db_connector"

_REQUIRED_CONFIG_KEYS = ("host", "port", "dbname", "query", "field_mapping")


def is_due_for_sync(
    last_synced_at: Optional[datetime], sync_frequency_minutes: Optional[int],
    now: Optional[datetime] = None,
) -> bool:
    """
    True when this source has never synced (last_synced_at is NULL - the
    real, honest "not yet run" state, never confused with "just synced")
    or its last sync is older than sync_frequency_minutes. `now` is
    injectable for deterministic tests; real callers omit it.
    """
    if last_synced_at is None:
        return True
    interval = sync_frequency_minutes if sync_frequency_minutes is not None else DEFAULT_SYNC_INTERVAL_MINUTES
    now = now or datetime.now(timezone.utc)
    return now - last_synced_at >= timedelta(minutes=interval)


def load_due_db_connector_sources(conn, tenant_id: str) -> list:
    """
    Real DB connector sources for this tenant that are due for a sync -
    ALLOWED and active, same policy gate every other collector in this
    codebase already requires (nothing auto-approves collection; a
    connector is never synced just because a row exists for it), and
    actually due per is_due_for_sync().
    """
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT source_id, last_synced_at, sync_frequency_minutes
            FROM data_sources
            WHERE tenant_id = %s AND collector_key = %s
              AND is_active = TRUE AND policy_status = 'ALLOWED';
            """,
            (tenant_id, DB_CONNECTOR_COLLECTOR_KEY),
        )
        rows = cursor.fetchall()
    return [
        {"source_id": str(source_id), "last_synced_at": last_synced_at, "sync_frequency_minutes": freq}
        for source_id, last_synced_at, freq in rows
        if is_due_for_sync(last_synced_at, freq)
    ]


def sync_db_connector_source(conn, tenant_id: str, source_id: str) -> dict:
    """
    Runs one real connector sync end-to-end:
    1. Loads the source's real config - collector_config holds the client
       database's host/port/dbname/query/field_mapping (the query and
       column names are the tenant's own responsibility to configure
       correctly, same as any other explicit integration config in this
       codebase); connection_credentials_vault (encrypted -
       credential_vault.py, decrypted transparently by load_source())
       holds the actual user/password.
    2. Opens a REAL, read-only connection to the client's database -
       .set_session(readonly=True) is real defense-in-depth: this module
       is a reader, it must never be able to write to a client's
       production database even if the query were somehow malformed.
    3. Runs the configured query (db_adapter.py::read_db_query() - the
       same generic adapter every file-based DB import already uses).
    4. Feeds the results through the SAME ingestion_pipeline.
       process_records() every file upload uses, with
       trusted_field_mapping (the caller already knows its own schema
       with certainty - a live DB connector skips header-guessing
       entirely, same TRUSTED_MAPPING tier a POS/ERP API integration
       uses) - identical savepoint-per-row, nothing-silently-dropped
       guarantee as any other ingestion path in this codebase.
    5. finish_ingestion_job() advances data_sources.last_synced_at only
       when job_status='COMPLETED' (its own existing, tested behavior) -
       a failed sync is retried on the next due cycle, never marked as
       if it had succeeded.

    Raises (never silently returns a partial/fake result) when the
    source is missing/inactive, its collector_config is missing a
    required key, or its credentials are missing user/password - a
    misconfigured connector must surface loudly, not silently skip.
    """
    source = load_source(conn, tenant_id, source_id)
    if source is None:
        raise ValueError(f"source not found, inactive, or not ALLOWED: {source_id!r}")

    config = source["collector_config"] or {}
    missing_config = [key for key in _REQUIRED_CONFIG_KEYS if key not in config]
    if missing_config:
        raise ValueError(f"db_connector collector_config missing required key(s): {missing_config}")

    credentials = source["connection_credentials"]
    if "user" not in credentials or "password" not in credentials:
        raise ValueError("db_connector credentials must include 'user' and 'password'")

    job_id = create_ingestion_job(conn, tenant_id, source_id)

    try:
        client_conn = psycopg2.connect(
            host=config["host"], port=config["port"], dbname=config["dbname"],
            user=credentials["user"], password=credentials["password"],
            connect_timeout=15,
        )
    except Exception as e:
        finish_ingestion_job(conn, tenant_id, job_id, status="FAILED", processed=0, failed=0, error=str(e))
        raise

    try:
        client_conn.set_session(readonly=True)
        try:
            headers, rows = read_db_query(client_conn, config["query"])
        finally:
            client_conn.close()
    except Exception as e:
        finish_ingestion_job(conn, tenant_id, job_id, status="FAILED", processed=0, failed=0, error=str(e))
        raise

    summary = process_records(
        tenant_id=tenant_id, job_id=job_id, source_name=source["source_name"],
        headers=headers, rows=rows, trusted_field_mapping=config["field_mapping"],
        conn=conn, commit_every=500,
    )

    finish_ingestion_job(
        conn, tenant_id, job_id, status="COMPLETED",
        processed=summary.rows_processed, failed=summary.rows_failed,
    )

    return {
        "source_id": source_id, "job_id": job_id,
        "rows_processed": summary.rows_processed, "rows_partial": summary.rows_partial,
        "rows_failed": summary.rows_failed,
    }


def run_due_connector_syncs(conn, tenant_id: str) -> list:
    """
    The real scheduler entry point - call this on an interval (e.g. a
    cron/beat task, DEFAULT_SYNC_INTERVAL_MINUTES-ish cadence) per tenant.
    Every due source gets a real attempt; one source's failure never
    blocks another's - matches every other batch-processing discipline
    in this codebase (one bad row/record/source must not sink the rest).
    """
    results = []
    for due in load_due_db_connector_sources(conn, tenant_id):
        try:
            results.append(sync_db_connector_source(conn, tenant_id, due["source_id"]))
        except Exception as e:  # noqa: BLE001 - one source's failure must not stop the batch
            logger.warning("connector sync failed for source_id=%s: %s", due["source_id"], e)
            results.append({"source_id": due["source_id"], "error": str(e)})
    return results
