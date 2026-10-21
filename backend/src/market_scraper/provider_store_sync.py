"""Scheduled, read-only Shopify synchronization into provider evidence.

This worker uses the existing connector receipt, ingestion-job, M95 identity,
and M96 inventory authorities. It does not persist provider payloads or write
canonical products, orders, invoices, or stock. WooCommerce remains blocked at
source verification until its adapter yields a stable store identity.
"""
from __future__ import annotations

import logging
import os
import uuid
from typing import Callable

from src.ai.core import operation_receipts
from src.market_scraper import data_access
from src.market_scraper.connector_sync import is_due_for_sync, safe_connector_error
from src.market_scraper.provider_identity import persist_shopify_records
from src.market_scraper.inventory_provenance import persist_shopify_inventory_records
from src.market_scraper.provider_lifecycle import ProviderLifecycleError
from src.market_scraper.shopify import (
    DEFAULT_API_VERSION, DEFAULT_MAX_PAGES, ShopifyError, ShopifyGraphQLClient,
)

logger = logging.getLogger("KEEL_PROVIDER_STORE_SYNC")
SHOPIFY_COLLECTOR_KEY = "shopify"
WOOCOMMERCE_COLLECTOR_KEY = "woocommerce"
_STREAMS = ("products", "orders", "inventory")


def load_due_provider_sources(conn, tenant_id: str) -> list[dict]:
    """Return due provider sources with binding state; never trust source URLs."""
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT ds.source_id,ds.collector_key,ds.last_synced_at,ds.sync_frequency_minutes, "
            "ps.provider,ps.verified_store_id,ps.verified_store_domain,ps.connection_state, "
            "ps.configuration_version "
            "FROM public.data_sources ds LEFT JOIN public.keel_provider_sources ps "
            "ON ps.tenant_id=ds.tenant_id AND ps.source_id=ds.source_id "
            "WHERE ds.tenant_id=%s::uuid AND ds.collector_key=ANY(%s) "
            "AND ds.is_active IS TRUE AND ds.policy_status='ALLOWED' "
            "ORDER BY ds.created_at,ds.source_id;",
            (tenant_id, [SHOPIFY_COLLECTOR_KEY, WOOCOMMERCE_COLLECTOR_KEY]),
        )
        rows = cursor.fetchall()
    due = []
    for row in rows:
        if is_due_for_sync(row[2], row[3]):
            due.append({
                "source_id": str(row[0]), "collector_key": row[1], "provider": row[4],
                "verified_store_id": row[5], "verified_store_domain": row[6],
                "connection_state": row[7], "configuration_version": row[8],
            })
    return due


def _client_for(source: dict, loaded: dict, client_factory: Callable = ShopifyGraphQLClient):
    """Construct a client only from verified source identity and vault data."""
    if source.get("collector_key") != SHOPIFY_COLLECTOR_KEY or source.get("provider") != "shopify":
        raise ProviderLifecycleError("source is not bound to a verified Shopify identity")
    if source.get("connection_state") != "verified" or not source.get("verified_store_id"):
        raise ProviderLifecycleError("Shopify source is not currently verified")
    if not isinstance(source.get("verified_store_domain"), str):
        raise ProviderLifecycleError("verified Shopify shop domain is unavailable")
    credentials = loaded.get("connection_credentials") or {}
    token = credentials.get("access_token")
    if not isinstance(token, str) or not token:
        raise ShopifyError("invalid_credentials", "Shopify access token is unavailable in the credential vault")
    config = loaded.get("collector_config") or {}
    api_version = config.get("api_version", DEFAULT_API_VERSION)
    max_pages = config.get("max_pages", DEFAULT_MAX_PAGES)
    if isinstance(max_pages, bool) or not isinstance(max_pages, int) or not 1 <= max_pages <= DEFAULT_MAX_PAGES:
        raise ValueError("Shopify page bound is invalid")
    return client_factory(
        source["verified_store_domain"], token, api_version=api_version, max_pages=max_pages,
    )


def _stream_records(client, stream: str):
    if stream == "products":
        return list(client.iter_products())
    if stream == "orders":
        return list(client.iter_orders())
    if stream == "inventory":
        return list(client.iter_inventory())
    raise ValueError("unsupported Shopify provider stream")


def sync_shopify_stream(conn, tenant_id: str, source: dict, stream: str, receipt: dict, *,
                         client_factory: Callable = ShopifyGraphQLClient) -> dict:
    """Read, persist provider-scoped evidence, and complete one stream atomically."""
    if stream not in _STREAMS:
        raise ValueError("unsupported Shopify provider stream")
    if not receipt or receipt.get("operation_type") != operation_receipts.SCHEDULED_CONNECTOR_SYNC:
        raise operation_receipts.ReceiptAuthorizationError("Shopify sync requires an ENT-008 source receipt")
    loaded = data_access.load_source(conn, tenant_id, source["source_id"])
    if loaded is None or loaded.get("collector_key") != SHOPIFY_COLLECTOR_KEY:
        raise operation_receipts.ReceiptAuthorizationError("Shopify source is inactive or no longer approved")
    receipt["source_execution_fingerprint"] = loaded["source_execution_fingerprint"]
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT ps.provider,ps.verified_store_id,ps.verified_store_domain,ps.connection_state, "
            "ps.configuration_version FROM public.keel_provider_sources ps "
            "JOIN public.data_sources ds ON ds.tenant_id=ps.tenant_id AND ds.source_id=ps.source_id "
            "WHERE ps.tenant_id=%s::uuid AND ps.source_id=%s::uuid "
            "AND ds.is_active IS TRUE AND ds.policy_status='ALLOWED' FOR SHARE OF ps,ds;",
            (tenant_id, source["source_id"]),
        )
        current_binding = cursor.fetchone()
    if (not current_binding or current_binding[0] != "shopify"
            or current_binding[3] != "verified"
            or str(current_binding[1]) != source["verified_store_id"]
            or current_binding[2] != source["verified_store_domain"]
            or int(current_binding[4]) != int(source["configuration_version"])):
        raise operation_receipts.ReceiptAuthorizationError("Shopify source verification changed before sync")
    job_id = data_access.create_or_reuse_receipt_ingestion_job(
        conn, tenant_id, source["source_id"], receipt, replay_safe_provider_read=True,
    )

    try:
        operation_receipts.begin_provider(conn, receipt)
        client = _client_for(source, loaded, client_factory)
        verification = client.verify_connection()
        if verification.get("verified") is not True or (
            verification.get("shop_id") != source["verified_store_id"]
            or verification.get("shop_domain") != source["verified_store_domain"]
        ):
            raise ShopifyError("shop_mismatch", "Authenticated Shopify identity differs from the verified source")
        records = _stream_records(client, stream)
    except operation_receipts.ReceiptSourceChanged:
        data_access.fail_source_changed_ingestion_job(conn, tenant_id, receipt)
        raise
    except Exception as exc:
        try:
            data_access.finish_ingestion_job(
                conn, tenant_id, job_id, status="FAILED", processed=0, failed=0,
                error=safe_connector_error(exc, "Shopify provider read"), receipt=receipt,
            )
        except Exception:
            conn.rollback()
        raise

    fenced = operation_receipts.FencedConnection(conn, receipt)
    try:
        if stream in {"products", "orders"}:
            persisted = persist_shopify_records(fenced, source["source_id"], records, ingestion_job_id=job_id)
            processed = len(persisted)
        else:
            persisted = persist_shopify_inventory_records(
                fenced, source["source_id"], records, ingestion_job_id=job_id,
                receipt_id=receipt["receipt_id"],
            )
            processed = len(persisted)
        checkpoint = {
            "source_id": source["source_id"], "stream_key": stream, "continuation": {},
            "configuration_version": int(source["configuration_version"]),
        }
        data_access.finish_ingestion_job(
            conn, tenant_id, job_id, status="COMPLETED", processed=processed, failed=0,
            error=None, receipt=receipt, provider_checkpoint=checkpoint,
        )
    except operation_receipts.ReceiptSourceChanged:
        conn.rollback()
        data_access.fail_source_changed_ingestion_job(conn, tenant_id, receipt)
        raise
    except Exception as exc:
        conn.rollback()
        data_access.finish_ingestion_job(
            conn, tenant_id, job_id, status="FAILED", processed=0, failed=0,
            error=safe_connector_error(exc, "Shopify evidence persistence"), receipt=receipt,
        )
        raise

    return {
        "source_id": source["source_id"], "job_id": job_id, "stream": stream,
        "records_persisted": processed, "checkpoint_advanced": True,
        "canonical_promotion": False,
    }


def run_due_provider_syncs(conn, tenant_id: str, *, client_factory: Callable = ShopifyGraphQLClient) -> list[dict]:
    """Run due preverified Shopify streams; report unsupported Woo binding closed."""
    service_actor = os.getenv("SCRAPER_ACTOR_USER_ID", "").strip()
    if not service_actor:
        raise RuntimeError("SCRAPER_ACTOR_USER_ID must identify an active tenant service principal")
    operation_receipts.recover_expired(conn, tenant_id)
    results: list[dict] = []
    for source in load_due_provider_sources(conn, tenant_id):
        if source["collector_key"] == WOOCOMMERCE_COLLECTOR_KEY:
            results.append({"source_id": source["source_id"], "provider": "woocommerce",
                            "blocked": "stable_verified_store_identity_unavailable"})
            continue
        if source.get("provider") != "shopify" or source.get("connection_state") != "verified":
            results.append({"source_id": source["source_id"], "provider": "shopify",
                            "blocked": "verified_provider_source_binding_required"})
            continue
        for stream in _STREAMS:
            receipt = None
            try:
                intent = operation_receipts.create_or_get_operation(
                    conn, operation_receipts.SCHEDULED_CONNECTOR_SYNC, tenant_id, "source",
                    source["source_id"], service_actor, "service", {},
                )
                receipt = operation_receipts.claim(
                    conn, tenant_id, intent["receipt_id"], f"shopify-sync-{uuid.uuid4()}",
                )
                result = sync_shopify_stream(conn, tenant_id, source, stream, receipt, client_factory=client_factory)
                operation_receipts.finish(conn, receipt, "completed")
                result["provider"] = "shopify"
                results.append(result)
            except Exception as exc:  # isolate stream/source failures without masking them
                if receipt is not None:
                    try:
                        changed = isinstance(exc, operation_receipts.ReceiptSourceChanged)
                        operation_receipts.finish(
                            conn, receipt, "failed" if changed else "retryable",
                            "SOURCE_CONFIGURATION_CHANGED" if changed else "SHOPIFY_READ_SYNC_FAILED",
                            replay_safe_provider_read=not changed,
                        )
                    except operation_receipts.ReceiptError:
                        conn.rollback()
                logger.warning("Shopify sync failed source_id=%s stream=%s error_type=%s",
                               source["source_id"], stream, type(exc).__name__)
                results.append({"source_id": source["source_id"], "provider": "shopify",
                                "stream": stream, "error": safe_connector_error(exc, "Shopify synchronization")})
    return results
