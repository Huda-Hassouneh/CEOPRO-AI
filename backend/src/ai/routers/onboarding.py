from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.ai import db
from src.ai.core import usage
from src.ai.core.security import TenantContext, get_tenant_context
from src.market_scraper import api_connector_sync, connector_sync, price_coverage
from src.market_scraper import data_access as market_scraper_data_access

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


def _require_vault(credentials) -> None:
    """Connection secrets are only ever stored encrypted; without a
    configured key the connection is refused rather than stored in clear."""
    if not credentials:
        return
    from src.market_scraper.credential_vault import get_default_kms_backend

    try:
        get_default_kms_backend()
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=503, detail="Secure credential storage isn't set up on this server yet. Ask your administrator to configure it.")


def _check_target(url: str) -> None:
    from src.market_scraper.network_security import UnsafeTargetError, assert_connector_target

    try:
        assert_connector_target(url)
    except UnsafeTargetError:
        raise HTTPException(status_code=422, detail="That address isn't reachable from the internet. Use your system's public address.")


class DatabaseConnectorRequest(BaseModel):
    """Onboarding: connect the tenant's own Postgres-compatible database
    as a live, scheduled connector (src/market_scraper/connector_sync.py).
    field_mapping/credentials shape matches that module's own contract
    exactly - see its docstring."""
    source_name: str
    host: str
    port: int
    dbname: str
    query: str
    field_mapping: dict
    credentials: dict
    sync_frequency_minutes: Optional[int] = None


class ApiConnectorRequest(BaseModel):
    """Onboarding: connect the tenant's own POS/ERP/e-commerce REST API as
    a live, scheduled connector (src/market_scraper/api_connector_sync.py).
    Only base_url/field_mapping are required - see that module's
    build_api_fetch_page() docstring for every optional key's meaning."""
    source_name: str
    base_url: str
    field_mapping: dict
    records_path: Optional[str] = None
    page_param: Optional[str] = None
    page_size_param: Optional[str] = None
    page_size: Optional[int] = None
    extra_query_params: Optional[dict] = None
    auth_header: Optional[str] = None
    auth_scheme: Optional[str] = None
    credentials: Optional[dict] = None
    sync_frequency_minutes: Optional[int] = None


@router.get("/status")
def onboarding_status(ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """
    The backend half of the vision's guided first-time-user "How do you
    currently manage your business data?" step - see
    market_scraper.data_access.get_onboarding_status()'s own docstring
    for exactly what counts as "connected".
    """
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        result = market_scraper_data_access.get_onboarding_status(conn, ctx.tenant_id)
        # Additive hint: barcodes make market-price lookup exact. Never allowed to break the status call.
        try:
            result = {**result, "barcodes": price_coverage.get_barcode_summary(conn, ctx.tenant_id)}
        except Exception:  # noqa: BLE001
            conn.rollback()
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.post("/connect/database")
def onboarding_connect_database(
    request: DatabaseConnectorRequest, ctx: TenantContext = Depends(get_tenant_context),
) -> dict:
    """
    Registers the tenant's own Postgres-compatible database as a live,
    scheduled connector (src/market_scraper/connector_sync.py + the new
    connector_worker.py that actually runs it on a schedule). Every
    required field is enforced by DatabaseConnectorRequest's own Pydantic
    schema (a 422 before this body ever runs) - the same "let FastAPI
    validate structure, the handler only does real work" split every
    other endpoint here already follows.
    """
    _check_target(f"https://{request.host}:{request.port}")
    _require_vault(request.credentials)
    config = {
        "host": request.host, "port": request.port, "dbname": request.dbname,
        "query": request.query, "field_mapping": request.field_mapping,
    }
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        _require_admin(conn, ctx)
        usage.ensure_capacity(conn, ctx.tenant_id, usage.CONNECTED_DATA_SOURCES)
        source_id = market_scraper_data_access.register_self_service_data_source(
            conn, ctx.tenant_id, ctx.user_id, request.source_name,
            connector_sync.DB_CONNECTOR_COLLECTOR_KEY, config, request.credentials,
            request.sync_frequency_minutes,
        )
        return {"source_id": source_id, "collector_key": connector_sync.DB_CONNECTOR_COLLECTOR_KEY}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.post("/connect/api")
def onboarding_connect_api(
    request: ApiConnectorRequest, ctx: TenantContext = Depends(get_tenant_context),
) -> dict:
    """
    Registers the tenant's own POS/ERP/e-commerce REST API as a live,
    scheduled connector (src/market_scraper/api_connector_sync.py +
    connector_worker.py). Same validation split as
    onboarding_connect_database() above - only base_url/field_mapping are
    required (ApiConnectorRequest's own schema), everything else is an
    optional, vendor-specific detail (see api_connector_sync.
    build_api_fetch_page()'s own docstring for what each one controls).
    """
    _check_target(request.base_url)
    _require_vault(request.credentials)
    if request.auth_header is not None:
        from src.market_scraper.network_security import UnsafeTargetError, validate_header_name

        try:
            validate_header_name(request.auth_header)
        except UnsafeTargetError:
            raise HTTPException(status_code=422, detail="That header name can't be used for authentication.")
    config = {
        key: value for key, value in {
            "base_url": request.base_url,
            "field_mapping": request.field_mapping,
            "records_path": request.records_path,
            "page_param": request.page_param,
            "page_size_param": request.page_size_param,
            "page_size": request.page_size,
            "extra_query_params": request.extra_query_params,
            "auth_header": request.auth_header,
            "auth_scheme": request.auth_scheme,
        }.items() if value is not None
    }
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        _require_admin(conn, ctx)
        usage.ensure_capacity(conn, ctx.tenant_id, usage.CONNECTED_DATA_SOURCES)
        source_id = market_scraper_data_access.register_self_service_data_source(
            conn, ctx.tenant_id, ctx.user_id, request.source_name,
            api_connector_sync.API_CONNECTOR_COLLECTOR_KEY, config, request.credentials,
            request.sync_frequency_minutes,
        )
        return {"source_id": source_id, "collector_key": api_connector_sync.API_CONNECTOR_COLLECTOR_KEY}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# --- Connected business systems: list, sync now, disconnect ---------------

_CONNECTOR_KEYS = (connector_sync.DB_CONNECTOR_COLLECTOR_KEY, api_connector_sync.API_CONNECTOR_COLLECTOR_KEY)
_ADMIN_ROLES = {"owner", "admin"}


def _require_admin(conn, ctx) -> None:
    with conn.cursor() as cursor:
        cursor.execute("SELECT role_key FROM tenant_users WHERE tenant_id = %s AND user_id = %s AND removed_at IS NULL;",
                       (ctx.tenant_id, ctx.user_id))
        row = cursor.fetchone()
    if row is None or row[0] not in _ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Only an owner or admin can manage connections.")


@router.get("/sources")
def list_connected_sources(ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """The company's live connections to its own POS/ERP API or database,
    with when each last synced and how the last run went."""
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT ds.source_id, ds.source_name, ds.collector_key, ds.sync_frequency_minutes, ds.last_synced_at,
                       ds.created_at, ds.is_active, j.job_status, j.rows_processed, j.rows_failed, j.ended_at
                FROM data_sources ds
                LEFT JOIN LATERAL (
                    SELECT job_status, rows_processed, rows_failed, ended_at FROM ingestion_jobs
                    WHERE tenant_id = ds.tenant_id AND source_id = ds.source_id ORDER BY created_at DESC LIMIT 1
                ) j ON TRUE
                WHERE ds.tenant_id = %s AND ds.collector_key = ANY(%s) AND ds.is_active
                ORDER BY ds.created_at DESC;
                """,
                (ctx.tenant_id, list(_CONNECTOR_KEYS)),
            )
            rows = cursor.fetchall()
        return {"sources": [{
            "source_id": str(r[0]), "name": r[1], "kind": "database" if r[2] == connector_sync.DB_CONNECTOR_COLLECTOR_KEY else "api",
            "sync_frequency_minutes": r[3], "last_synced_at": r[4].isoformat() if r[4] else None,
            "created_at": r[5].isoformat() if r[5] else None,
            "last_run": None if r[7] is None else {"status": r[7], "rows_processed": r[8], "rows_failed": r[9],
                                                    "finished_at": r[10].isoformat() if r[10] else None},
        } for r in rows]}
    finally:
        conn.close()


def _update_source(ctx, source_id: str, sql: str) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        _require_admin(conn, ctx)
        with conn.cursor() as cursor:
            try:
                cursor.execute(sql, (ctx.tenant_id, source_id, list(_CONNECTOR_KEYS)))
            except Exception:  # noqa: BLE001 - malformed id
                raise HTTPException(status_code=404, detail="Connection not found.")
            if cursor.rowcount != 1:
                raise HTTPException(status_code=404, detail="Connection not found.")
        conn.commit()
        return {"source_id": source_id}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.post("/sources/{source_id}/sync")
def sync_source_now(source_id: str, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """Marks the connection as due, so the connector worker syncs it on its
    next pass (within its poll interval)."""
    result = _update_source(ctx, source_id, """
        UPDATE data_sources SET last_synced_at = NULL
        WHERE tenant_id = %s AND source_id = %s AND collector_key = ANY(%s) AND is_active;""")
    return {**result, "queued": True}


@router.delete("/sources/{source_id}")
def disconnect_source(source_id: str, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """Stops syncing and erases the stored credentials; data already
    imported stays."""
    result = _update_source(ctx, source_id, """
        UPDATE data_sources SET is_active = FALSE, connection_credentials_vault = NULL
        WHERE tenant_id = %s AND source_id = %s AND collector_key = ANY(%s) AND is_active;""")
    return {**result, "disconnected": True}
