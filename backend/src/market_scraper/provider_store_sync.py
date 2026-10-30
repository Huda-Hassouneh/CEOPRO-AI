"""Scheduled, read-only Shopify and WooCommerce synchronization into evidence.

This worker uses the existing connector receipt, ingestion-job, M95 identity,
and M96 inventory authorities. It does not persist provider payloads or write
canonical products, orders, invoices, or stock. WooCommerce preserves the
original URL + REST-key onboarding contract; its URL is bound only after
authenticated product, order, and currency reads succeed.
"""
from __future__ import annotations

import logging
import os
import uuid
import hashlib
from typing import Callable

from src.ai.core import operation_receipts
from src.market_scraper import data_access
from src.market_scraper.connector_sync import is_due_for_sync, safe_connector_error
from src.market_scraper.provider_identity import persist_shopify_records
from src.market_scraper.inventory_provenance import persist_shopify_inventory_records
from src.market_scraper.provider_business_staging import stage_provider_business_records
from src.market_scraper.provider_lifecycle import ProviderLifecycleError
from src.market_scraper.provider_incremental import load_order_watermark,next_order_continuation
from src.market_scraper.provider_identity import persist_woocommerce_records
from src.market_scraper.inventory_provenance import persist_woocommerce_inventory_records
from src.market_scraper.woocommerce import WooCommerceClient, WooCommerceError, canonical_store_url
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
        include_test_orders=credentials.get("include_test_orders") is True,
    )


def _woocommerce_client_for(source: dict, loaded: dict, client_factory: Callable = WooCommerceClient):
    """Build the original URL + consumer key/secret connection from the vault."""
    if source.get("collector_key") != WOOCOMMERCE_COLLECTOR_KEY or source.get("provider") != "woocommerce":
        raise ProviderLifecycleError("source is not bound to a verified WooCommerce identity")
    if source.get("connection_state") != "verified" or not source.get("verified_store_id"):
        raise ProviderLifecycleError("WooCommerce source is not currently verified")
    config = loaded.get("collector_config") or {}
    credentials = loaded.get("connection_credentials") or {}
    store_url = config.get("store_url") or config.get("base_url")
    if not isinstance(store_url, str):
        raise ProviderLifecycleError("WooCommerce store URL is unavailable")
    try:
        canonical = canonical_store_url(store_url)
    except Exception as exc:
        raise ProviderLifecycleError("WooCommerce store URL is invalid") from exc
    expected_id = "url-sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if expected_id != source.get("verified_store_id"):
        raise ProviderLifecycleError("WooCommerce store URL differs from its verified binding")
    consumer_key, consumer_secret = credentials.get("consumer_key"), credentials.get("consumer_secret")
    if not isinstance(consumer_key, str) or not isinstance(consumer_secret, str):
        raise WooCommerceError("invalid_credentials", "WooCommerce credentials are unavailable in the credential vault")
    return client_factory(canonical, consumer_key, consumer_secret,
                          max_pages=config.get("max_pages", 100))


def _stream_records(client, stream: str, modified_since=None):
    if stream == "products":
        return list(client.iter_products())
    if stream == "orders":
        return list(client.iter_orders(modified_since=modified_since)) if modified_since else list(client.iter_orders())
    if stream == "inventory":
        return list(client.iter_inventory())
    raise ValueError("unsupported provider stream")


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
            # ceopro_app is intentionally SELECT-only on M94 provider bindings.
            # Lock the mutable data-source row (which owns active/config/credential
            # fencing) and read the provider binding without requesting table-write
            # privileges just to obtain a row lock on the SELECT-only evidence table.
            "AND ds.is_active IS TRUE AND ds.policy_status='ALLOWED' FOR SHARE OF ds;",
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
        conn, tenant_id, source["source_id"], receipt, replay_safe_provider_read=True, provider="shopify",
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
    business = None
    persisted_count = 0
    try:
        if stream in {"products", "orders"}:
            persisted = persist_shopify_records(fenced, source["source_id"], records, ingestion_job_id=job_id)
            business = stage_provider_business_records(
                fenced, provider="shopify", source_id=source["source_id"],
                ingestion_job_id=job_id, receipt=receipt,
                configuration_version=int(source["configuration_version"]),
                records=records, identity_rows=persisted,
            )
            persisted_count = len(persisted)
            processed = len(persisted) + business["revisions_created"]
        else:
            persisted = persist_shopify_inventory_records(
                fenced, source["source_id"], records, ingestion_job_id=job_id,
                receipt_id=receipt["receipt_id"],
            )
            processed = len(persisted)
            persisted_count = len(persisted)
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

    result = {
        "source_id": source["source_id"], "job_id": job_id, "stream": stream,
        "records_persisted": persisted_count, "checkpoint_advanced": True,
        "canonical_promotion": False,
    }
    if business is not None:
        result["business_staging"] = business
        result["business_records_staged"] = business["revisions_created"]
    return result


def sync_shopify_source(conn, tenant_id: str, source: dict, receipt: dict, *,
                        client_factory: Callable = ShopifyGraphQLClient) -> dict:
    """Synchronize all Shopify streams under one source receipt and job.

    ENT-008 authorizes one active operation per source, not per stream. Keeping
    all three reads under that receipt prevents a failed stream's retryable
    receipt/job from being accidentally reused and completed by the next stream.
    The evidence writes, job completion, and all full-scan checkpoints commit
    together; a failure leaves the existing checkpoint set untouched.
    """
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
            "AND ds.is_active IS TRUE AND ds.policy_status='ALLOWED' FOR SHARE OF ds;",
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
        conn, tenant_id, source["source_id"], receipt, replay_safe_provider_read=True, provider="shopify",
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
        order_watermark=load_order_watermark(conn,tenant_id,source)
        records_by_stream = {stream: _stream_records(client, stream,order_watermark if stream=='orders' else None) for stream in _STREAMS}
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
    stream_results: dict[str, int] = {}
    business_results: dict[str, dict[str, int]] = {}
    checkpoints = []
    try:
        for stream, records in records_by_stream.items():
            if stream in {"products", "orders"}:
                persisted = persist_shopify_records(
                    fenced, source["source_id"], records, ingestion_job_id=job_id,
                )
                business_results[stream] = stage_provider_business_records(
                    fenced, provider="shopify", source_id=source["source_id"],
                    ingestion_job_id=job_id, receipt=receipt,
                    configuration_version=int(source["configuration_version"]),
                    records=records, identity_rows=persisted,
                )
            else:
                persisted = persist_shopify_inventory_records(
                    fenced, source["source_id"], records, ingestion_job_id=job_id,
                    receipt_id=receipt["receipt_id"],
                )
            # Preserve the established stream_results contract (M95/M96
            # identity/observation counts); M98 typed evidence is reported in
            # its own additive summary.
            stream_results[stream] = len(persisted)
            checkpoints.append({
                "source_id": source["source_id"], "stream_key": stream,
                # The adapter consumes bounded cursors internally. This marks a
                # completed full scan; it is not an incremental-resume cursor.
                "continuation": next_order_continuation(records,"shopify",order_watermark) if stream=="orders" else {},
                "configuration_version": int(source["configuration_version"]),
            })
        data_access.finish_ingestion_job(
            conn, tenant_id, job_id, status="COMPLETED",
            processed=sum(stream_results.values()), failed=0, error=None,
            receipt=receipt, provider_checkpoints=checkpoints,
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
        "source_id": source["source_id"], "job_id": job_id,
        "stream_results": stream_results, "business_staging": business_results,
        "business_records_staged": sum(v["revisions_created"] for v in business_results.values()),
        "records_persisted": sum(stream_results.values()),
        "checkpoint_advanced": True, "full_scan": order_watermark is None,
        "canonical_promotion": False,
    }


def sync_woocommerce_source(conn, tenant_id: str, source: dict, receipt: dict, *,
                            client_factory: Callable = WooCommerceClient) -> dict:
    """Full read scan into M95 identities and M96 observations, never canonical tables."""
    if not receipt or receipt.get("operation_type") != operation_receipts.SCHEDULED_CONNECTOR_SYNC:
        raise operation_receipts.ReceiptAuthorizationError("WooCommerce sync requires an ENT-008 source receipt")
    loaded = data_access.load_source(conn, tenant_id, source["source_id"])
    if loaded is None or loaded.get("collector_key") != WOOCOMMERCE_COLLECTOR_KEY:
        raise operation_receipts.ReceiptAuthorizationError("WooCommerce source is inactive or no longer approved")
    receipt["source_execution_fingerprint"] = loaded["source_execution_fingerprint"]
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT ps.provider,ps.verified_store_id,ps.verified_store_domain,ps.connection_state, "
            "ps.configuration_version FROM public.keel_provider_sources ps "
            "JOIN public.data_sources ds ON ds.tenant_id=ps.tenant_id AND ds.source_id=ps.source_id "
            "WHERE ps.tenant_id=%s::uuid AND ps.source_id=%s::uuid "
            "AND ds.is_active IS TRUE AND ds.policy_status='ALLOWED' FOR SHARE OF ds;",
            (tenant_id, source["source_id"]),
        )
        binding = cursor.fetchone()
    if (not binding or binding[0] != "woocommerce" or binding[3] != "verified"
            or binding[1] != source["verified_store_id"]
            or int(binding[4]) != int(source["configuration_version"])):
        raise operation_receipts.ReceiptAuthorizationError("WooCommerce source verification changed before sync")
    job_id = data_access.create_or_reuse_receipt_ingestion_job(
        conn, tenant_id, source["source_id"], receipt, replay_safe_provider_read=True, provider="woocommerce",
    )
    try:
        operation_receipts.begin_provider(conn, receipt)
        client = _woocommerce_client_for(source, loaded, client_factory)
        verification = client.verify_connection()
        canonical = canonical_store_url((loaded.get("collector_config") or {}).get("store_url")
                                        or (loaded.get("collector_config") or {}).get("base_url", ""))
        expected_id = "url-sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        if verification.get("verified") is not True or verification.get("canonical_store_url") != canonical \
                or expected_id != source["verified_store_id"]:
            raise WooCommerceError("store_mismatch", "Authenticated WooCommerce endpoint differs from its verified source")
        products = list(client.iter_products())
        order_watermark=load_order_watermark(conn,tenant_id,source)
        orders = list(client.iter_orders(modified_since=order_watermark)) if order_watermark else list(client.iter_orders())
    except operation_receipts.ReceiptSourceChanged:
        data_access.fail_source_changed_ingestion_job(conn, tenant_id, receipt)
        raise
    except Exception as exc:
        try:
            data_access.finish_ingestion_job(conn, tenant_id, job_id, status="FAILED", processed=0, failed=0,
                                             error=safe_connector_error(exc, "WooCommerce provider read"), receipt=receipt)
        except Exception:
            conn.rollback()
        raise

    fenced = operation_receipts.FencedConnection(conn, receipt)
    try:
        identities = persist_woocommerce_records(fenced, source["source_id"], [*products, *orders],
                                                 ingestion_job_id=job_id)
        binding_currency = (loaded.get("collector_config") or {}).get("store_currency")
        # WooCommerce's authenticated store read returns the configured store
        # currency; use it only as a provider value qualifier, not an FX rule.
        verification_currency = verification.get("currency_code")
        store_currency = verification_currency if isinstance(verification_currency, str) else binding_currency
        business = stage_provider_business_records(
            fenced, provider="woocommerce", source_id=source["source_id"],
            ingestion_job_id=job_id, receipt=receipt,
            configuration_version=int(source["configuration_version"]),
            records=[*products, *orders], identity_rows=identities, store_currency=store_currency,
        )
        inventory = persist_woocommerce_inventory_records(
            fenced, source["source_id"], products, ingestion_job_id=job_id,
            receipt_id=receipt["receipt_id"],
        )
        checkpoints = [{"source_id": source["source_id"], "stream_key": stream,
                        "continuation": next_order_continuation(orders,"woocommerce",order_watermark) if stream=="orders" else {}, "configuration_version": int(source["configuration_version"])}
                       for stream in ("products", "orders", "inventory")]
        data_access.finish_ingestion_job(
            conn, tenant_id, job_id, status="COMPLETED",
            processed=len(identities) + len(inventory) + business["revisions_created"], failed=0, error=None,
            receipt=receipt, provider_checkpoints=checkpoints,
        )
    except operation_receipts.ReceiptSourceChanged:
        conn.rollback()
        data_access.fail_source_changed_ingestion_job(conn, tenant_id, receipt)
        raise
    except Exception as exc:
        conn.rollback()
        data_access.finish_ingestion_job(conn, tenant_id, job_id, status="FAILED", processed=0, failed=0,
                                         error=safe_connector_error(exc, "WooCommerce evidence persistence"), receipt=receipt)
        raise
    return {"source_id": source["source_id"], "job_id": job_id,
            "stream_results": {"products": sum(1 for r in products if r.entity_type == "product"),
                               "orders": len(orders), "inventory": len(inventory)},
            "records_persisted": len(identities) + len(inventory),
            "business_records_staged": business["revisions_created"],
            "business_staging": business, "checkpoint_advanced": True,
            "full_scan": order_watermark is None, "canonical_promotion": False, "provider": "woocommerce"}


def run_due_provider_syncs(conn, tenant_id: str, *, client_factory: Callable = ShopifyGraphQLClient,
                            woocommerce_client_factory: Callable = WooCommerceClient) -> list[dict]:
    """Run due Shopify and authenticated URL-bound WooCommerce sources."""
    service_actor = os.getenv("SCRAPER_ACTOR_USER_ID", "").strip()
    if not service_actor:
        raise RuntimeError("SCRAPER_ACTOR_USER_ID must identify an active tenant service principal")
    operation_receipts.recover_expired(conn, tenant_id)
    results: list[dict] = []
    for source in load_due_provider_sources(conn, tenant_id):
        provider = source.get("provider")
        if provider not in {"shopify", "woocommerce"} or source.get("connection_state") != "verified":
            results.append({"source_id": source["source_id"], "provider": provider or source["collector_key"],
                            "blocked": "verified_provider_source_binding_required"})
            continue
        receipt = None
        try:
            intent = operation_receipts.create_or_get_operation(
                conn, operation_receipts.SCHEDULED_CONNECTOR_SYNC, tenant_id, "source",
                source["source_id"], service_actor, "service", {},
            )
            receipt = operation_receipts.claim(
                conn, tenant_id, intent["receipt_id"], f"shopify-sync-{uuid.uuid4()}",
            )
            if provider == "woocommerce":
                result = sync_woocommerce_source(conn, tenant_id, source, receipt,
                                                 client_factory=woocommerce_client_factory)
            else:
                result = sync_shopify_source(conn, tenant_id, source, receipt, client_factory=client_factory)
            operation_receipts.finish(conn, receipt, "completed")
            # Evidence scan and canonical outcomes are reported separately. A held
            # canonical row is durable/reviewable, never a second provider charge.
            if os.getenv('KEEL_ALLOW_DISPOSABLE_PROVIDER_PROMOTION')=='YES':
                from src.market_scraper.provider_promotion import reconcile
                try:
                    result['canonical_reconciliation']=reconcile(conn,tenant_id,source['source_id'],service_actor)
                    result['canonical_promotion']=any(result['canonical_reconciliation'].get(k,0) for k in ('catalog_created','stock_updated'))
                except Exception as exc:
                    conn.rollback()
                    result['canonical_reconciliation']={'enabled':True,'status':'review_required','error_type':type(exc).__name__}
                    logger.warning('Provider canonical reconciliation held source_id=%s error_type=%s',source['source_id'],type(exc).__name__)
            result["provider"] = provider
            results.append(result)
        except Exception as exc:  # isolate one provider source without masking others
            if receipt is not None:
                try:
                    changed = isinstance(exc, operation_receipts.ReceiptSourceChanged)
                    operation_receipts.finish(
                        conn, receipt, "failed" if changed else "retryable",
                        "SOURCE_CONFIGURATION_CHANGED" if changed else f"{provider.upper()}_READ_SYNC_FAILED",
                        replay_safe_provider_read=not changed,
                    )
                except operation_receipts.ReceiptError:
                    conn.rollback()
            logger.warning("Provider sync failed source_id=%s provider=%s error_type=%s",
                           source["source_id"], provider, type(exc).__name__)
            results.append({"source_id": source["source_id"], "provider": provider,
                            "error": safe_connector_error(exc, f"{provider.title()} synchronization")})
    return results
