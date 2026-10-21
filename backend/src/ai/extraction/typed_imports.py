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
            output["validation_outcome"] = (
                "review_required" if all(f["code"].endswith("requires_review") for f in output["validation_findings"])
                else "invalid"
            )
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
        if outcome.staging_row_id is not None:
            with conn.cursor() as cursor:
                cursor.execute("SELECT validation_errors FROM public.import_staging_rows WHERE tenant_id=%s::uuid AND job_id=%s::uuid AND staging_row_id=%s",
                               (tenant_id, job_id, outcome.staging_row_id))
                staged = cursor.fetchone()
            staging_errors = staged[0] if staged else None
            if isinstance(staging_errors, str):
                try:
                    staging_errors = json.loads(staging_errors)
                except (TypeError, ValueError):
                    staging_errors = None
            if isinstance(staging_errors, Mapping) and staging_errors.get("product_identity"):
                findings.append({"field": "product_reference", "code": "product_identity_requires_review"})
        row = validate_typed_import_row("sales", values, source_row_key=f"row:{outcome.row_index}",
               staging_row_id=outcome.staging_row_id, row_number=outcome.row_index,
               source_provenance={"existing_staging_row": outcome.staging_row_id} if outcome.staging_row_id is not None else {})
        if findings:
            row["validation_findings"].extend(findings)
            row["validation_outcome"] = (
                "review_required" if all(f["code"].endswith("requires_review") for f in row["validation_findings"])
                else "invalid"
            )
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
            output["validation_outcome"] = (
                "review_required" if all(f["code"].endswith("requires_review") for f in output["validation_findings"])
                else "invalid"
            )
    digest = _fingerprint(validated)
    with conn.cursor() as cursor:
        cursor.execute("SELECT * FROM public.keel_import_revision_create97(%s::uuid,%s,%s,%s,%s::jsonb,%s::jsonb)",
                       (batch_id, schema_version, idempotency_key, digest, json.dumps(validated), json.dumps(dict(provenance or {}))))
        revision_id, duplicate = cursor.fetchone()
    return {"revision_id": str(revision_id), "duplicate": bool(duplicate), "row_count": len(validated)}


def list_import_drafts(conn, *, limit: int = 50, offset: int = 0, category: str | None = None,
                       state: str | None = None) -> list[dict[str, Any]]:
    """List tenant-visible draft metadata without returning uploaded file contents."""
    if not 1 <= limit <= 100 or offset < 0:
        raise TypedImportError("pagination is invalid")
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT b.batch_id,b.source_id,b.job_id,b.import_category,b.schema_version,
                   b.current_revision_id,b.lifecycle_state,b.created_at,b.updated_at,
                   s.source_name,s.source_type,j.job_status,
                   count(r.draft_row_id)::int,
                   count(r.draft_row_id) FILTER (WHERE r.validation_outcome='invalid')::int,
                   count(r.draft_row_id) FILTER (WHERE r.validation_outcome='review_required')::int,
                   count(r.draft_row_id) FILTER (WHERE st.validation_status='COMMITTED'
                       AND st.committed_table IS NOT NULL AND st.committed_record_id IS NOT NULL)::int
            FROM public.keel_import_batches b
            JOIN public.data_sources s ON s.tenant_id=b.tenant_id AND s.source_id=b.source_id
            JOIN public.ingestion_jobs j ON j.tenant_id=b.tenant_id AND j.source_id=b.source_id AND j.job_id=b.job_id
            LEFT JOIN public.keel_import_draft_rows r ON r.tenant_id=b.tenant_id AND r.batch_id=b.batch_id
                 AND r.revision_id=b.current_revision_id
            LEFT JOIN public.import_staging_rows st ON st.tenant_id=r.tenant_id AND st.staging_row_id=r.staging_row_id
            WHERE b.tenant_id=public.get_current_tenant()
              AND (%s::text IS NULL OR b.import_category=%s)
              AND (%s::text IS NULL OR b.lifecycle_state=%s)
            GROUP BY b.tenant_id,b.batch_id,b.source_id,b.job_id,b.import_category,b.schema_version,
                     b.current_revision_id,b.lifecycle_state,b.created_at,b.updated_at,
                     s.source_name,s.source_type,j.job_status
            ORDER BY b.created_at DESC,b.batch_id
            LIMIT %s OFFSET %s
            """,
            (category, category, state, state, limit, offset),
        )
        rows = cursor.fetchall()
    return [{
        "batch_id": str(r[0]), "source_id": str(r[1]), "job_id": str(r[2]), "category": r[3],
        "schema_version": r[4], "revision_id": str(r[5]), "state": r[6],
        "created_at": r[7], "updated_at": r[8], "source_name": r[9], "source_type": r[10],
        "ingestion_status": r[11], "row_count": r[12], "invalid_row_count": r[13],
        "review_required_row_count": r[14], "canonically_committed_row_count": r[15],
        "review_status": r[6], "posting_status": "partially_committed" if 0 < r[15] < r[12]
                          else "committed" if r[12] and r[15] == r[12] else "not_committed",
    } for r in rows]


def get_import_revisions(conn, batch_id: str) -> list[dict[str, Any]]:
    """Return immutable revision metadata for a tenant-visible batch."""
    with conn.cursor() as cursor:
        cursor.execute(
            """SELECT revision_id,revision_number,prior_revision_id,schema_version,revision_sha256,
                      source_provenance,created_by_user_id,created_at
               FROM public.keel_import_revisions
               WHERE tenant_id=public.get_current_tenant() AND batch_id=%s::uuid
               ORDER BY revision_number""", (batch_id,),
        )
        rows = cursor.fetchall()
    return [{"revision_id": str(r[0]), "revision_number": r[1],
             "prior_revision_id": str(r[2]) if r[2] else None, "schema_version": r[3],
             "content_sha256": r[4].strip(), "source_provenance": r[5],
             "created_by_user_id": str(r[6]) if r[6] else None, "created_at": r[7]} for r in rows]


def get_import_review_history(conn, batch_id: str, revision_id: str | None = None) -> list[dict[str, Any]]:
    """Return immutable review history with internal actor IDs, never profile data."""
    with conn.cursor() as cursor:
        cursor.execute(
            """SELECT decision_id,revision_id,draft_row_id,decision,reason_code,reviewer_user_id,
                      prior_decision_id,created_at
               FROM public.keel_import_review_decisions
               WHERE tenant_id=public.get_current_tenant() AND batch_id=%s::uuid
                 AND (%s::uuid IS NULL OR revision_id=%s::uuid)
               ORDER BY created_at,decision_id""", (batch_id, revision_id, revision_id),
        )
        rows = cursor.fetchall()
    return [{"decision_id": str(r[0]), "revision_id": str(r[1]),
             "draft_row_id": str(r[2]) if r[2] else None, "decision": r[3],
             "reason_code": r[4], "reviewer_user_id": str(r[5]),
             "prior_decision_id": str(r[6]) if r[6] else None, "created_at": r[7]} for r in rows]


def get_import_draft(conn, batch_id: str, revision_id: str | None = None) -> dict[str, Any] | None:
    """Read an import draft through tenant RLS; never exposes original raw upload payloads."""
    with conn.cursor() as cursor:
        cursor.execute("""SELECT b.batch_id,b.source_id,b.job_id,b.import_category,b.schema_version,
                                 b.current_revision_id,b.lifecycle_state,b.created_at,b.updated_at,
                                 s.source_name,s.source_type,j.job_status
                          FROM public.keel_import_batches b
                          JOIN public.data_sources s ON s.tenant_id=b.tenant_id AND s.source_id=b.source_id
                          JOIN public.ingestion_jobs j ON j.tenant_id=b.tenant_id AND j.source_id=b.source_id AND j.job_id=b.job_id
                          WHERE b.tenant_id=public.get_current_tenant() AND b.batch_id=%s::uuid""", (batch_id,))
        batch = cursor.fetchone()
        if not batch:
            return None
        selected_revision = revision_id or str(batch[5])
        cursor.execute("SELECT revision_id,revision_number,prior_revision_id,schema_version,created_at FROM public.keel_import_revisions "
                       "WHERE tenant_id=public.get_current_tenant() AND batch_id=%s::uuid AND revision_id=%s::uuid",
                       (batch_id, selected_revision))
        revision = cursor.fetchone()
        if not revision:
            return None
        cursor.execute("""SELECT r.draft_row_id,r.source_row_key,r.staging_row_id,r.row_number,r.typed_values,
                                 r.validation_findings,r.validation_outcome,r.product_candidate,r.ambiguity_code,
                                 st.validation_status,st.validation_errors,st.committed_table,st.committed_record_id
                          FROM public.keel_import_draft_rows r
                          LEFT JOIN public.import_staging_rows st ON st.tenant_id=r.tenant_id AND st.staging_row_id=r.staging_row_id
                          WHERE r.tenant_id=public.get_current_tenant() AND r.batch_id=%s::uuid AND r.revision_id=%s::uuid
                          ORDER BY r.row_number""", (batch_id, selected_revision))
        rows = cursor.fetchall()
    decisions = get_import_review_history(conn, batch_id, selected_revision)
    latest = {}
    for decision in decisions:
        latest[decision["draft_row_id"]] = decision
    committed_count = sum(1 for r in rows if r[9] == "COMMITTED" and r[11] and r[12])
    posting_status = (
        "committed" if rows and committed_count == len(rows)
        else "partially_committed" if committed_count
        else "not_committed"
    )
    return {"batch_id": str(batch[0]), "source_id": str(batch[1]), "job_id": str(batch[2]), "category": batch[3],
            "schema_version": batch[4], "revision_id": str(revision[0]), "current_revision_id": str(batch[5]),
            "is_current_revision": str(revision[0]) == str(batch[5]), "state": batch[6], "created_at": batch[7],
            "updated_at": batch[8], "source_name": batch[9], "source_type": batch[10],
            "ingestion_status": batch[11], "revision_number": revision[1],
            "prior_revision_id": str(revision[2]) if revision[2] else None,
            "review_status": batch[6], "posting_status": posting_status,
            "rows": [{"draft_row_id": str(r[0]), "source_row_key": r[1], "staging_row_id": r[2], "row_number": r[3],
                      "typed_values": r[4], "validation_findings": r[5], "validation_outcome": r[6],
                      "product_candidate": r[7], "ambiguity_code": r[8],
                      "review_decision": latest.get(str(r[0])),
                      "staging_status": r[9], "staging_findings": r[10],
                      "canonical_posting_status": "committed" if r[9] == "COMMITTED" and r[11] and r[12] else "not_committed",
                      "canonical_table": r[11] if r[9] == "COMMITTED" and r[12] else None,
                      "canonical_record_id": str(r[12]) if r[9] == "COMMITTED" and r[12] else None} for r in rows],
            "review_history": decisions}
