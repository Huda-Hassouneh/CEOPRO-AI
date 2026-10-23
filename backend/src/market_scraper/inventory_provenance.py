"""Tenant-scoped source-owned inventory evidence.

The service persists provider observations and authorized source/location
decisions. It never updates ``public.inventory`` or aggregates quantities.
Callers must pass records obtained through the existing verified adapters and
run under the established tenant database context.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from decimal import Decimal, InvalidOperation
from typing import Any


class InventoryProvenanceError(ValueError):
    """Inventory evidence is malformed, ambiguous, or outside its provider contract."""


_SHOPIFY_LOCATION = re.compile(r"^gid://shopify/Location/[0-9]+$")
_SHOPIFY_VARIANT = re.compile(r"^gid://shopify/ProductVariant/[0-9]+$")
_SHOPIFY_PRODUCT = re.compile(r"^gid://shopify/Product/[0-9]+$")
_WOO_ID = re.compile(r"^[1-9][0-9]{0,17}$")


def _digest(fields: Mapping[str, Any]) -> str:
    encoded = json.dumps(fields, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _decimal(value: Any) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise InventoryProvenanceError("provider inventory quantity is invalid")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise InventoryProvenanceError("provider inventory quantity is invalid") from exc
    if not result.is_finite():
        raise InventoryProvenanceError("provider inventory quantity is invalid")
    return result


def _revision(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > 255:
        raise InventoryProvenanceError("provider inventory revision is invalid")
    return value.strip()


def _provider_identity_id(conn, source_id: str, provider: str, record_id: str) -> str | None:
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT provider_record_identity_id FROM public.keel_provider_record_identities "
            "WHERE tenant_id=public.get_current_tenant() AND source_id=%s::uuid AND provider=%s "
            "AND entity_type IN ('product','variant') AND provider_record_id=%s",
            (source_id, provider, record_id),
        )
        row = cursor.fetchone()
    return str(row[0]) if row else None


def _provider_location_id(conn, source_id: str, provider_location_id: str) -> str | None:
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT provider_location_identity_id FROM public.keel_provider_inventory_locations "
            "WHERE tenant_id=public.get_current_tenant() AND source_id=%s::uuid AND provider='shopify' "
            "AND provider_location_id=%s",
            (source_id, provider_location_id),
        )
        row = cursor.fetchone()
    return str(row[0]) if row else None


def _observe_location(conn, source_id: str, record: Any) -> dict[str, Any]:
    payload = getattr(record, "payload", None)
    provider_id = getattr(record, "provider_id", None)
    if not isinstance(payload, Mapping) or not isinstance(provider_id, str) or not _SHOPIFY_LOCATION.fullmatch(provider_id):
        raise InventoryProvenanceError("Shopify location identity is invalid")
    name = payload.get("name")
    if not isinstance(name, str) or not name.strip() or len(name) > 200:
        raise InventoryProvenanceError("Shopify location name is invalid")
    active = payload.get("isActive")
    if active is not None and not isinstance(active, bool):
        raise InventoryProvenanceError("Shopify location status is invalid")
    updated = _revision(payload.get("updatedAt"))
    fingerprint = _digest({"id": provider_id, "name": name, "active": active, "updatedAt": updated})
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT * FROM public.keel_inventory_location_observe96(%s::uuid,%s,%s,%s,%s,%s::timestamptz,%s)",
            (source_id, provider_id, name.strip(), active, updated, updated, fingerprint),
        )
        identity_id, duplicate = cursor.fetchone()
    return {"provider_location_identity_id": str(identity_id), "duplicate": bool(duplicate), "provider_location_id": provider_id}


def _observe_level(conn, source_id: str, record: Any, locations: Mapping[str, str], *, ingestion_job_id: str | None,
                   receipt_id: str | None) -> list[dict[str, Any]]:
    payload = getattr(record, "payload", None)
    level_id = getattr(record, "provider_id", None)
    location_provider_id = getattr(record, "parent_provider_id", None)
    if not isinstance(payload, Mapping) or not isinstance(level_id, str) or not level_id.startswith("gid://shopify/InventoryLevel/"):
        raise InventoryProvenanceError("Shopify inventory-level identity is invalid")
    item = payload.get("item")
    if not isinstance(item, Mapping):
        raise InventoryProvenanceError("Shopify inventory item identity is missing")
    variant = item.get("variant")
    provider_product_id = variant.get("id") if isinstance(variant, Mapping) else None
    if not isinstance(provider_product_id, str) or not (_SHOPIFY_VARIANT.fullmatch(provider_product_id) or _SHOPIFY_PRODUCT.fullmatch(provider_product_id)):
        # Keep the stable InventoryItem reference as a source-scoped unmatched
        # identity; never guess a product from SKU or name.
        provider_product_id = item.get("id")
        if not isinstance(provider_product_id, str) or not provider_product_id.startswith("gid://shopify/InventoryItem/"):
            raise InventoryProvenanceError("Shopify inventory product identity is unavailable")
    quantities = payload.get("quantities")
    if not isinstance(quantities, list):
        raise InventoryProvenanceError("Shopify inventory quantities are malformed")
    updated = _revision(payload.get("updatedAt"))
    location_identity_id = locations.get(location_provider_id) if isinstance(location_provider_id, str) else None
    product_identity_id = _provider_identity_id(conn, source_id, "shopify", provider_product_id)
    output: list[dict[str, Any]] = []
    for quantity in quantities:
        if not isinstance(quantity, Mapping):
            raise InventoryProvenanceError("Shopify inventory quantity entry is malformed")
        name, raw_amount = quantity.get("name"), quantity.get("quantity")
        # The configured Shopify adapter currently requests these two exact
        # states. Other provider states are not silently converted or stored.
        if name not in {"available", "on_hand"}:
            continue
        amount = _decimal(raw_amount)
        fingerprint = _digest({"level": level_id, "location": location_provider_id,
                               "product": provider_product_id, "quantity_type": name,
                               "quantity": str(amount), "updatedAt": updated})
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM public.keel_inventory_observation_record96(%s::uuid,%s,%s,%s::uuid,%s::uuid,%s,%s::numeric,%s,%s::timestamptz,%s::uuid,%s::uuid,%s)",
                (source_id, level_id, provider_product_id, product_identity_id, location_identity_id,
                 name, amount, updated, updated, ingestion_job_id, receipt_id, fingerprint),
            )
            observation_id, status, duplicate = cursor.fetchone()
        output.append({"inventory_observation_id": str(observation_id), "reconciliation_status": status,
                       "duplicate": bool(duplicate), "provider": "shopify", "quantity_semantics": name})
    return output


def persist_shopify_inventory_records(conn, source_id: str, records: Iterable[Any], *,
                                      ingestion_job_id: str | None = None,
                                      receipt_id: str | None = None) -> list[dict[str, Any]]:
    """Persist Shopify location and quantity observations; no stock promotion."""
    locations: dict[str, str] = {}
    output: list[dict[str, Any]] = []
    for record in records:
        entity = getattr(record, "entity_type", None)
        if entity == "location":
            saved = _observe_location(conn, source_id, record)
            locations[saved["provider_location_id"]] = saved["provider_location_identity_id"]
        elif entity == "inventory_level":
            output.extend(_observe_level(conn, source_id, record, locations,
                                         ingestion_job_id=ingestion_job_id, receipt_id=receipt_id))
        else:
            raise InventoryProvenanceError("unsupported Shopify inventory record")
    return output


def persist_woocommerce_inventory_records(conn, source_id: str, records: Iterable[Any], *,
                                          ingestion_job_id: str | None = None,
                                          receipt_id: str | None = None) -> list[dict[str, Any]]:
    """Persist only explicit WooCommerce stock_quantity values, without a location."""
    output: list[dict[str, Any]] = []
    for record in records:
        if getattr(record, "entity_type", None) not in {"product", "variation"}:
            continue
        payload = getattr(record, "payload", None)
        provider_id = getattr(record, "provider_id", None)
        if not isinstance(payload, Mapping) or isinstance(provider_id, bool) or not isinstance(provider_id, int) or provider_id < 1:
            raise InventoryProvenanceError("WooCommerce product inventory record is invalid")
        if payload.get("manage_stock") is not True or payload.get("stock_quantity") is None:
            continue
        product_id = str(provider_id)
        parent_id = getattr(record, "parent_provider_id", None)
        if parent_id is not None:
            if isinstance(parent_id, bool) or not isinstance(parent_id, int) or parent_id < 1:
                raise InventoryProvenanceError("WooCommerce variation parent identity is invalid")
            # Inventory is recorded against the exact variation when it owns
            # stock; a parent-managed variation has no independent quantity.
        amount = _decimal(payload.get("stock_quantity"))
        updated = _revision(payload.get("date_modified_gmt") or payload.get("date_modified"))
        identity_id = _provider_identity_id(conn, source_id, "woocommerce", product_id)
        fingerprint = _digest({"product": product_id, "quantity_type": "woocommerce_stock_quantity",
                               "quantity": str(amount), "updatedAt": updated})
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM public.keel_inventory_observation_record96(%s::uuid,%s,%s,%s::uuid,NULL,'woocommerce_stock_quantity',%s::numeric,%s,%s::timestamptz,%s::uuid,%s::uuid,%s)",
                (source_id, product_id, product_id, identity_id, amount, updated, updated,
                 ingestion_job_id, receipt_id, fingerprint),
            )
            observation_id, status, duplicate = cursor.fetchone()
        output.append({"inventory_observation_id": str(observation_id), "reconciliation_status": status,
                       "duplicate": bool(duplicate), "provider": "woocommerce",
                       "quantity_semantics": "woocommerce_stock_quantity"})
    return output


def register_canonical_inventory_location(conn, location_key: str, display_name: str) -> str:
    """Internal owner/admin primitive; this module intentionally adds no API route."""
    if not isinstance(location_key, str) or not isinstance(display_name, str):
        raise InventoryProvenanceError("canonical location is invalid")
    with conn.cursor() as cursor:
        cursor.execute("SELECT public.keel_inventory_location_register96(%s,%s)", (location_key, display_name))
        return str(cursor.fetchone()[0])


def decide_provider_location_association(conn, source_id: str, provider_location_identity_id: str,
                                         decision: str, canonical_location_id: str | None,
                                         evidence_code: str | None = None) -> str:
    if decision not in {"associate", "revoke"} or (decision == "associate") != (canonical_location_id is not None):
        raise InventoryProvenanceError("location association decision is invalid")
    with conn.cursor() as cursor:
        cursor.execute("SELECT public.keel_inventory_location_decide96(%s::uuid,%s::uuid,%s,%s::uuid,%s)",
                       (source_id, provider_location_identity_id, decision, canonical_location_id, evidence_code))
        return str(cursor.fetchone()[0])


def decide_inventory_authority(conn, *, canonical_product_id: str, quantity_semantics: str,
                               decision: str, authority_kind: str, canonical_location_id: str | None = None,
                               source_id: str | None = None, provider: str | None = None,
                               provider_record_identity_id: str | None = None,
                               provider_location_identity_id: str | None = None,
                               evidence_code: str | None = None) -> str:
    """Owner/admin-only decision primitive. Actor identity is database context-derived."""
    if decision not in {"select", "revoke"} or authority_kind not in {"provider", "manual"}:
        raise InventoryProvenanceError("inventory authority decision is invalid")
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT public.keel_inventory_authority_decide96(%s::uuid,%s::uuid,%s,%s,%s,%s::uuid,%s,%s::uuid,%s::uuid,%s)",
            (canonical_product_id, canonical_location_id, quantity_semantics, decision, authority_kind,
             source_id, provider, provider_record_identity_id, provider_location_identity_id, evidence_code),
        )
        return str(cursor.fetchone()[0])


def _read_limit(limit: int) -> int:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
        raise InventoryProvenanceError("inventory history limit must be between 1 and 500")
    return limit


def list_inventory_observation_history(conn, *, canonical_product_id: str | None = None,
                                       source_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    """Read nonsecret inventory evidence within the already-bound tenant context."""
    predicates = ["tenant_id=public.get_current_tenant()"]
    params: list[Any] = []
    if canonical_product_id is not None:
        predicates.append("canonical_product_id=%s::uuid")
        params.append(canonical_product_id)
    if source_id is not None:
        predicates.append("source_id=%s::uuid")
        params.append(source_id)
    params.append(_read_limit(limit))
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT inventory_observation_id,source_id,provider,provider_inventory_record_id,"
            "provider_product_record_id,provider_record_identity_id,provider_location_identity_id,"
            "canonical_product_id,canonical_location_id,quantity_semantics,quantity,provider_revision,"
            "provider_updated_at,ingestion_job_id,receipt_id,observation_sha256,reconciliation_status,observed_at "
            "FROM public.keel_inventory_observations WHERE " + " AND ".join(predicates) +
            " ORDER BY observed_at DESC,inventory_observation_id LIMIT %s",
            tuple(params),
        )
        columns = [column.name for column in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]


def list_inventory_authority_history(conn, *, canonical_product_id: str,
                                     canonical_location_id: str | None = None,
                                     quantity_semantics: str | None = None,
                                     limit: int = 100) -> list[dict[str, Any]]:
    """Read explicit selection/revocation history; actor IDs come from persisted audit rows."""
    predicates = ["tenant_id=public.get_current_tenant()", "canonical_product_id=%s::uuid"]
    params: list[Any] = [canonical_product_id]
    predicates.append("canonical_location_id IS NOT DISTINCT FROM %s::uuid")
    params.append(canonical_location_id)
    if quantity_semantics is not None:
        predicates.append("quantity_semantics=%s")
        params.append(quantity_semantics)
    params.append(_read_limit(limit))
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT authority_decision_id,canonical_product_id,canonical_location_id,quantity_semantics,"
            "decision,decision_sequence,authority_kind,source_id,provider,provider_record_identity_id,"
            "provider_location_identity_id,prior_decision_id,actor_user_id,evidence_code,decided_at "
            "FROM public.keel_inventory_authority_decisions WHERE " + " AND ".join(predicates) +
            " ORDER BY decision_sequence DESC LIMIT %s",
            tuple(params),
        )
        columns = [column.name for column in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]


def list_provider_inventory_location_history(conn, source_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
    """Read provider location identity plus safe status/review history for this tenant source."""
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT l.provider_location_identity_id,l.source_id,l.provider,l.provider_location_id,"
            "o.display_name,o.provider_active,o.provider_revision,o.provider_updated_at,o.observed_at,"
            "d.location_decision_id,d.decision,d.canonical_location_id,d.actor_user_id,d.decided_at "
            "FROM public.keel_provider_inventory_locations l "
            "LEFT JOIN LATERAL (SELECT lo.* FROM public.keel_provider_inventory_location_observations lo "
            " WHERE lo.tenant_id=l.tenant_id AND lo.source_id=l.source_id AND lo.provider_location_identity_id=l.provider_location_identity_id "
            " ORDER BY lo.observed_at DESC,lo.location_observation_id DESC LIMIT 1) o ON TRUE "
            "LEFT JOIN LATERAL (SELECT ld.* FROM public.keel_inventory_location_decisions ld "
            " WHERE ld.tenant_id=l.tenant_id AND ld.source_id=l.source_id AND ld.provider_location_identity_id=l.provider_location_identity_id "
            " ORDER BY ld.decision_sequence DESC LIMIT 1) d ON TRUE "
            "WHERE l.tenant_id=public.get_current_tenant() AND l.source_id=%s::uuid "
            "ORDER BY l.first_verified_at DESC,l.provider_location_identity_id LIMIT %s",
            (source_id, _read_limit(limit)),
        )
        columns = [column.name for column in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
