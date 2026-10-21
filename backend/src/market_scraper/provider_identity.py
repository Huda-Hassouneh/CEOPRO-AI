"""Source-scoped provider record identity persistence.

Only provider IDs, parent references, revision metadata, hashes and ingestion-job
provenance are persisted. This module never stores payloads or promotes canonical
business records. Association review is an internal primitive; no public route
is registered until its application review contract is separately approved.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any


class ProviderIdentityError(ValueError):
    """A provider identity or reviewed association is invalid or ambiguous."""


_ENTITY_TYPES = {"product", "variant", "order", "order_line_item"}
_SHOPIFY_TYPES = {
    "product": "product", "variant": "variant", "order": "order", "line_item": "order_line_item",
}
_WOO_TYPES = {
    "product": "product", "variation": "variant", "order": "order", "line_item": "order_line_item",
}


def _id(value: Any, provider: str, entity_type: str) -> str:
    if provider == "woocommerce":
        # The adapters expose numeric JSON IDs as ints, while this helper's
        # own first normalization returns the namespace key as text. Accept
        # only that canonical decimal representation on the second pass.
        if isinstance(value, bool) or not isinstance(value, (int, str)):
            raise ProviderIdentityError("WooCommerce record identity must be a positive provider ID")
        token = str(value)
        if not token.isdecimal() or len(token) > 18 or int(token) < 1:
            raise ProviderIdentityError("WooCommerce record identity must be a positive provider ID")
        return token
    if provider == "shopify" and isinstance(value, str) and value.startswith("gid://shopify/") and len(value) <= 255:
        expected = {"product": "Product", "variant": "ProductVariant", "order": "Order", "order_line_item": "LineItem"}[entity_type]
        if value.startswith(f"gid://shopify/{expected}/"):
            tail = value.rsplit("/", 1)[-1]
            if tail.isdecimal() and int(tail) > 0:
                return value
    raise ProviderIdentityError("provider record identity does not match its entity type")


def _revision_time(value: Any) -> tuple[str | None, datetime | None]:
    if value is None:
        return None, None
    if not isinstance(value, str) or not value.strip() or len(value) > 255:
        raise ProviderIdentityError("provider revision timestamp is invalid")
    raw = value.strip()
    normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ProviderIdentityError("provider revision timestamp is invalid") from exc
    if parsed.tzinfo is None:
        raise ProviderIdentityError("provider revision timestamp must include a timezone")
    return raw, parsed


def _fingerprint(provider: str, entity: str, record_id: str, parent_id: str | None,
                 product_id: str | None, variant_id: str | None, revision: str | None) -> str:
    # Fingerprint only stable provider identity/revision fields, never a raw
    # product/order payload or customer attribute.
    material = json.dumps(
        {"provider": provider, "entity": entity, "record_id": record_id,
         "parent_id": parent_id, "product_id": product_id, "variant_id": variant_id,
         "revision": revision}, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def _persist(conn, *, source_id: str, provider: str, entity_type: str, record_id: Any,
             parent_id: Any = None, related_product_id: Any = None,
             related_variant_id: Any = None, updated_at: Any = None,
             ingestion_job_id: str | None = None) -> dict[str, Any]:
    if entity_type not in _ENTITY_TYPES:
        raise ProviderIdentityError("unsupported provider entity type")
    record_id = _id(record_id, provider, entity_type)
    parent = _id(parent_id, provider, "product" if entity_type == "variant" else "order") if parent_id is not None else None
    related_product = _id(related_product_id, provider, "product") if related_product_id is not None else None
    related_variant = _id(related_variant_id, provider, "variant") if related_variant_id is not None else None
    revision, revision_time = _revision_time(updated_at)
    fingerprint = _fingerprint(provider, entity_type, record_id, parent, related_product, related_variant, revision)
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT * FROM public.keel_provider_identity_observe(%s::uuid,%s,%s,%s,%s,%s,%s,%s::timestamptz,%s,%s::uuid);",
            (source_id, entity_type, record_id, parent, related_product, related_variant,
             revision, revision_time, fingerprint, ingestion_job_id),
        )
        identity_id, status, duplicate = cursor.fetchone()
    return {"identity_id": str(identity_id), "mapping_status": status, "duplicate": bool(duplicate),
            "provider": provider, "entity_type": entity_type, "provider_record_id": record_id}


def persist_shopify_records(conn, source_id: str, records: Iterable[Any], *, ingestion_job_id: str | None = None) -> list[dict[str, Any]]:
    """Persist a ShopifyGraphQLClient iterator without retaining its payloads."""
    output: list[dict[str, Any]] = []
    order_versions: dict[str, str | None] = {}
    for record in records:
        entity = _SHOPIFY_TYPES.get(getattr(record, "entity_type", None))
        payload = getattr(record, "payload", None)
        if entity is None or not isinstance(payload, Mapping):
            raise ProviderIdentityError("Shopify adapter record is malformed or unsupported")
        record_id = _id(getattr(record, "provider_id", None), "shopify", entity)
        parent = getattr(record, "parent_provider_id", None)
        if entity == "order":
            order_versions[record_id] = payload.get("updatedAt")
        updated = payload.get("updatedAt")
        related_product = related_variant = None
        if entity == "order_line_item":
            variant = payload.get("variant")
            if isinstance(variant, Mapping):
                related_variant = variant.get("id")
                product = variant.get("product")
                if isinstance(product, Mapping):
                    related_product = product.get("id")
            if updated is None and parent is not None:
                parent_key = _id(parent, "shopify", "order")
                updated = order_versions.get(parent_key)
        output.append(_persist(conn, source_id=source_id, provider="shopify", entity_type=entity,
                               record_id=record_id, parent_id=parent, related_product_id=related_product,
                               related_variant_id=related_variant, updated_at=updated,
                               ingestion_job_id=ingestion_job_id))
    return output


def persist_woocommerce_records(conn, source_id: str, records: Iterable[Any], *, ingestion_job_id: str | None = None) -> list[dict[str, Any]]:
    """Persist WooCommerce product/variation/order records and order lines."""
    output: list[dict[str, Any]] = []
    order_versions: dict[str, Any] = {}
    for record in records:
        entity = _WOO_TYPES.get(getattr(record, "entity_type", None))
        payload = getattr(record, "payload", None)
        if entity is None or not isinstance(payload, Mapping):
            raise ProviderIdentityError("WooCommerce adapter record is malformed or unsupported")
        record_id = _id(getattr(record, "provider_id", None), "woocommerce", entity)
        parent = getattr(record, "parent_provider_id", None)
        gmt_updated = payload.get("date_modified_gmt")
        updated = gmt_updated or payload.get("date_modified")
        if isinstance(gmt_updated, str):
            try:
                parsed_gmt = datetime.fromisoformat(gmt_updated.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ProviderIdentityError("WooCommerce provider revision timestamp is invalid") from exc
            if parsed_gmt.tzinfo is None:
                updated = gmt_updated + "+00:00"
        if entity == "order":
            order_versions[record_id] = updated
        output.append(_persist(conn, source_id=source_id, provider="woocommerce", entity_type=entity,
                               record_id=record_id, parent_id=parent, updated_at=updated,
                               ingestion_job_id=ingestion_job_id))
        if entity == "order":
            lines = payload.get("line_items")
            if lines is None:
                continue
            if not isinstance(lines, list):
                raise ProviderIdentityError("WooCommerce order line items are malformed")
            for line in lines:
                if not isinstance(line, Mapping):
                    raise ProviderIdentityError("WooCommerce order line item is malformed")
                output.append(_persist(
                    conn, source_id=source_id, provider="woocommerce", entity_type="order_line_item",
                    record_id=line.get("id"), parent_id=record_id,
                    related_product_id=line.get("product_id") or None,
                    related_variant_id=line.get("variation_id") or None,
                    updated_at=updated, ingestion_job_id=ingestion_job_id,
                ))
    return output


def associate_provider_record(conn, identity_id: str, target_kind: str, target_id: str,
                              *, reason_code: str | None = None,
                              evidence_reference: str | None = None) -> dict[str, Any]:
    """Internal reviewed association primitive; deliberately not an API route.

    Reviewer identity comes from the authenticated database session context,
    never a request-supplied reviewer ID. The database authorizes the existing
    tenant owner/admin review role and appends immutable audit evidence.
    """
    if target_kind not in {"product", "transaction", "invoice"}:
        raise ProviderIdentityError("unsupported canonical association target")
    metadata = {}
    if reason_code is not None:
        if not isinstance(reason_code, str) or not reason_code.strip() or len(reason_code) > 80:
            raise ProviderIdentityError("review reason code is invalid")
        metadata["reason_code"] = reason_code.strip()
    if evidence_reference is not None:
        if not isinstance(evidence_reference, str) or not evidence_reference.strip() or len(evidence_reference) > 200:
            raise ProviderIdentityError("review evidence reference is invalid")
        metadata["evidence_reference"] = evidence_reference.strip()
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT * FROM public.keel_provider_record_associate(%s::uuid,%s,%s::uuid,%s::jsonb);",
            (identity_id, target_kind, target_id, json.dumps(metadata)),
        )
        review_id, duplicate = cursor.fetchone()
    return {"review_id": str(review_id), "duplicate": bool(duplicate)}
