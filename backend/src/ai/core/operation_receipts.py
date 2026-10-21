"""Durable, tenant-scoped orchestration receipts for ENT-008 operations.

Receipts are an outbox and execution fence only. Existing usage counters and
Data/AI Credit ledgers remain the sole accounting authorities.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime, timezone
from typing import Any

from fastapi import HTTPException

from src.ai.core import usage

OPERATION_TYPE = "reviewed_source_collection"
COMPETITOR_ENRICHMENT = "competitor_enrichment"
SCHEDULED_CONNECTOR_SYNC = "scheduled_connector_sync"
SUPPORTED_OPERATION_TYPES = (OPERATION_TYPE, COMPETITOR_ENRICHMENT, SCHEDULED_CONNECTOR_SYNC)
ACTIVE_STATES = (
    "dispatch_pending", "queued", "claimed", "authorized", "provider_started",
    "retryable", "reconciliation_required",
)


class ReceiptError(RuntimeError):
    """Base class for fail-closed receipt errors."""


class ReceiptAuthorizationError(ReceiptError):
    pass


class ReceiptConflict(ReceiptError):
    pass


class ReceiptLeaseLost(ReceiptError):
    pass


class ReceiptSourceChanged(ReceiptAuthorizationError):
    """The connector configuration changed while its sync was running."""


class ReceiptUncertain(ReceiptError):
    pass


class FencedConnection:
    """Connection proxy that fences every canonical transaction commit."""

    def __init__(self, conn, receipt: dict):
        self._conn = conn
        self._receipt = receipt

    def commit(self):
        try:
            assert_fence(self._conn, self._receipt)
        except Exception:
            self._conn.rollback()
            raise
        return self._conn.commit()

    def __getattr__(self, name):
        return getattr(self._conn, name)


def source_fingerprint(tenant_id: str, source_id: str) -> str:
    payload = json.dumps(
        {"operation": OPERATION_TYPE, "tenant_id": str(tenant_id), "source_id": str(source_id)},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def operation_fingerprint(operation_type: str, tenant_id: str, target_kind: str,
                          target_id: str, request_payload: dict | None = None) -> str:
    payload = json.dumps(
        {"operation": operation_type, "tenant_id": str(tenant_id), "target_kind": target_kind,
         "target_id": str(target_id), "request": request_payload or {}},
        sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def connector_source_fingerprint(collector_config: dict | None, encrypted_credentials: str | None) -> str:
    """Fingerprint persisted connector settings without exposing credentials.

    Credentials enter this value only as their already-encrypted vault envelope.
    The digest is runtime fencing metadata, never an authorization credential.
    """
    payload = json.dumps(
        {"config": collector_config or {}, "encrypted_credentials": encrypted_credentials or ""},
        sort_keys=True, separators=(",", ":"), default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _principal_is_active(conn, tenant_id: str, actor_user_id: str) -> bool:
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT public.keel_active_principal(%s::uuid, %s::uuid);",
            (actor_user_id, tenant_id),
        )
        row = cursor.fetchone()
    return bool(row and row[0] is True)


def authorize_collection(conn, tenant_id: str, source_id: str, actor_user_id: str,
                         expected_period: date | None = None) -> dict:
    """Revalidate the existing router entitlement, principal, source and period."""
    if not _principal_is_active(conn, tenant_id, actor_user_id):
        raise ReceiptAuthorizationError("active principal required")
    plan = usage.get_plan(conn, tenant_id)
    try:
        usage._require_active(plan, usage.COMPETITOR_MANAGEMENT)
    except (usage.PlanLimitReached, KeyError) as exc:
        raise ReceiptAuthorizationError("competitor collection is not currently authorized") from exc
    if expected_period is not None and plan["period_start"] != expected_period:
        raise ReceiptAuthorizationError("billing period changed after enqueue")
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM public.data_sources "
            "WHERE tenant_id = %s::uuid AND source_id = %s::uuid "
            "AND is_active IS TRUE AND policy_status = 'ALLOWED';",
            (tenant_id, source_id),
        )
        if cursor.fetchone() is None:
            raise ReceiptAuthorizationError("source is no longer active and approved")
    return plan


def authorize_operation(conn, operation_type: str, tenant_id: str, target_kind: str,
                        target_id: str, actor_user_id: str,
                        expected_period: date | None = None) -> dict:
    """Revalidate the operation-specific existing Python authorization."""
    if operation_type == OPERATION_TYPE and target_kind == "source":
        return authorize_collection(conn, tenant_id, target_id, actor_user_id, expected_period)
    if operation_type not in SUPPORTED_OPERATION_TYPES or not _principal_is_active(conn, tenant_id, actor_user_id):
        raise ReceiptAuthorizationError("active tenant principal required")

    plan = usage.get_plan(conn, tenant_id)
    if operation_type == COMPETITOR_ENRICHMENT and target_kind == "competitor":
        try:
            usage._require_active(plan, usage.COMPETITOR_MANAGEMENT)
        except (usage.PlanLimitReached, KeyError) as exc:
            raise ReceiptAuthorizationError("competitor enrichment is not currently authorized") from exc
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM public.tenant_competitors tc "
                "JOIN public.global_competitors gc ON gc.global_competitor_id=tc.global_competitor_id "
                "WHERE tc.tenant_id=%s::uuid AND tc.global_competitor_id=%s::uuid "
                "AND tc.is_tracked IS TRUE AND gc.visibility='PRIVATE' AND gc.added_by_tenant_id=tc.tenant_id;",
                (tenant_id, target_id),
            )
            if cursor.fetchone() is None:
                raise ReceiptAuthorizationError("competitor is not tracked by this tenant")
    elif operation_type == SCHEDULED_CONNECTOR_SYNC and target_kind == "source":
        # Capacity is consumed when a persistent connection is created, not when it syncs.
        try:
            usage._require_active(plan, usage.CONNECTED_DATA_SOURCES)
        except (usage.PlanLimitReached, KeyError) as exc:
            raise ReceiptAuthorizationError("connector synchronization requires an active subscription") from exc
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM public.data_sources WHERE tenant_id=%s::uuid AND source_id=%s::uuid "
                "AND is_active IS TRUE AND policy_status='ALLOWED' "
                "AND collector_key IN ('db_connector','api_connector');",
                (tenant_id, target_id),
            )
            if cursor.fetchone() is None:
                raise ReceiptAuthorizationError("source is not an active approved connector for this tenant")
    else:
        raise ReceiptAuthorizationError("operation target does not match its operation type")

    if expected_period is not None and plan["period_start"] != expected_period:
        raise ReceiptAuthorizationError("billing period changed after enqueue")
    return plan


def _validate_request_payload(operation_type: str, request_payload: dict | None) -> dict:
    payload = dict(request_payload or {})
    if operation_type == COMPETITOR_ENRICHMENT:
        if set(payload) - {"facets", "depth", "mode"}:
            raise ReceiptError("unsupported competitor enrichment receipt parameter")
        if "facets" in payload and (not isinstance(payload["facets"], list)
                                     or any(not isinstance(value, str) for value in payload["facets"])):
            raise ReceiptError("facets must be a list of strings")
        if payload.get("depth", "standard") not in {"standard", "deep"}:
            raise ReceiptError("unsupported enrichment depth")
        if payload.get("mode", "single") not in {"single", "due", "force", "comments"}:
            raise ReceiptError("unsupported enrichment mode")
    elif payload:
        raise ReceiptError("this operation does not accept request parameters")
    return payload


def create_or_get_operation(conn, operation_type: str, tenant_id: str, target_kind: str,
                            target_id: str, actor_user_id: str,
                            principal_kind: str = "user", request_payload: dict | None = None) -> dict:
    """Persist sanitized, tenant-scoped intent before signaling a worker."""
    if operation_type not in SUPPORTED_OPERATION_TYPES or principal_kind not in {"user", "service"} or not actor_user_id:
        raise ReceiptAuthorizationError("supported operation and authenticated tenant principal required")
    if ((operation_type == COMPETITOR_ENRICHMENT and target_kind != "competitor")
            or (operation_type != COMPETITOR_ENRICHMENT and target_kind != "source")):
        raise ReceiptAuthorizationError("operation target does not match its operation type")
    params = _validate_request_payload(operation_type, request_payload)
    plan = authorize_operation(conn, operation_type, tenant_id, target_kind, target_id, actor_user_id)
    fingerprint = (source_fingerprint(tenant_id, target_id) if operation_type == OPERATION_TYPE
                   else operation_fingerprint(operation_type, tenant_id, target_kind, target_id, params))
    active_states = list(ACTIVE_STATES)
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT receipt_id,actor_user_id,request_fingerprint,state,period_start "
            "FROM public.keel_operation_receipts WHERE tenant_id=%s::uuid AND operation_type=%s "
            "AND target_kind=%s AND target_id=%s::uuid AND state=ANY(%s) FOR UPDATE;",
            (tenant_id, operation_type, target_kind, target_id, active_states),
        )
        previous = cursor.fetchone()
        if previous:
            if str(previous[1]) != str(actor_user_id) or previous[2] != fingerprint or previous[4] != plan["period_start"]:
                raise ReceiptConflict("active operation identity does not match this request")
            conn.commit()
            return {"receipt_id": str(previous[0]), "state": previous[3], "period_start": previous[4], "created": False}

        receipt_id, key = str(uuid.uuid4()), str(uuid.uuid4())
        source_id = target_id if target_kind == "source" else None
        cursor.execute(
            "INSERT INTO public.keel_operation_receipts "
            "(receipt_id,tenant_id,source_id,operation_type,target_kind,target_id,request_payload, "
            "principal_kind,actor_user_id,period_start,idempotency_key,request_fingerprint,state,provider_outcome) "
            "VALUES (%s::uuid,%s::uuid,%s::uuid,%s,%s,%s::uuid,%s::jsonb,%s,%s::uuid,%s,%s::uuid,%s,'dispatch_pending','not_started') "
            "ON CONFLICT (tenant_id,operation_type,target_kind,target_id) WHERE state IN "
            "('dispatch_pending','queued','claimed','authorized','provider_started','retryable','reconciliation_required') "
            "DO NOTHING RETURNING receipt_id,state,period_start;",
            (receipt_id, tenant_id, source_id, operation_type, target_kind, target_id,
             json.dumps(params, sort_keys=True, separators=(",", ":")), principal_kind, actor_user_id,
             plan["period_start"], key, fingerprint),
        )
        row = cursor.fetchone()
        if row is None:
            cursor.execute(
                "SELECT receipt_id,actor_user_id,request_fingerprint,state,period_start "
                "FROM public.keel_operation_receipts WHERE tenant_id=%s::uuid AND operation_type=%s "
                "AND target_kind=%s AND target_id=%s::uuid AND state=ANY(%s) FOR UPDATE;",
                (tenant_id, operation_type, target_kind, target_id, active_states),
            )
            previous = cursor.fetchone()
            if not previous or str(previous[1]) != str(actor_user_id) or previous[2] != fingerprint or previous[4] != plan["period_start"]:
                conn.rollback()
                raise ReceiptConflict("concurrent operation identity could not be resolved")
            row = (previous[0], previous[3], previous[4])
    conn.commit()
    return {"receipt_id": str(row[0]), "state": row[1], "period_start": row[2],
            "created": str(row[0]) == receipt_id}


def create_or_get_collection(conn, tenant_id: str, source_id: str, actor_user_id: str,
                             principal_kind: str = "user") -> dict:
    """Backward-compatible Stage 1 entry point over the generalized receipt."""
    return create_or_get_operation(conn, OPERATION_TYPE, tenant_id, "source", source_id,
                                   actor_user_id, principal_kind, {})


def mark_queued(conn, tenant_id: str, receipt_id: str) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE public.keel_operation_receipts SET state='queued', updated_at=NOW() "
            "WHERE tenant_id=%s::uuid AND receipt_id=%s::uuid AND state IN ('dispatch_pending','retryable');",
            (tenant_id, receipt_id),
        )
    conn.commit()


def dispatch_pending(conn, tenant_id: str, limit: int = 25,
                     operation_types: tuple[str, ...] = (OPERATION_TYPE,)) -> list[dict]:
    """Return current-tenant outbox rows; Redis remains only a delivery signal."""
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT receipt_id, source_id, operation_type, target_kind, target_id, request_payload "
            "FROM public.keel_operation_receipts "
            "WHERE tenant_id=%s::uuid AND operation_type=ANY(%s) AND state IN ('dispatch_pending','retryable') "
            "ORDER BY created_at LIMIT %s;",
            (tenant_id, list(operation_types), limit),
        )
        rows = cursor.fetchall()
    return [{"receipt_id": str(row[0]), "source_id": str(row[1]) if row[1] else None,
             "operation_type": row[2], "target_kind": row[3], "target_id": str(row[4]),
             "request_payload": row[5]} for row in rows]


def attach_ingestion_job(conn, receipt: dict, job_id: str) -> None:
    """Link the pipeline's existing job record to its operation receipt."""
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE public.keel_operation_receipts SET ingestion_job_id=%s::uuid, updated_at=NOW() "
            "WHERE tenant_id=%s::uuid AND receipt_id=%s::uuid AND state='authorized' "
            "AND lease_owner=%s AND lease_generation=%s "
            "AND (ingestion_job_id IS NULL OR ingestion_job_id=%s::uuid);",
            (job_id, receipt["tenant_id"], receipt["receipt_id"], receipt["worker_id"],
             receipt["lease_generation"], job_id),
        )
        if cursor.rowcount != 1:
            raise ReceiptLeaseLost("ingestion job could not be bound to the authorized receipt")
    receipt["ingestion_job_id"] = str(job_id)


def claim(conn, tenant_id: str, receipt_id: str, worker_id: str,
          lease_seconds: int = 1800) -> dict:
    if not worker_id or lease_seconds <= 0:
        raise ReceiptError("valid worker identity and lease duration required")
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT source_id, actor_user_id, principal_kind, period_start, state, "
            "lease_generation, lease_expires_at, provider_started_at, ingestion_job_id, "
            "operation_type, target_kind, target_id, request_payload "
            "FROM public.keel_operation_receipts "
            "WHERE tenant_id=%s::uuid AND receipt_id=%s::uuid FOR UPDATE;",
            (tenant_id, receipt_id),
        )
        row = cursor.fetchone()
        if row is None:
            raise ReceiptError("receipt not found")
        (source_id, actor_id, principal_kind, period, state, generation, lease_until,
         provider_started, job_id, operation_type, target_kind, target_id, request_payload) = row
        if state in {"completed", "denied", "failed", "reconciliation_required"}:
            conn.commit()
            raise ReceiptError(f"receipt is terminal or requires reconciliation: {state}")
        if state == "provider_started" or provider_started is not None:
            if lease_until is not None and lease_until > datetime.now(timezone.utc):
                conn.commit()
                raise ReceiptConflict("receipt is actively leased by another worker")
            cursor.execute(
                "UPDATE public.keel_operation_receipts SET state='reconciliation_required', "
                "provider_outcome='unknown', lease_owner=NULL, lease_expires_at=NULL, updated_at=NOW() "
                "WHERE tenant_id=%s::uuid AND receipt_id=%s::uuid AND lease_generation=%s;",
                (tenant_id, receipt_id, generation),
            )
            conn.commit()
            raise ReceiptUncertain("provider may have received the operation; automatic retry is blocked")
        if lease_until is not None and lease_until > datetime.now(timezone.utc):
            conn.commit()
            raise ReceiptConflict("receipt is already leased")
        generation = int(generation) + 1
        cursor.execute(
            "UPDATE public.keel_operation_receipts SET state='claimed', attempt_count=attempt_count+1, "
            "lease_owner=%s, lease_expires_at=NOW() + (%s * INTERVAL '1 second'), "
            "lease_generation=%s, updated_at=NOW() "
            "WHERE tenant_id=%s::uuid AND receipt_id=%s::uuid AND lease_generation=%s "
            "RETURNING lease_expires_at;",
            (worker_id, lease_seconds, generation, tenant_id, receipt_id, generation - 1),
        )
        claimed = cursor.fetchone()
        if not claimed:
            conn.rollback()
            raise ReceiptConflict("receipt claim raced with another worker")
    try:
        authorize_operation(conn, operation_type, tenant_id, target_kind, str(target_id), str(actor_id), period)
    except ReceiptAuthorizationError:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE public.keel_operation_receipts SET state='denied', error_code='AUTHORIZATION_REVOKED', "
                "lease_owner=NULL, lease_expires_at=NULL, updated_at=NOW() "
                "WHERE tenant_id=%s::uuid AND receipt_id=%s::uuid AND lease_generation=%s;",
                (tenant_id, receipt_id, generation),
            )
        conn.commit()
        raise
    except Exception:
        conn.rollback()
        raise
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE public.keel_operation_receipts SET state='authorized', updated_at=NOW() "
            "WHERE tenant_id=%s::uuid AND receipt_id=%s::uuid AND lease_owner=%s "
            "AND lease_generation=%s AND state='claimed';",
            (tenant_id, receipt_id, worker_id, generation),
        )
        if cursor.rowcount != 1:
            conn.rollback()
            raise ReceiptLeaseLost("claim was fenced before authorization completed")
    conn.commit()
    return {"receipt_id": receipt_id, "tenant_id": tenant_id,
            "source_id": str(source_id) if source_id else None,
            "operation_type": operation_type, "target_kind": target_kind, "target_id": str(target_id),
            "request_payload": request_payload or {},
            "actor_user_id": str(actor_id), "principal_kind": principal_kind,
            "period_start": period, "worker_id": worker_id, "lease_generation": generation,
            "ingestion_job_id": str(job_id) if job_id else None, "lease_seconds": lease_seconds}


def begin_provider(conn, receipt: dict) -> None:
    """Persist uncertainty before any provider/network side effect."""
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE public.keel_operation_receipts SET state='provider_started', "
            "provider_started_at=NOW(), provider_outcome='unknown', updated_at=NOW() "
            "WHERE tenant_id=%s::uuid AND receipt_id=%s::uuid AND state='authorized' "
            "AND lease_owner=%s AND lease_generation=%s AND lease_expires_at > NOW();",
            (receipt["tenant_id"], receipt["receipt_id"], receipt["worker_id"], receipt["lease_generation"]),
        )
        if cursor.rowcount != 1:
            conn.rollback()
            raise ReceiptLeaseLost("worker lease expired before provider work")
        expected_fingerprint = receipt.get("source_execution_fingerprint")
        if receipt.get("operation_type") == SCHEDULED_CONNECTOR_SYNC and expected_fingerprint:
            cursor.execute(
                "SELECT collector_config, connection_credentials_vault FROM public.data_sources "
                "WHERE tenant_id=%s::uuid AND source_id=%s::uuid AND is_active IS TRUE "
                "AND policy_status='ALLOWED' FOR SHARE;",
                (receipt["tenant_id"], receipt["source_id"]),
            )
            source = cursor.fetchone()
            if source is None or connector_source_fingerprint(source[0], source[1]) != expected_fingerprint:
                conn.rollback()
                raise ReceiptSourceChanged("connector configuration or credentials changed before provider work")
    conn.commit()
    receipt["provider_started"] = True


def assert_fence(conn, receipt: dict, allow_pre_provider: bool = False) -> None:
    """Fence a canonical write, or an authorized no-provider finalization.

    Canonical data writes require provider_started. The explicit pre-provider
    option is reserved for a no-target ingestion job that completes without
    making a provider request.
    """
    state_predicate = (
        "state IN ('authorized','provider_started')"
        if allow_pre_provider else "state='provider_started'"
    )
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE public.keel_operation_receipts SET lease_expires_at=NOW() + (%s * INTERVAL '1 second'), "
            f"updated_at=NOW() WHERE tenant_id=%s::uuid AND receipt_id=%s::uuid AND {state_predicate} "
            "AND lease_owner=%s AND lease_generation=%s AND lease_expires_at > NOW() "
            "RETURNING actor_user_id, period_start, operation_type, target_kind, target_id;",
            (receipt.get("lease_seconds", 1800), receipt["tenant_id"], receipt["receipt_id"],
             receipt["worker_id"], receipt["lease_generation"]),
        )
        row = cursor.fetchone()
    if row is None:
        raise ReceiptLeaseLost("canonical write rejected by receipt lease fence")
    expected_fingerprint = receipt.get("source_execution_fingerprint")
    if row[2] == SCHEDULED_CONNECTOR_SYNC and expected_fingerprint:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT collector_config, connection_credentials_vault FROM public.data_sources "
                "WHERE tenant_id=%s::uuid AND source_id=%s::uuid AND is_active IS TRUE "
                "AND policy_status='ALLOWED' FOR SHARE;",
                (receipt["tenant_id"], row[4]),
            )
            source = cursor.fetchone()
        if source is None or connector_source_fingerprint(source[0], source[1]) != expected_fingerprint:
            raise ReceiptSourceChanged("connector configuration or credentials changed during synchronization")
    authorize_operation(conn, row[2], receipt["tenant_id"], row[3], str(row[4]), str(row[0]), row[1])


def finish(conn, receipt: dict, state: str, error_code: str | None = None) -> None:
    if state not in {"completed", "retryable", "reconciliation_required", "failed", "denied"}:
        raise ValueError("invalid terminal receipt transition")
    if state == "completed":
        authorize_operation(conn, receipt["operation_type"], receipt["tenant_id"], receipt["target_kind"],
                            receipt["target_id"], receipt["actor_user_id"], receipt["period_start"])
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE public.keel_operation_receipts SET state=%s, error_code=%s, "
            "provider_outcome=CASE WHEN provider_started_at IS NOT NULL AND %s='completed' THEN 'completed' "
            "WHEN provider_started_at IS NOT NULL THEN 'unknown' ELSE 'not_started' END, "
            "lease_owner=NULL, lease_expires_at=NULL, completed_at=CASE WHEN %s='completed' THEN NOW() ELSE NULL END, "
            "updated_at=NOW() WHERE tenant_id=%s::uuid AND receipt_id=%s::uuid "
            "AND lease_owner=%s AND lease_generation=%s AND state IN ('authorized','provider_started');",
            (state, error_code, state, state, receipt["tenant_id"], receipt["receipt_id"],
             receipt["worker_id"], receipt["lease_generation"]),
        )
        if cursor.rowcount != 1:
            conn.rollback()
            raise ReceiptLeaseLost("receipt completion was fenced")
    conn.commit()


def recover_expired(conn, tenant_id: str) -> dict[str, int]:
    """Expire pre-send claims for retry; never retry uncertain provider work."""
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE public.keel_operation_receipts SET state='retryable', lease_owner=NULL, "
            "lease_expires_at=NULL, updated_at=NOW() WHERE tenant_id=%s::uuid "
            "AND state IN ('claimed','authorized') AND lease_expires_at < NOW();",
            (tenant_id,),
        )
        retryable = cursor.rowcount
        cursor.execute(
            "UPDATE public.keel_operation_receipts SET state='reconciliation_required', "
            "provider_outcome='unknown', lease_owner=NULL, lease_expires_at=NULL, updated_at=NOW() "
            "WHERE tenant_id=%s::uuid AND state='provider_started' AND lease_expires_at < NOW();",
            (tenant_id,),
        )
        uncertain = cursor.rowcount
    conn.commit()
    return {"retryable": retryable, "reconciliation_required": uncertain}
