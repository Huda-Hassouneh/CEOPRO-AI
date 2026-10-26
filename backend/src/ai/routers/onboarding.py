from src.infrastructure.public_urls import frontend_origin
from typing import Optional
import json
import os
from uuid import UUID
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field

from src.ai import db
from src.ai.core import usage
from src.ai.core.security import TenantContext, get_tenant_context
from src.market_scraper import api_connector_sync, connector_sync, price_coverage
from src.market_scraper import data_access as market_scraper_data_access
from src.market_scraper.woocommerce import WooCommerceClient, canonical_store_url, WooCommerceError
from src.market_scraper.provider_lifecycle import bind_verified_provider_source, woocommerce_verified_store_id
from src.market_scraper import provider_business_staging

router = APIRouter(prefix="/onboarding", tags=["onboarding"])

from src.ai import onboarding_profile

@router.get("/state")
def onboarding_state(ctx: TenantContext = Depends(get_tenant_context)):
    conn=db.app_role_connection(ctx.tenant_id,ctx.user_id)
    try:
        result=onboarding_profile.state(conn,ctx.tenant_id)
        conn.commit()
        return result
    finally: conn.close()

@router.put("/state")
def save_onboarding_state(body: onboarding_profile.StepRequest, ctx: TenantContext = Depends(get_tenant_context)):
    conn=db.app_role_connection(ctx.tenant_id,ctx.user_id)
    try:
        _require_admin(conn,ctx)
        result=onboarding_profile.save(conn,ctx.tenant_id,ctx.user_id,body)
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally: conn.close()



@router.get("/industries")
def onboarding_industries() -> dict:
    """Static profile choices needed to finish setup on every plan.

    Discovery endpoints are plan-gated as a whole, but reading the shared
    industry catalog is not a discovery operation and must remain available
    to an owner completing a workspace that has no paid market entitlement.
    """
    from src.market_scraper.market_discovery import industries

    return {"industries": industries.choices()}


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


class WooCommerceConnectorRequest(BaseModel):
    """Original KEEL store onboarding contract, adapted to Python authorities."""
    url: str = Field(max_length=2048)
    consumer_key: str = Field(alias="consumerKey", min_length=43, max_length=43)
    consumer_secret: str = Field(alias="consumerSecret", min_length=43, max_length=43)
    consent: bool
    sync_frequency_minutes: int = Field(default=60, alias="syncFrequencyMinutes", ge=15, le=10080)
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class ShopifyAuthorizeRequest(BaseModel):
    url: str = Field(max_length=2048)
    consent: bool
    include_test_orders: bool = Field(default=False, alias="includeTestOrders")
    sync_frequency_minutes: int = Field(default=60, alias="syncFrequencyMinutes", ge=15, le=10080)
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class ShopifyFinishRequest(BaseModel):
    ticket: str = Field(max_length=20000)
    model_config = ConfigDict(extra="forbid")


class ProviderBusinessReviewRequest(BaseModel):
    business_revision_id: UUID
    decision: str
    idempotency_key: str = Field(min_length=1, max_length=180)
    reason_code: str = Field(min_length=1, max_length=100)
    model_config = ConfigDict(extra="forbid")


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


@router.post("/connect/woocommerce")
def onboarding_connect_woocommerce(
    request: WooCommerceConnectorRequest, ctx: TenantContext = Depends(get_tenant_context),
) -> dict:
    """Verify then bind the original WooCommerce URL + REST key connection.

    The URL is not accepted as proof by itself: M94 binding follows a real
    authenticated wc/v3 product, order and currency verification.
    """
    import re
    from src.market_scraper.network_security import UnsafeTargetError

    if request.consent is not True:
        raise HTTPException(status_code=422, detail="Connection consent is required.")
    if not re.fullmatch(r"ck_[a-fA-F0-9]{40}", request.consumer_key) \
            or not re.fullmatch(r"cs_[a-fA-F0-9]{40}", request.consumer_secret):
        raise HTTPException(status_code=422, detail="WooCommerce REST credentials are invalid.")
    try:
        canonical = canonical_store_url(request.url)
        parts = urlsplit(canonical)
        if parts.port is not None or "%" in parts.path or "\\" in parts.path:
            raise UnsafeTargetError("store URL does not match the approved connection URL contract")
    except UnsafeTargetError:
        raise HTTPException(status_code=422, detail="Use the public HTTPS store URL without a port or encoded path.")
    _require_vault({"consumer_key": request.consumer_key, "consumer_secret": request.consumer_secret})

    # Authenticate and authorize before spending provider requests. Re-check
    # authorization in the write transaction in case membership changed.
    check = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        _require_admin(check, ctx)
    finally:
        check.close()
    try:
        verification = dict(WooCommerceClient(canonical, request.consumer_key, request.consumer_secret).verify_connection())
    except Exception as exc:
        raise HTTPException(status_code=422 if isinstance(exc, (ValueError, UnsafeTargetError))
                            or getattr(exc, "code", None) == "authentication_failed" else 502,
                            detail="WooCommerce connection could not be verified.")
    if verification.get("verified") is not True:
        raise HTTPException(status_code=422, detail="WooCommerce connection could not be verified.")

    tenant_conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        _require_admin(tenant_conn, ctx)
        with tenant_conn.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                           ("connected-data-sources:" + str(ctx.tenant_id),))
            identity_id = woocommerce_verified_store_id(canonical)
            cursor.execute(
                "SELECT ps.source_id,ds.collector_key,ds.is_active,ds.collector_config "
                "FROM public.keel_provider_sources ps JOIN public.data_sources ds "
                "ON ds.tenant_id=ps.tenant_id AND ds.source_id=ps.source_id "
                "WHERE ps.tenant_id=%s::uuid AND ps.provider='woocommerce' AND ps.verified_store_id=%s "
                "FOR UPDATE OF ds",
                (ctx.tenant_id, identity_id),
            )
            existing = cursor.fetchone()
        if existing and existing[1] != "woocommerce":
            raise HTTPException(status_code=409, detail="This verified store is bound to a different source type.")
        source_id = str(existing[0]) if existing else None
        if existing and (existing[3] or {}).get("store_url", (existing[3] or {}).get("base_url")) != canonical:
            raise HTTPException(status_code=409, detail="The verified store binding requires operator review.")
        if not existing:
            usage.ensure_capacity(tenant_conn, ctx.tenant_id, usage.CONNECTED_DATA_SOURCES)
            config = {"provider": "woocommerce", "store_url": canonical, "max_pages": 100}
            source_id = market_scraper_data_access.register_self_service_data_source(
                tenant_conn, ctx.tenant_id, ctx.user_id, parts.hostname, "woocommerce", config,
                {"consumer_key": request.consumer_key, "consumer_secret": request.consumer_secret},
                request.sync_frequency_minutes, source_url=canonical, commit=False,
            )
        else:
            if not existing[2]:
                usage.ensure_capacity(tenant_conn, ctx.tenant_id, usage.CONNECTED_DATA_SOURCES)
            with tenant_conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE public.data_sources SET is_active=TRUE,policy_status='ALLOWED',source_url=%s,"
                    "collector_config=%s::jsonb,source_name=%s,sync_frequency_minutes=%s,last_synced_at=NULL "
                    "WHERE tenant_id=%s::uuid AND source_id=%s::uuid",
                    (canonical, json.dumps({"provider": "woocommerce", "store_url": canonical,
                                                            "max_pages": 100}), parts.hostname,
                     request.sync_frequency_minutes, ctx.tenant_id, source_id),
                )
            market_scraper_data_access.set_source_credentials(
                tenant_conn, ctx.tenant_id, source_id,
                {"consumer_key": request.consumer_key, "consumer_secret": request.consumer_secret}, commit=False,
            )
        verification.update({"canonical_store_url": canonical})
        binding = bind_verified_provider_source(
            tenant_conn, tenant_id=ctx.tenant_id, source_id=source_id, provider="woocommerce",
            verification=verification,
        )
        tenant_conn.commit()
        return {"source_id": source_id, "provider": "woocommerce", "connection_status": "verified",
                "reconnected": bool(binding.get("reconnected")), "currency_code": verification["currency_code"]}
    except Exception:
        tenant_conn.rollback()
        raise
    finally:
        tenant_conn.close()


@router.post("/connect/shopify/authorize")
def onboarding_shopify_authorize(request: ShopifyAuthorizeRequest,
                                 ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """Begin the Node-compatible signed-state Shopify installation flow."""
    if request.consent is not True:
        raise HTTPException(status_code=422, detail="Connection consent is required.")
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        _require_admin(conn, ctx)
    finally:
        conn.close()
    from src.market_scraper.shopify_oauth import begin_authorization
    return begin_authorization(tenant_id=ctx.tenant_id, user_id=ctx.user_id, shop_input=request.url,
                               sync_frequency_minutes=request.sync_frequency_minutes,
                               include_test_orders=request.include_test_orders)


@router.get("/shopify/callback")
def onboarding_shopify_callback(request: Request) -> RedirectResponse:
    """Validate Shopify's signed callback and return a short-lived finish ticket.

    The callback does not exchange/store a token. The initiating authenticated
    tenant session must submit the ticket to the finish endpoint.
    """
    pairs = list(request.query_params.multi_items())
    if len({key for key, _ in pairs}) != len(pairs):
        raise HTTPException(status_code=400, detail="Shopify callback contains duplicate parameters.")
    from src.market_scraper.shopify_oauth import create_callback_ticket
    from urllib.parse import urlencode
    try:
        ticket = create_callback_ticket(dict(pairs))
        destination = frontend_origin() + "/connect-data#" + urlencode(
            {"shopify_ticket": ticket["ticket"], "shopify_state": ticket["state"]}
        )
    except HTTPException:
        frontend = frontend_origin()
        if not frontend:
            raise
        destination = frontend + "/connect-data?shopify=error"
    return RedirectResponse(destination, status_code=303, headers={"Cache-Control": "no-store",
                                                                   "Referrer-Policy": "no-referrer"})


@router.post("/connect/shopify/complete")
def onboarding_shopify_complete(request: ShopifyFinishRequest,
                                ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        _require_admin(conn, ctx)
        from src.market_scraper.shopify_oauth import finish_authorization
        result = finish_authorization(conn, tenant_id=ctx.tenant_id, user_id=ctx.user_id,
                                      ticket=request.ticket)
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# --- Connected business systems: list, sync now, disconnect ---------------

_CONNECTOR_KEYS = (connector_sync.DB_CONNECTOR_COLLECTOR_KEY, api_connector_sync.API_CONNECTOR_COLLECTOR_KEY,
                   "woocommerce", "shopify")
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
                       ds.created_at, ds.is_active, j.job_status, j.rows_processed, j.rows_failed, j.ended_at,
                       ps.connection_state, ps.verified_at, j.job_id, j.created_at
                FROM data_sources ds
                LEFT JOIN LATERAL (
                    SELECT job_id, job_status, rows_processed, rows_failed, ended_at, created_at FROM ingestion_jobs
                    WHERE tenant_id = ds.tenant_id AND source_id = ds.source_id ORDER BY created_at DESC LIMIT 1
                ) j ON TRUE
                LEFT JOIN public.keel_provider_sources ps
                  ON ps.tenant_id=ds.tenant_id AND ps.source_id=ds.source_id
                WHERE ds.tenant_id = %s AND ds.collector_key = ANY(%s) AND ds.is_active
                ORDER BY ds.created_at DESC;
                """,
                (ctx.tenant_id, list(_CONNECTOR_KEYS)),
            )
            rows = cursor.fetchall()
        return {"sources": [{
            "source_id": str(r[0]), "name": r[1], "kind": r[2],
            "sync_frequency_minutes": r[3], "last_synced_at": r[4].isoformat() if r[4] else None,
            "created_at": r[5].isoformat() if r[5] else None,
            "connection_status": r[11] or ("verification_required" if r[2] in {"woocommerce", "shopify"} else "active"),
            "verified_at": r[12].isoformat() if r[12] else None,
            "last_run": None if r[7] is None else {"status": r[7], "rows_processed": r[8], "rows_failed": r[9],
                                                    "finished_at": r[10].isoformat() if r[10] else None,
                                                    "job_id": str(r[13]) if r[13] else None,
                                                    "created_at": r[14].isoformat() if r[14] else None},
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


@router.get("/sources/{source_id}/provider-records")
def list_provider_business_records(source_id: UUID, limit: int = 50, offset: int = 0,
                                   entity_type: Optional[str] = None,
                                   ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """List current source-scoped provider evidence; nothing here is canonical posting."""
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT 1 FROM data_sources WHERE tenant_id=%s::uuid AND source_id=%s::uuid AND collector_key=ANY(%s)",
                           (ctx.tenant_id, str(source_id), ["shopify", "woocommerce"]))
            if cursor.fetchone() is None:
                raise HTTPException(status_code=404, detail="Provider connection not found.")
        try:
            return provider_business_staging.list_provider_business_records(
                conn, str(source_id), limit=limit, offset=offset, entity_type=entity_type,
            )
        except provider_business_staging.ProviderBusinessStagingError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
    finally:
        conn.close()


@router.get("/sources/{source_id}/provider-records/{identity_id}/revisions")
def provider_business_record_history(source_id: UUID, identity_id: UUID,
                                     ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        result = provider_business_staging.get_provider_business_history(conn, str(source_id), str(identity_id))
        if result is None:
            raise HTTPException(status_code=404, detail="Provider record not found.")
        return result
    finally:
        conn.close()


@router.post("/sources/{source_id}/provider-records/reviews")
def review_provider_business_record(source_id: UUID, body: ProviderBusinessReviewRequest,
                                    ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        _require_admin(conn, ctx)
        with conn.cursor() as cursor:
            cursor.execute("SELECT 1 FROM public.keel_provider_business_revisions WHERE tenant_id=%s::uuid "
                           "AND source_id=%s::uuid AND business_revision_id=%s::uuid",
                           (ctx.tenant_id, str(source_id), str(body.business_revision_id)))
            if cursor.fetchone() is None:
                raise HTTPException(status_code=404, detail="Provider record revision not found.")
        result = provider_business_staging.decide_provider_business_review(
            conn, str(body.business_revision_id), decision=body.decision,
            idempotency_key=body.idempotency_key, reason_code=body.reason_code,
        )
        conn.commit()
        return {**result, "review_status": "recorded", "canonical_write_performed": False}
    except HTTPException:
        conn.rollback()
        raise
    except provider_business_staging.ProviderBusinessStagingError as exc:
        conn.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except Exception as exc:
        conn.rollback()
        code = getattr(exc, "pgcode", None)
        if code == "42501":
            raise HTTPException(status_code=403, detail="An owner or admin role is required to review provider records.") from None
        if code == "22023":
            raise HTTPException(status_code=422, detail="Provider review request is invalid.") from None
        if code in {"23505", "55000", "23514"}:
            raise HTTPException(status_code=409, detail="The provider revision is stale or already reviewed.") from None
        if code == "23503":
            raise HTTPException(status_code=404, detail="Provider record revision not found.") from None
        raise HTTPException(status_code=500, detail="Provider review could not be recorded.") from None
    finally:
        conn.close()
