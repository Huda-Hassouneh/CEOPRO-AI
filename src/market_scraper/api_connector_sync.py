"""
CEOPRO AI - Scheduled polling sync for a client's own REST API (POS, ERP,
e-commerce platform) - the generic API/POS/ERP connector the vision spec
calls for alongside the DB connector and file upload.

Mirrors connector_sync.py's exact scheduling/watermark contract
(is_due_for_sync(), the same data_sources.last_synced_at/
sync_frequency_minutes columns, the same create_ingestion_job() ->
process_records() -> finish_ingestion_job() pipeline) - reused directly,
not reimplemented, per connector_sync.py's own docstring: "An API
connector's sync would reuse the exact same is_due_for_sync()/
finish_ingestion_job() mechanism, just with a per-vendor fetch_page()
... instead of a SQL query." This module is that fetch_page().

Uses src.ai.extraction.adapters.api_adapter.read_paginated_api() (already
built, previously uncalled anywhere in the codebase) to normalize however
many pages a vendor's API returns into the same (headers, rows) shape
db_adapter.py's read_db_query() already produces - so process_records()
downstream needs zero awareness of which connector type produced its
input.

Real-world API shapes vary enough that no single hardcoded request format
would work for more than one vendor - collector_config below describes
just enough of a REST API's shape (base URL, where the pagination page
number goes, where the records live in the JSON response) to build a
working fetch_page() for the common case: a paginated GET endpoint
returning either a bare JSON array or an object with a named list field.
A vendor whose API genuinely doesn't fit this shape (cursor-based
pagination, GraphQL, webhooks) needs its own dedicated adapter, exactly
the same scope boundary connector_sync.py draws for a non-Postgres client
database (MySQL/SQL Server support is "a distinct, larger piece of work,
not built here").
"""
import logging
from typing import Callable, List, Optional

import httpx

from src.ai.extraction.adapters.api_adapter import read_paginated_api
from src.ai.extraction.ingestion_pipeline import process_records
from src.market_scraper.connector_sync import is_due_for_sync
from src.market_scraper.data_access import create_ingestion_job, finish_ingestion_job, load_source

logger = logging.getLogger("CEOPRO_AI_API_CONNECTOR_SYNC")

# The collector_key a source must be registered under to be treated as a
# live, polled REST API connector - see src.ai.onboarding.register_api_connector().
API_CONNECTOR_COLLECTOR_KEY = "api_connector"

_REQUIRED_CONFIG_KEYS = ("base_url", "field_mapping")

# A single sync call is capped to this many pages regardless of what the
# vendor's API claims to have - the same defensive cap read_paginated_api()
# already defaults to (1000), made explicit and configurable here so an
# unusually large or misbehaving upstream can't turn one sync tick into an
# unbounded, minutes-long request storm against a client's production API.
DEFAULT_MAX_PAGES = 1000

# Real, not arbitrary: a slow or hung upstream API must not block this
# connector's sync loop (and, transitively, every other tenant waiting on
# the same worker iteration) indefinitely. 20s matches this codebase's
# other outbound-HTTP defaults (rag/llm_client.py's own Groq timeout).
DEFAULT_REQUEST_TIMEOUT_SECONDS = 20.0


def _get_nested(payload: object, path: Optional[str]) -> object:
    """
    Walks a dot-separated path (e.g. "data.results") into a JSON response
    to find the actual list of records - many REST APIs wrap their array
    in an envelope object rather than returning it bare. None/"" path
    means the response IS the array already.
    """
    if not path:
        return payload
    current = payload
    for key in path.split("."):
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def build_api_fetch_page(
    config: dict, credentials: dict, timeout: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
) -> Callable[[int], Optional[List[dict]]]:
    """
    Builds a real fetch_page(page) callable against config["base_url"] -
    the one piece genuinely specific to talking to an arbitrary vendor's
    REST API, everything else (pagination looping, flattening into
    (headers, rows)) is api_adapter.read_paginated_api()'s existing,
    vendor-agnostic logic.

    config keys (only base_url/field_mapping are required - see
    _REQUIRED_CONFIG_KEYS):
      base_url            The endpoint to GET, e.g. "https://pos.example.com/api/sales".
      records_path        Dot path to the records array inside the JSON
                           response (e.g. "data.results"); omit when the
                           response body IS the array.
      page_param           Query param name carrying the page number.
                           Defaults to "page".
      page_size_param      Optional query param name for page size.
      page_size            Value sent for page_size_param, when set.
      extra_query_params   Dict of additional static query params sent on
                           every request (e.g. a store/location filter).
      auth_header          Header name for the credential. Defaults to
                           "Authorization".
      auth_scheme          Prefix before the credential value in that
                           header, e.g. "Bearer". Defaults to "Bearer".

    credentials: {"api_key": ...} or {"token": ...} (either key name is
    accepted - vendors call this field different things). No credentials
    at all is valid for a genuinely public/unauthenticated API; a
    misconfigured connector that DOES need auth simply gets real 401s
    from the vendor, surfaced exactly like any other fetch failure below,
    never silently skipped.
    """
    base_url = config["base_url"]
    records_path = config.get("records_path")
    page_param = config.get("page_param", "page")
    page_size_param = config.get("page_size_param")
    page_size = config.get("page_size")
    extra_query_params = config.get("extra_query_params") or {}
    auth_header = config.get("auth_header", "Authorization")
    auth_scheme = config.get("auth_scheme", "Bearer")

    headers = {}
    token = credentials.get("api_key") or credentials.get("token")
    if token:
        headers[auth_header] = f"{auth_scheme} {token}".strip()

    def fetch_page(page: int) -> Optional[List[dict]]:
        params = dict(extra_query_params)
        params[page_param] = page
        if page_size_param and page_size is not None:
            params[page_size_param] = page_size

        response = httpx.get(base_url, params=params, headers=headers, timeout=timeout)
        response.raise_for_status()
        records = _get_nested(response.json(), records_path)
        if records is None:
            return None
        if not isinstance(records, list):
            raise ValueError(
                f"API connector expected a list of records at "
                f"{'the response root' if not records_path else records_path!r}, got {type(records).__name__}"
            )
        return records or None

    return fetch_page


def load_due_api_connector_sources(conn, tenant_id: str) -> list:
    """Same contract as connector_sync.load_due_db_connector_sources(),
    filtered to API_CONNECTOR_COLLECTOR_KEY instead."""
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT source_id, last_synced_at, sync_frequency_minutes
            FROM data_sources
            WHERE tenant_id = %s AND collector_key = %s
              AND is_active = TRUE AND policy_status = 'ALLOWED';
            """,
            (tenant_id, API_CONNECTOR_COLLECTOR_KEY),
        )
        rows = cursor.fetchall()
    return [
        {"source_id": str(source_id), "last_synced_at": last_synced_at, "sync_frequency_minutes": freq}
        for source_id, last_synced_at, freq in rows
        if is_due_for_sync(last_synced_at, freq)
    ]


def sync_api_connector_source(conn, tenant_id: str, source_id: str, max_pages: int = DEFAULT_MAX_PAGES) -> dict:
    """
    Runs one real connector sync end-to-end - identical shape to
    connector_sync.sync_db_connector_source(), a REST API fetch instead
    of a SQL query for step 3. Raises (never silently returns a partial/
    fake result) on a missing source, missing required config, or a real
    request failure - a misconfigured or unreachable connector must
    surface loudly, not silently skip, same discipline as the DB
    connector.
    """
    source = load_source(conn, tenant_id, source_id)
    if source is None:
        raise ValueError(f"source not found, inactive, or not ALLOWED: {source_id!r}")

    config = source["collector_config"] or {}
    missing_config = [key for key in _REQUIRED_CONFIG_KEYS if key not in config]
    if missing_config:
        raise ValueError(f"api_connector collector_config missing required key(s): {missing_config}")

    job_id = create_ingestion_job(conn, tenant_id, source_id)

    try:
        fetch_page = build_api_fetch_page(config, source["connection_credentials"])
        headers, rows = read_paginated_api(fetch_page, max_pages=max_pages)
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


def run_due_api_connector_syncs(conn, tenant_id: str) -> list:
    """Same contract as connector_sync.run_due_connector_syncs() - one
    bad source's failure never blocks another's."""
    results = []
    for due in load_due_api_connector_sources(conn, tenant_id):
        try:
            results.append(sync_api_connector_source(conn, tenant_id, due["source_id"]))
        except Exception as e:  # noqa: BLE001 - one source's failure must not stop the batch
            logger.warning("api connector sync failed for source_id=%s: %s", due["source_id"], e)
            results.append({"source_id": due["source_id"], "error": str(e)})
    return results
