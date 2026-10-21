"""Tenant-scoped persistence for verified provider identities and deliveries.

This module stores provider lifecycle evidence only. It does not promote
catalog records, reconcile inventory, interpret refunds, or create charges.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any


class ProviderLifecycleError(ValueError):
    """A provider lifecycle action lacked verified, tenant-safe evidence."""


_SENSITIVE_KEYS = ("secret", "password", "token", "credential", "authorization", "cookie", "api_key")
_SHOPIFY_PROVENANCE = "shopify_authenticated_shop_query"
_SHOPIFY_DOMAIN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.myshopify\.com$", re.ASCII)


def _canonical_shop_domain(value: str) -> str:
    if not isinstance(value, str) or len(value) > 255:
        raise ProviderLifecycleError("Shopify shop domain is invalid")
    canonical = value.strip().lower().rstrip(".")
    if not _SHOPIFY_DOMAIN.fullmatch(canonical):
        raise ProviderLifecycleError("Shopify shop domain must be a bare myshopify.com hostname")
    return canonical


def _require_safe_metadata(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ProviderLifecycleError("provider evidence must be a metadata object")
    result = dict(value)
    if any(any(part in str(key).lower() for part in _SENSITIVE_KEYS) for key in result):
        raise ProviderLifecycleError("provider evidence cannot contain secret or credential fields")
    try:
        encoded = json.dumps(result, separators=(",", ":"), ensure_ascii=True)
    except (TypeError, ValueError) as exc:
        raise ProviderLifecycleError("provider evidence must be JSON serializable") from exc
    if len(encoded.encode("utf-8")) > 8192:
        raise ProviderLifecycleError("provider evidence exceeds the allowed size")
    return result


def bind_verified_provider_source(
    conn,
    *,
    tenant_id: str,
    source_id: str,
    provider: str,
    verification: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind an existing source after the provider adapter verifies identity.

    Current WooCommerce verification confirms REST access but does not return
    a stable provider account ID, so it is deliberately rejected here. A
    configured host alone is not sufficient U6 identity evidence.
    """
    if verification.get("verified") is not True:
        raise ProviderLifecycleError("provider identity must be verified before binding")
    if any(any(part in str(key).lower() for part in _SENSITIVE_KEYS) for key in verification):
        raise ProviderLifecycleError("provider verification objects must not contain credentials")
    if provider != "shopify":
        raise ProviderLifecycleError("this provider verification contract does not yet expose a stable store ID")
    shop_id = verification.get("shop_id")
    domain = verification.get("shop_domain")
    if not isinstance(shop_id, str) or not shop_id.startswith("gid://shopify/Shop/"):
        raise ProviderLifecycleError("Shopify verification did not return a stable shop ID")
    if not isinstance(domain, str) or _canonical_shop_domain(domain) != domain:
        raise ProviderLifecycleError("Shopify verification did not return a canonical shop domain")
    evidence = _require_safe_metadata({
        "api_version": verification.get("api_version"),
        "currency_code": verification.get("currency_code"),
    })
    command = {
        "tenant_id": str(tenant_id),
        "source_id": str(source_id),
        "provider": "shopify",
        "verified": True,
        "verified_store_id": shop_id,
        "verified_store_domain": domain,
        "identity_provenance": _SHOPIFY_PROVENANCE,
        "verification_evidence": evidence,
    }
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT public.keel_provider_source_command('bind_verified', %s::jsonb);",
            (json.dumps(command),),
        )
        row = cursor.fetchone()
    return row[0]


def set_provider_source_state(conn, *, source_id: str, provider: str, state: str) -> dict[str, Any]:
    """Disable or require reverification without deleting source history."""
    actions = {"disabled": "disable", "verification_required": "mark_verification_required"}
    if state not in actions or provider not in {"shopify", "woocommerce"}:
        raise ProviderLifecycleError("unsupported provider source state")
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT public.keel_provider_source_command(%s, %s::jsonb);",
            (actions[state], json.dumps({"source_id": str(source_id), "provider": provider})),
        )
        row = cursor.fetchone()
    return row[0]


def advance_completed_checkpoint(
    conn,
    *,
    tenant_id: str,
    source_id: str,
    stream_key: str,
    continuation: Mapping[str, Any],
    receipt: Mapping[str, Any],
    job_id: str,
    configuration_version: int,
    job_completed: bool,
    rows_failed: int = 0,
    rows_partial: int = 0,
) -> int:
    """Advance only for a complete job, tied to the live ENT-008 lease.

    Caller must invoke this in the same transaction as marking the ingestion
    job complete. The database function verifies that committed status,
    source, receipt state, generation, lease and configuration version.
    """
    if not job_completed or rows_failed or rows_partial:
        raise ProviderLifecycleError("partial or unsuccessful sync cannot advance its checkpoint")
    safe_continuation = _require_safe_metadata(continuation)
    if set(safe_continuation) - {"cursor", "page", "modified_since"}:
        raise ProviderLifecycleError("unsupported provider checkpoint field")
    if receipt.get("operation_type") != "scheduled_connector_sync":
        raise ProviderLifecycleError("a scheduled connector receipt is required")
    receipt_id = receipt.get("receipt_id")
    generation = receipt.get("lease_generation")
    if not receipt_id or isinstance(generation, bool) or not isinstance(generation, int):
        raise ProviderLifecycleError("receipt fencing identity is incomplete")
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT public.keel_provider_checkpoint_advance(%s::uuid,%s::uuid,%s,%s::jsonb,"
            "%s::uuid,%s::uuid,%s::bigint,%s::bigint);",
            (tenant_id, source_id, stream_key, json.dumps(safe_continuation), receipt_id,
             job_id, generation, configuration_version),
        )
        row = cursor.fetchone()
    return int(row[0])


def record_shopify_delivery(
    conn,
    *,
    source_id: str,
    expected_shop_domain: str,
    raw_body: bytes,
    verified: Any,
) -> dict[str, Any]:
    """Persist a Shopify delivery only after HMAC and shop checks succeeded."""
    from src.market_scraper.shopify import VerifiedShopifyWebhook

    if not isinstance(verified, VerifiedShopifyWebhook):
        raise ProviderLifecycleError("a signature-verified Shopify webhook is required")
    if _canonical_shop_domain(expected_shop_domain) != _canonical_shop_domain(verified.shop_domain):
        raise ProviderLifecycleError("verified webhook does not match its bound source")
    if not isinstance(raw_body, bytes):
        raise ProviderLifecycleError("raw signed webhook body is required")
    payload_hash = hashlib.sha256(raw_body).hexdigest()
    safe_metadata = _require_safe_metadata({"topic": verified.topic})
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT * FROM public.keel_provider_delivery_record(%s::uuid,'shopify',%s,%s,%s,%s::jsonb,"
            "'shopify_hmac_sha256',TRUE);",
            (source_id, verified.webhook_id, verified.topic, payload_hash, json.dumps(safe_metadata)),
        )
        row = cursor.fetchone()
    return {"delivery_receipt_id": str(row[0]), "duplicate": bool(row[1])}


def authenticate_and_record_shopify_delivery(
    conn,
    *,
    tenant_id: str,
    source_id: str,
    raw_body: bytes,
    headers: Mapping[str, str],
    client_secret: str,
) -> dict[str, Any]:
    """Authenticate the raw Shopify request, bind its shop, then persist it.

    The secret must be obtained from the existing credential vault by the
    caller and is used only in memory. The database stores only a body digest
    and safe topic metadata.
    """
    from src.market_scraper.shopify import verify_shopify_webhook

    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT verified_store_id,verified_store_domain FROM public.keel_provider_sources "
            "WHERE tenant_id=%s::uuid AND source_id=%s::uuid AND provider='shopify' "
            "AND connection_state IN ('verified','disabled','verification_required');",
            (tenant_id, source_id),
        )
        source = cursor.fetchone()
    if not source:
        raise ProviderLifecycleError("no verified Shopify source matches the delivery")
    verified_id, verified_domain = source
    verified = verify_shopify_webhook(
        raw_body,
        headers,
        client_secret,
        expected_shop=verified_domain,
        expected_shop_id=verified_id,
    )
    return record_shopify_delivery(
        conn,
        source_id=source_id,
        expected_shop_domain=verified_domain,
        raw_body=raw_body,
        verified=verified,
    )


def transition_provider_delivery(conn, delivery_receipt_id: str, state: str) -> bool:
    """Move a verified delivery through its durable operational states."""
    if state not in {"processing", "reconciliation_required", "processed", "failed"}:
        raise ProviderLifecycleError("unsupported provider delivery transition")
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT public.keel_provider_delivery_transition(%s::uuid,%s);",
            (delivery_receipt_id, state),
        )
        row = cursor.fetchone()
    return bool(row[0])
