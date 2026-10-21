"""Typed, immutable import draft persistence layered over existing ingestion.

Draft approval records review evidence only. It never posts invoices or writes
canonical stock. Existing sales promotion remains the established authority.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence


class TypedImportError(ValueError):
    pass


_CURRENCY = re.compile(r"^[A-Z]{3}$")
_SAFE_FIELDS = {
    "sales": {"product_name", "quantity", "unit_price", "currency", "transaction_date", "invoice_id", "order_id", "amount_raw", "barcode"},
    "invoice": {"invoice_id", "invoice_date", "currency", "product_id", "provider_product_id", "product_name", "quantity", "unit_price", "line_total"},
    "inventory": {"product_id", "provider_product_id", "product_name", "quantity", "quantity_semantics", "unit", "location_id", "provider_location_id", "observed_at"},
}


def _decimal(value: Any, *, positive: bool = False) -> str | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not parsed.is_finite() or (positive and parsed <= 0):
        return None
    return str(parsed)


def validate_typed_import_row(category: str, values: Mapping[str, Any], *, source_row_key: str,
                              staging_row_id: int | None = None, row_number: int = 0,
                              source_provenance: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Validate only established field contracts and return a safe typed row."""
    if category not in _SAFE_FIELDS or not isinstance(values, Mapping):
        raise TypedImportError("unsupported import category or row shape")
    if not isinstance(source_row_key, str) or not source_row_key.strip() or len(source_row_key) > 180:
        raise TypedImportError("source row identity is invalid")
    safe = {k: v for k, v in values.items() if k in _SAFE_FIELDS[category] and v is not None}
    findings: list[dict[str, str]] = []

    def required(name: str) -> None:
        if safe.get(name) in (None, ""):
            findings.append({"field": name, "code": "required"})

    if category == "sales":
        for name in ("product_name", "quantity", "unit_price", "currency", "transaction_date"):
            required(name)
    elif category == "invoice":
        for name in ("invoice_id", "invoice_date", "currency", "quantity", "unit_price"):
            required(name)
        if not any(safe.get(k) not in (None, "") for k in ("product_id", "provider_product_id", "product_name")):
            findings.append({"field": "product_reference", "code": "required"})
    else:
        required("quantity")
        if not any(safe.get(k) not in (None, "") for k in ("product_id", "provider_product_id")):
            findings.append({"field": "product_reference", "code": "required"})
        if not safe.get("quantity_semantics"):
            findings.append({"field": "quantity_semantics", "code": "required"})
        elif safe["quantity_semantics"] not in {"available", "on_hand", "woocommerce_stock_quantity", "stock_quantity"}:
            findings.append({"field": "quantity_semantics", "code": "unsupported_semantics"})

    for name in ("quantity",):
        if safe.get(name) not in (None, ""):
            normalized = _decimal(safe[name], positive=True)
            if normalized is None:
                findings.append({"field": name, "code": "must_be_positive_number"})
            else:
                safe[name] = normalized
    for name in ("unit_price", "line_total", "amount_raw"):
        if safe.get(name) not in (None, ""):
            normalized = _decimal(safe[name])
            if normalized is None or Decimal(normalized) < 0:
                findings.append({"field": name, "code": "must_be_nonnegative_number"})
            else:
                safe[name] = normalized
    if safe.get("currency") not in (None, ""):
        safe["currency"] = str(safe["currency"]).upper()
        if not _CURRENCY.fullmatch(safe["currency"]):
            findings.append({"field": "currency", "code": "invalid_currency_code"})
    for field in ("transaction_date", "invoice_date"):
        if safe.get(field) not in (None, ""):
            try:
                date.fromisoformat(str(safe[field])[:10])
            except (ValueError, TypeError):
                findings.append({"field": field, "code": "invalid_date"})
    if safe.get("observed_at") not in (None, ""):
        try:
            datetime.fromisoformat(str(safe["observed_at"]).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            findings.append({"field": "observed_at", "code": "invalid_timestamp"})

    candidate = None
    if safe.get("product_id") is not None or safe.get("provider_product_id") is not None or safe.get("product_name") is not None:
        candidate = {k: safe[k] for k in ("product_id", "provider_product_id", "product_name") if safe.get(k) is not None}
    if category in {"invoice", "inventory"} and safe.get("provider_product_id") and not safe.get("product_id"):
        findings.append({"field": "product_reference", "code": "provider_identity_requires_review"})
    if category == "inventory" and safe.get("provider_location_id") and not safe.get("location_id"):
        findings.append({"field": "location_id", "code": "provider_location_requires_review"})
    outcome = "valid" if not findings else (
        "review_required" if all(f["code"].endswith("requires_review") for f in findings) else "invalid"
    )
    return {
        "source_row_key": source_row_key,
        "staging_row_id": staging_row_id,
        "row_number": row_number,
        "typed_values": safe,
        "validation_findings": findings,
        "validation_outcome": outcome,
        "product_candidate": candidate,
        "ambiguity_code": next((f["code"] for f in findings if f["code"].endswith("requires_review")), None),
        "source_provenance": dict(source_provenance or {}),
    }


def _fingerprint(rows: Sequence[Mapping[str, Any]]) -> str:
    body = json.dumps(list(rows), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def persist_import_draft(conn, *, tenant_id: str, actor_id: str, source_id: str, job_id: str,
                         category: str, rows: Sequence[Mapping[str, Any]], schema_version: str = "1",
                         idempotency_key: str | None = None, provenance: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Persist a validated batch through the tenant-context-bound M97 function."""
    if category not in _SAFE_FIELDS:
        raise TypedImportError("unsupported import category")
    validated = [validate_typed_import_row(category, row.get("typed_values", row),
                 source_row_key=str(row.get("source_row_key", index)),
                 staging_row_id=row.get("staging_row_id"), row_number=int(row.get("row_number", index)),
                 source_provenance=row.get("source_provenance")) for index, row in enumerate(rows)]
    for output, supplied in zip(validated, rows):
        extra = supplied.get("validation_findings", [])
        if isinstance(extra, list):
            for finding in extra:
                if isinstance(finding, Mapping) and isinstance(finding.get("field"), str) and isinstance(finding.get("code"), str):
                    output["validation_findings"].append({"field": finding["field"][:80], "code": finding["code"][:100]})
        if output["validation_findings"] and output["validation_outcome"] == "valid":
            output["validation_outcome"] = "invalid"
    digest = _fingerprint(validated)
    idem = idempotency_key or f"{category}:{job_id}"
    with conn.cursor() as cursor:
        cursor.execute("SELECT public.get_current_tenant(), nullif(current_setting('app.current_user_id',true),'')::uuid")
        context = cursor.fetchone()
        if not context or str(context[0]) != str(tenant_id) or str(context[1]) != str(actor_id):
            raise TypedImportError("authenticated tenant and actor context is required")
        cursor.execute(
            "SELECT * FROM public.keel_import_batch_create97(%s::uuid,%s::uuid,%s,%s,%s,%s,%s::jsonb,%s::jsonb)",
            (source_id, job_id, category, schema_version, idem, digest,
             json.dumps(validated, separators=(",", ":")), json.dumps(dict(provenance or {}), separators=(",", ":"))),
        )
        batch_id, revision_id, duplicate = cursor.fetchone()
    return {"batch_id": str(batch_id), "revision_id": str(revision_id), "duplicate": bool(duplicate),
            "category": category, "row_count": len(validated)}


def record_sales_extraction_draft(conn, *, tenant_id: str, actor_id: str, job_id: str, summary: Any) -> dict[str, Any]:
    """Create a draft from existing extraction staging without changing its promotion path."""
    with conn.cursor() as cursor:
        cursor.execute("SELECT source_id FROM public.ingestion_jobs WHERE tenant_id=%s::uuid AND job_id=%s::uuid", (tenant_id, job_id))
        found = cursor.fetchone()
        if not found:
            raise TypedImportError("ingestion job is unavailable in this tenant")
        source_id = str(found[0])
    rows = []
    for outcome in summary.row_outcomes:
        parsed = outcome.parse_result
        values = parsed.typed_fields if parsed is not None else {}
        findings = [{"field": field, "code": "existing_validator_rejected"} for field in outcome.field_errors]
        if outcome.error:
            findings.append({"field": "row", "code": "existing_extractor_rejected"})
        row = validate_typed_import_row("sales", values, source_row_key=f"row:{outcome.row_index}",
               staging_row_id=outcome.staging_row_id, row_number=outcome.row_index,
               source_provenance={"existing_staging_row": outcome.staging_row_id} if outcome.staging_row_id is not None else {})
        if findings:
            row["validation_findings"].extend(findings)
            row["validation_outcome"] = "invalid"
        rows.append(row)
    return persist_import_draft(conn, tenant_id=tenant_id, actor_id=actor_id, source_id=source_id,
                                job_id=job_id, category="sales", rows=rows,
                                provenance={"pipeline": "python_extraction", "kind": "sales"})


def decide_import_review(conn, *, batch_id: str, revision_id: str, decision: str,
                         idempotency_key: str, reason_code: str, row_id: str | None = None) -> dict[str, Any]:
    if decision not in {"approve", "reject"}:
        raise TypedImportError("review decision is invalid")
    with conn.cursor() as cursor:
        cursor.execute("SELECT * FROM public.keel_import_review_decide97(%s::uuid,%s::uuid,%s::uuid,%s,%s,%s)",
                       (batch_id, revision_id, row_id, decision, idempotency_key, reason_code))
        identifier, duplicate = cursor.fetchone()
    return {"decision_id": str(identifier), "duplicate": bool(duplicate), "decision": decision,
            "canonical_write_performed": False}


def create_import_revision(conn, *, batch_id: str, category: str, rows: Sequence[Mapping[str, Any]],
                           schema_version: str = "1", idempotency_key: str = "revision",
                           provenance: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if category not in _SAFE_FIELDS:
        raise TypedImportError("unsupported import category")
    validated = [validate_typed_import_row(category, row.get("typed_values", row),
                 source_row_key=str(row.get("source_row_key", index)), staging_row_id=row.get("staging_row_id"),
                 row_number=int(row.get("row_number", index)), source_provenance=row.get("source_provenance"))
                 for index, row in enumerate(rows)]
    for output, supplied in zip(validated, rows):
        for finding in supplied.get("validation_findings", []):
            if isinstance(finding, Mapping) and isinstance(finding.get("field"), str) and isinstance(finding.get("code"), str):
                output["validation_findings"].append({"field": finding["field"][:80], "code": finding["code"][:100]})
        if output["validation_findings"] and output["validation_outcome"] == "valid":
            output["validation_outcome"] = "invalid"
    digest = _fingerprint(validated)
    with conn.cursor() as cursor:
        cursor.execute("SELECT * FROM public.keel_import_revision_create97(%s::uuid,%s,%s,%s,%s::jsonb,%s::jsonb)",
                       (batch_id, schema_version, idempotency_key, digest, json.dumps(validated), json.dumps(dict(provenance or {}))))
        revision_id, duplicate = cursor.fetchone()
    return {"revision_id": str(revision_id), "duplicate": bool(duplicate), "row_count": len(validated)}


def get_import_draft(conn, batch_id: str) -> dict[str, Any] | None:
    """Read an import draft through tenant RLS; never exposes original raw upload payloads."""
    with conn.cursor() as cursor:
        cursor.execute("SELECT batch_id,source_id,job_id,import_category,schema_version,current_revision_id,lifecycle_state,created_at "
                       "FROM public.keel_import_batches WHERE tenant_id=public.get_current_tenant() AND batch_id=%s::uuid", (batch_id,))
        batch = cursor.fetchone()
        if not batch:
            return None
        cursor.execute("SELECT draft_row_id,source_row_key,staging_row_id,row_number,typed_values,validation_findings,validation_outcome,product_candidate,ambiguity_code "
                       "FROM public.keel_import_draft_rows WHERE tenant_id=public.get_current_tenant() AND batch_id=%s::uuid AND revision_id=%s::uuid ORDER BY row_number",
                       (batch_id, str(batch[5])))
        rows = cursor.fetchall()
    return {"batch_id": str(batch[0]), "source_id": str(batch[1]), "job_id": str(batch[2]), "category": batch[3],
            "schema_version": batch[4], "revision_id": str(batch[5]), "state": batch[6], "created_at": batch[7],
            "rows": [{"draft_row_id": str(r[0]), "source_row_key": r[1], "staging_row_id": r[2], "row_number": r[3],
                      "typed_values": r[4], "validation_findings": r[5], "validation_outcome": r[6],
                      "product_candidate": r[7], "ambiguity_code": r[8]} for r in rows]}
