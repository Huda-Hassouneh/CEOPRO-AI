"""Typed, privacy-minimized staging for Shopify and WooCommerce records.

Provider business values remain immutable evidence. This module never changes
canonical products, transactions, invoices, or inventory quantities.
"""
from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any

from src.market_scraper.provider_business_values import (
    ProviderBusinessValueError,
    business_value_fingerprint,
    normalize_shopify_record,
    normalize_woocommerce_record,
)


class ProviderBusinessStagingError(ValueError):
    """A normalized provider business record could not be staged safely."""


_ENTITY = {
    "shopify": {"product": "product", "variant": "variant", "order": "order", "line_item": "order_line_item"},
    "woocommerce": {"product": "product", "variation": "variant", "order": "order", "line_item": "order_line_item"},
}


def _records_for_staging(provider: str, records: Iterable[Any]) -> list[tuple[str, str, Mapping[str, Any]]]:
    records=list(records)
    parent_titles={str(r.provider_id):r.payload.get('name') for r in records if provider=='woocommerce' and getattr(r,'entity_type',None)=='product' and isinstance(getattr(r,'payload',None),Mapping)}
    staged: list[tuple[str, str, Mapping[str, Any]]] = []
    for record in records:
        raw_entity = getattr(record, "entity_type", None)
        entity = _ENTITY.get(provider, {}).get(raw_entity)
        provider_id = getattr(record, "provider_id", None)
        payload = getattr(record, "payload", None)
        if entity is None or not isinstance(payload, Mapping):
            raise ProviderBusinessStagingError("Provider adapter returned an unsupported business record")
        if provider=='woocommerce' and entity=='variant' and not payload.get('name'):
            parent=parent_titles.get(str(getattr(record,'parent_provider_id',None)))
            attributes=payload.get('attributes') or []
            if isinstance(parent,str) and isinstance(attributes,list):
                labels=[a.get('option') for a in attributes if isinstance(a,Mapping) and isinstance(a.get('option'),str)]
                payload={**payload,'name':parent+(' / '+' / '.join(labels) if labels else '')}
        staged.append((entity, str(provider_id), payload))
        # WooCommerce returns line items nested in each order; M95 creates an
        # independent source-scoped identity for each line in the same pass.
        if provider == "woocommerce" and entity == "order":
            lines = payload.get("line_items") or []
            if not isinstance(lines, list):
                raise ProviderBusinessStagingError("WooCommerce order line items are malformed")
            for line in lines:
                if not isinstance(line, Mapping) or line.get("id") is None:
                    raise ProviderBusinessStagingError("WooCommerce line item identity is unavailable")
                # WooCommerce includes the order currency on the parent order,
                # not consistently on each line item. Carry only that
                # provider-reported scalar into normalization; never infer it
                # from the store's current currency configuration.
                line_payload = dict(line)
                if line_payload.get("currency") is None and payload.get("currency") is not None:
                    line_payload["currency"] = payload["currency"]
                staged.append(("order_line_item", str(line["id"]), line_payload))
    return staged


def stage_provider_business_records(
    conn,
    *,
    provider: str,
    source_id: str,
    ingestion_job_id: str,
    receipt: Mapping[str, Any],
    configuration_version: int,
    records: Iterable[Any],
    identity_rows: Iterable[Mapping[str, Any]],
    store_currency: str | None = None,
) -> dict[str, int]:
    """Persist typed revisions under the live M94/ENT-008 worker fence."""
    if provider not in _ENTITY:
        raise ProviderBusinessStagingError("Provider business staging is unavailable")
    identity_by_key = {
        (row.get("entity_type"), str(row.get("provider_record_id"))): row
        for row in identity_rows
    }
    stats = {"records_seen": 0, "revisions_created": 0, "duplicates": 0,
             "invalid": 0, "review_required": 0, "valid": 0}
    for entity, provider_id, payload in _records_for_staging(provider, records):
        identity = identity_by_key.get((entity, provider_id))
        if identity is None:
            raise ProviderBusinessStagingError("Provider business record has no persisted M95 identity")
        try:
            if provider == "shopify":
                values, findings = normalize_shopify_record(entity, payload)
            else:
                values, findings = normalize_woocommerce_record(entity, payload, store_currency=store_currency)
            status = "review_required" if findings or identity.get("mapping_status") in {"pending_review", "conflict", "unavailable"} else "valid"
            if identity.get("mapping_status") in {"pending_review", "conflict", "unavailable"}:
                findings = [*findings, {"field": "provider_identity", "code": str(identity["mapping_status"])}]
        except ProviderBusinessValueError:
            # Keep a safe, inspectable validation outcome without persisting
            # the malformed input or exception text (which may contain data).
            values = {}
            findings = [{"field": "record", "code": "provider_record_invalid"}]
            status = "invalid"
        digest = business_value_fingerprint(values)
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM public.keel_provider_business_stage98(%s::uuid,%s::uuid,%s::uuid,%s::uuid,"
                "%s,%s::bigint,%s::bigint,%s,%s::jsonb,%s::jsonb,%s);",
                (source_id, identity["identity_id"], ingestion_job_id, receipt["receipt_id"],
                 receipt["worker_id"], receipt["lease_generation"], configuration_version, digest,
                 json.dumps(values, separators=(",", ":")), json.dumps(findings, separators=(",", ":")), status),
            )
            _, _, duplicate = cursor.fetchone()
        stats["records_seen"] += 1
        stats["duplicates" if duplicate else "revisions_created"] += 1
        stats[status] += 1
    return stats


def list_provider_business_records(conn, source_id: str, *, limit: int = 50, offset: int = 0,
                                   entity_type: str | None = None) -> dict[str, Any]:
    if not 1 <= limit <= 200 or offset < 0 or entity_type not in {None, "product", "variant", "order", "order_line_item"}:
        raise ProviderBusinessStagingError("Provider record query is invalid")
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT b.business_revision_id,b.provider_record_identity_id,b.entity_type,b.revision_number,"
            "b.typed_values,b.validation_findings,b.validation_status,b.created_at,i.provider_record_id,"
            "i.mapping_status,r.decision,r.created_at,r.reason_code,i.canonical_product_id "
            "FROM public.keel_provider_business_revisions b "
            "JOIN public.keel_provider_record_identities i ON i.tenant_id=b.tenant_id "
            "AND i.source_id=b.source_id AND i.provider=b.provider AND i.provider_record_identity_id=b.provider_record_identity_id "
            "LEFT JOIN public.keel_provider_business_reviews r ON r.tenant_id=b.tenant_id "
            "AND r.source_id=b.source_id AND r.business_revision_id=b.business_revision_id "
            "WHERE b.source_id=%s::uuid AND (%s IS NULL OR b.entity_type=%s) "
            "AND NOT EXISTS (SELECT 1 FROM public.keel_provider_business_revisions newer "
            "WHERE newer.tenant_id=b.tenant_id AND newer.provider_record_identity_id=b.provider_record_identity_id "
            "AND newer.revision_number>b.revision_number) "
            "ORDER BY b.created_at DESC,b.business_revision_id LIMIT %s OFFSET %s",
            (source_id, entity_type, entity_type, limit, offset),
        )
        rows = cursor.fetchall()
    return {"items": [{
        "business_revision_id": str(r[0]), "provider_record_identity_id": str(r[1]), "entity_type": r[2],
        "revision_number": r[3], "typed_values": r[4], "validation_findings": r[5],
        "validation_status": r[6], "created_at": r[7].isoformat(), "provider_record_id": r[8],
        "identity_status": r[9], "review_decision": r[10], "reviewed_at": r[11].isoformat() if r[11] else None,
        "review_reason_code": r[12],
        "canonical_status": "linked" if r[13] else "not_posted",
        "canonical_product_id":str(r[13]) if r[13] else None,
    } for r in rows], "limit": limit, "offset": offset}


def get_provider_business_history(conn, source_id: str, identity_id: str) -> dict[str, Any] | None:
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT b.business_revision_id,b.entity_type,b.revision_number,b.provider_identity_revision_sha256,"
            "b.business_values_sha256,b.typed_values,b.validation_findings,b.validation_status,b.ingestion_job_id,b.created_at,"
            "r.business_review_id,r.decision,r.reason_code,r.created_at "
            "FROM public.keel_provider_business_revisions b LEFT JOIN public.keel_provider_business_reviews r "
            "ON r.tenant_id=b.tenant_id AND r.source_id=b.source_id AND r.business_revision_id=b.business_revision_id "
            "WHERE b.source_id=%s::uuid AND b.provider_record_identity_id=%s::uuid ORDER BY b.revision_number DESC",
            (source_id, identity_id),
        )
        rows = cursor.fetchall()
    if not rows:
        return None
    return {"provider_record_identity_id": identity_id, "revisions": [{
        "business_revision_id": str(r[0]), "entity_type": r[1], "revision_number": r[2],
        "provider_identity_revision_sha256": r[3], "business_values_sha256": r[4],
        "typed_values": r[5], "validation_findings": r[6], "validation_status": r[7],
        "ingestion_job_id": str(r[8]), "created_at": r[9].isoformat(),
        "review": None if r[10] is None else {"review_id": str(r[10]), "decision": r[11],
            "reason_code": r[12], "created_at": r[13].isoformat()},
        "canonical_status": "not_posted",
    } for r in rows]}


def decide_provider_business_review(conn, business_revision_id: str, *, decision: str,
                                    idempotency_key: str, reason_code: str) -> dict[str, Any]:
    if decision not in {"approve", "reject"}:
        raise ProviderBusinessStagingError("Review decision must be approve or reject")
    with conn.cursor() as cursor:
        cursor.execute("SELECT * FROM public.keel_provider_business_review98(%s::uuid,%s,%s,%s);",
                       (business_revision_id, decision, idempotency_key, reason_code))
        review_id, duplicate = cursor.fetchone()
    return {"review_id": str(review_id), "duplicate": bool(duplicate), "canonical_write_performed": False}
