"""Tenant-safe PostgreSQL operations owned by the Market Scraper Service."""

import json
import os
import uuid
from typing import Optional

from src.infrastructure.db_pool import PooledTenantConnection, TenantConnectionPool
from src.market_scraper.credential_vault import decrypt_credentials, encrypt_credentials, get_default_kms_backend

_POOL: Optional[TenantConnectionPool] = None


def _get_pool() -> TenantConnectionPool:
    """
    Lazy, module-level, one per process - mirrors src/ai/db.py::_get_pool()
    exactly (see src/infrastructure/db_pool.py's own docstring for the full
    RLS-under-pooling reasoning). A separate pool from the ai service's:
    this is a different, independently-deployed service/process
    (docker-compose.yml's market-scraper/market-analysis-worker/
    market-discovery-worker containers), each with its own pool for its
    own process lifetime - there is no cross-process pool to share even
    though both ultimately connect as the same ceopro_app role.
    """
    global _POOL
    if _POOL is None:
        db_url = os.getenv("SCRAPER_DATABASE_URL") or os.getenv("DATABASE_URL")
        if not db_url:
            raise RuntimeError("SCRAPER_DATABASE_URL or DATABASE_URL must be set")
        minconn = int(os.getenv("SCRAPER_DB_POOL_MIN_SIZE", "1"))
        maxconn = int(os.getenv("SCRAPER_DB_POOL_MAX_SIZE", "10"))
        _POOL = TenantConnectionPool(db_url, minconn=minconn, maxconn=maxconn)
    return _POOL


def get_tenant_connection(tenant_id: str, actor_user_id: Optional[str] = None) -> PooledTenantConnection:
    """
    Pooled tenant-scoped connection (production-hardening audit follow-up -
    see src/infrastructure/db_pool.py's own docstring for why a pooled
    connection needs SET LOCAL, not the session-scoped SET this used to
    issue, to stay RLS-safe across reuse). No caller needs to change: this
    still returns something that duck-types a plain psycopg2 connection.
    """
    actor_user_id = actor_user_id or os.getenv("SCRAPER_ACTOR_USER_ID")
    if not actor_user_id:
        raise RuntimeError("SCRAPER_ACTOR_USER_ID must identify an active tenant service principal")
    return _get_pool().get_tenant_connection(tenant_id, actor_user_id)


def load_source(conn, tenant_id: str, source_id: str) -> Optional[dict]:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT source_id, source_name, source_url, collection_method,
                   policy_status, collection_justification,
                   technical_restrictions, rate_limit_per_minute,
                   collector_key, render_javascript, collector_config,
                   approval_reference, approved_at, privacy_reviewed_at,
                   retention_days, contains_personal_data,
                   connection_credentials_vault
            FROM data_sources
            WHERE tenant_id = %s AND source_id = %s AND is_active = TRUE;
            """,
            (tenant_id, source_id),
        )
        row = cursor.fetchone()
    if not row:
        return None
    # connection_credentials_vault holds an encrypted envelope (see
    # credential_vault.py - PENDING_ACTIONS.md #42's real fix: field-level
    # envelope encryption, not plaintext JSON). Empty/unset stays {} (the
    # normal "no credentials configured yet" case, e.g. before Digi-Key/
    # Mouser are set up) - but a NON-empty value that isn't a recognized
    # envelope fails loud, never silently degrades to {}, since that would
    # otherwise surface as a confusing "not configured" error from whatever
    # collector needed the real credential instead of the actual problem
    # (wrong KMS backend, wrong master key, a pre-encryption legacy value).
    if not row[16]:
        credentials = {}
    else:
        credentials = decrypt_credentials(row[16], get_default_kms_backend())
    from src.ai.core.operation_receipts import connector_source_fingerprint
    return {
        "source_id": str(row[0]),
        "source_name": row[1],
        "source_url": row[2],
        "collection_method": row[3],
        "policy_status": row[4],
        "collection_justification": row[5],
        "technical_restrictions": row[6] or {},
        "rate_limit_per_minute": row[7],
        "collector_key": row[8],
        "render_javascript": row[9],
        "collector_config": row[10] or {},
        "approval_reference": row[11],
        "approved_at": row[12],
        "privacy_reviewed_at": row[13],
        "retention_days": row[14],
        "contains_personal_data": row[15],
        "connection_credentials": credentials,
        "source_execution_fingerprint": connector_source_fingerprint(row[10], row[16]),
    }


def set_source_credentials(
    conn, tenant_id: str, source_id: str, credentials: dict, kms=None,
) -> None:
    """
    Writes connection_credentials_vault - the real replacement for a raw
    SQL UPDATE (the only way this was previously done). The stored value
    is a real encrypted envelope (credential_vault.py), never the
    plaintext JSON this column used to hold directly - PENDING_ACTIONS.md
    #42's actual fix, not a documentation-only acknowledgment of the gap.
    Validates the source actually exists for this tenant first - never
    silently no-ops on a typo'd source_id - and requires credentials to
    be a real dict, never a bare string, so a malformed value fails loud
    here rather than becoming something unparseable later.

    kms: the KMS backend to encrypt with - defaults to
    credential_vault.get_default_kms_backend() (env-configured); pass one
    explicitly to use a specific backend/key for this one write without
    changing the process-wide default (mainly a test/tooling hook).
    """
    if not isinstance(credentials, dict):
        raise ValueError('credentials must be a JSON object, e.g. {"api_token": "..."}')
    envelope = encrypt_credentials(credentials, kms or get_default_kms_backend())
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE data_sources SET connection_credentials_vault = %s WHERE tenant_id = %s AND source_id = %s;",
            (envelope, tenant_id, source_id),
        )
        if cursor.rowcount != 1:
            raise ValueError(
                "source not found for this tenant - create it first with "
                "`python -m src.market_scraper.policy_cli register-source`"
            )
    conn.commit()


def load_scrape_targets(conn, tenant_id: str, source_id: str) -> list[dict]:
    """Allocate only active mappings tied to an explicitly ALLOWED web source."""
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT cpm.mapping_id, cpm.competitor_product_url,
                   cpm.competitor_product_sku, gc.competitor_name,
                   cpm.product_id, cpm.global_competitor_id,
                   COALESCE(p.product_name->>'en', p.product_name->>'ar', p.product_name::text)
            FROM competitor_product_mappings cpm
            JOIN tenant_competitors tc
              ON tc.tenant_id = cpm.tenant_id
             AND tc.global_competitor_id = cpm.global_competitor_id
            JOIN global_competitors gc
              ON gc.global_competitor_id = cpm.global_competitor_id
            JOIN products p
              ON p.tenant_id = cpm.tenant_id AND p.product_id = cpm.product_id
            JOIN data_sources ds
              ON ds.tenant_id = cpm.tenant_id AND ds.source_id = cpm.source_id
            WHERE cpm.tenant_id = %s
              AND cpm.source_id = %s
              AND cpm.is_active = TRUE
              AND (tc.is_tracked = TRUE OR tc.classification_reason LIKE 'excluded: competitor country%%')
              AND ds.is_active = TRUE
              AND ds.policy_status = 'ALLOWED'
              AND ds.collection_method IN ('OFFICIAL_API', 'RSS', 'STRUCTURED_DATA', 'WEB_SCRAPE')
              AND cpm.competitor_product_url IS NOT NULL
            ORDER BY cpm.created_at;
            """,
            (tenant_id, source_id),
        )
        rows = cursor.fetchall()
    return [
        {
            "mapping_id": str(row[0]),
            "product_url": row[1],
            "external_sku": row[2],
            "competitor_name": row[3],
            "product_id": str(row[4]),
            "global_competitor_id": str(row[5]),
            "product_name": row[6],
        }
        for row in rows
    ]


def list_tenant_sources(
    conn, tenant_id: str, policy_status: Optional[str] = None, limit: int = 50, offset: int = 0,
) -> list[dict]:
    """
    Real, paginated view of this tenant's discovered data_sources - what
    an owner/admin actually reviews to approve/reject a RESTRICTED source
    (see source_review.py::review_source()). LEFT JOINs to whichever
    competitor this source was discovered for so the reviewer sees real
    context ("this is X's website"), not a bare URL - a domain-level find
    with no product mapping yet still shows up, just without that count.
    """
    if limit < 1 or limit > 200:
        raise ValueError("limit must be between 1 and 200")
    if offset < 0:
        raise ValueError("offset must not be negative")
    query = """
        SELECT ds.source_id, ds.source_name, ds.source_url, ds.collection_method,
               ds.policy_status, ds.collection_justification, ds.technical_restrictions,
               ds.collector_key, ds.created_at, ds.approval_reference, ds.approved_at,
               gc.competitor_name, gc.global_competitor_id,
               COUNT(DISTINCT cpm.product_id) AS mapped_product_count
        FROM data_sources ds
        LEFT JOIN competitor_product_mappings cpm
          ON cpm.tenant_id = ds.tenant_id AND cpm.source_id = ds.source_id AND cpm.is_active = TRUE
        LEFT JOIN global_competitors gc ON gc.global_competitor_id = cpm.global_competitor_id
        WHERE ds.tenant_id = %s AND ds.is_active = TRUE
          -- Discovered websites only: the business's own uploads (sales files,
          -- documents, review imports) are data_sources too, but they are not
          -- competitor sources and have nothing to review here.
          AND ds.source_url IS NOT NULL
    """
    params = [tenant_id]
    if policy_status:
        query += " AND ds.policy_status = %s"
        params.append(policy_status)
    query += """
        GROUP BY ds.source_id, gc.competitor_name, gc.global_competitor_id
        ORDER BY ds.created_at DESC
        LIMIT %s OFFSET %s;
    """
    params.extend([limit, offset])
    with conn.cursor() as cursor:
        cursor.execute(query, params)
        rows = cursor.fetchall()
    return [
        {
            "source_id": str(row[0]), "source_name": row[1], "source_url": row[2],
            "collection_method": row[3], "policy_status": row[4],
            "collection_justification": row[5], "technical_restrictions": row[6] or {},
            "collector_key": row[7], "created_at": row[8].isoformat() if row[8] else None,
            "approval_reference": row[9], "approved_at": row[10].isoformat() if row[10] else None,
            "competitor_name": row[11], "global_competitor_id": str(row[12]) if row[12] else None,
            "mapped_product_count": row[13],
        }
        for row in rows
    ]


def count_tenant_sources_by_status(conn, tenant_id: str) -> dict:
    """Real counts per policy_status for this tenant's active sources - the
    summary an owner/admin sees before drilling into the RESTRICTED list
    (e.g. "192 blocked, 615 restricted, 0 allowed"), never estimated."""
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT policy_status, COUNT(*) FROM data_sources WHERE tenant_id = %s AND is_active = TRUE "
            "AND source_url IS NOT NULL GROUP BY policy_status;",
            (tenant_id,),
        )
        rows = cursor.fetchall()
    counts = {"ALLOWED": 0, "RESTRICTED": 0, "BLOCKED": 0}
    counts.update({status: count for status, count in rows})
    return counts


def create_ingestion_job(conn, tenant_id: str, source_id: str, receipt: dict | None = None) -> str:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO ingestion_jobs
                (tenant_id, source_id, job_status, started_at, heartbeat_at)
            SELECT %s, source_id, 'PROCESSING', NOW(), NOW()
            FROM data_sources
            WHERE tenant_id = %s AND source_id = %s
              AND is_active = TRUE AND policy_status = 'ALLOWED'
            RETURNING job_id;
            """,
            (tenant_id, tenant_id, source_id),
        )
        row = cursor.fetchone()
    if not row:
        raise ValueError("source is missing, inactive, or not ALLOWED")
    if receipt is not None:
        from src.ai.core import operation_receipts
        operation_receipts.attach_ingestion_job(conn, receipt, str(row[0]))
    conn.commit()
    return str(row[0])


def create_or_reuse_receipt_ingestion_job(conn, tenant_id: str, source_id: str, receipt: dict) -> str:
    """Reuse an unfinished job when a durable pre-provider receipt is retried."""
    if not receipt or str(receipt.get("tenant_id")) != str(tenant_id):
        raise ValueError("tenant-scoped operation receipt required")
    existing_job_id = receipt.get("ingestion_job_id")
    if existing_job_id:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT source_id,job_status FROM ingestion_jobs "
                "WHERE tenant_id=%s::uuid AND job_id=%s::uuid;",
                (tenant_id, existing_job_id),
            )
            row = cursor.fetchone()
        if row and str(row[0]) != str(source_id):
            raise ValueError("receipt ingestion job belongs to a different source")
        if row and row[1] == "PROCESSING":
            return str(existing_job_id)
    return create_ingestion_job(conn, tenant_id, source_id, receipt=receipt)


def load_ingestion_job_status(conn, tenant_id: str, job_id: str) -> Optional[str]:
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT job_status FROM ingestion_jobs WHERE tenant_id = %s AND job_id = %s;",
            (tenant_id, job_id),
        )
        row = cursor.fetchone()
    return row[0] if row else None


def heartbeat_ingestion_job(conn, tenant_id: str, job_id: str):
    with conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE ingestion_jobs SET heartbeat_at = NOW()
            WHERE tenant_id = %s AND job_id = %s AND job_status = 'PROCESSING';
            """,
            (tenant_id, job_id),
        )
    conn.commit()


def recover_stale_ingestion_jobs(conn, tenant_id: str, stale_minutes: int = 30) -> list[str]:
    """Fail abandoned jobs in this RLS-scoped tenant and return their IDs."""
    if not 1 <= stale_minutes <= 1440:
        raise ValueError("stale_minutes must be between 1 and 1440")
    with conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE ingestion_jobs
            SET job_status = 'FAILED', ended_at = NOW(),
                error_log = 'Recovered after stale worker heartbeat'
            WHERE tenant_id = %s AND job_status = 'PROCESSING'
              AND COALESCE(heartbeat_at, started_at) < NOW() - (%s * INTERVAL '1 minute')
            RETURNING job_id;
            """,
            (tenant_id, stale_minutes),
        )
        recovered = [str(row[0]) for row in cursor.fetchall()]
    conn.commit()
    return recovered


def fail_source_changed_ingestion_job(conn, tenant_id: str, receipt: dict) -> bool:
    """Mark this receipt-owned job failed after its source settings changed.

    This updates only the job status, never staged/canonical data, and requires
    the same live receipt generation so an old worker cannot overwrite a newer
    claim.
    """
    job_id = receipt.get("ingestion_job_id")
    if not job_id:
        return False
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM public.keel_operation_receipts WHERE tenant_id=%s::uuid "
            "AND receipt_id=%s::uuid AND lease_owner=%s AND lease_generation=%s "
            "AND state IN ('authorized','provider_started') AND lease_expires_at > NOW() FOR UPDATE;",
            (tenant_id, receipt["receipt_id"], receipt["worker_id"], receipt["lease_generation"]),
        )
        owns_live_lease = cursor.fetchone() is not None
        if not owns_live_lease:
            conn.rollback()
            return False
        cursor.execute(
            "UPDATE public.ingestion_jobs SET job_status='FAILED', "
            "error_log='Connector settings changed during synchronization; no further rows were committed.', "
            "ended_at=NOW(), heartbeat_at=NOW() WHERE tenant_id=%s::uuid AND job_id=%s::uuid "
            "AND job_status='PROCESSING';",
            (tenant_id, job_id),
        )
        updated = cursor.rowcount == 1
    conn.commit()
    return updated


def finish_ingestion_job(
    conn, tenant_id: str, job_id: str, status: str, processed: int,
    failed: int, error=None, quarantined: int = 0, receipt: dict | None = None,
    receipt_allow_pre_provider: bool = False,
):
    if receipt is not None:
        from src.ai.core import operation_receipts
        operation_receipts.assert_fence(
            conn, receipt, allow_pre_provider=receipt_allow_pre_provider,
        )
    with conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE ingestion_jobs
            SET job_status = %s, rows_processed = %s, rows_failed = %s,
                rows_quarantined = %s, error_log = %s, ended_at = NOW(), heartbeat_at = NOW()
            WHERE tenant_id = %s AND job_id = %s AND job_status = 'PROCESSING';
            """,
            (status, processed, failed, quarantined, error, tenant_id, job_id),
        )
        cursor.execute(
            """
            UPDATE data_sources ds SET last_synced_at = NOW()
            FROM ingestion_jobs job
            WHERE job.tenant_id = %s AND job.job_id = %s
              AND job.job_status = 'COMPLETED'
              AND ds.tenant_id = job.tenant_id AND ds.source_id = job.source_id;
            """,
            (tenant_id, job_id),
        )
    conn.commit()


def record_policy_decision(
    conn, tenant_id: str, source_id: str, decision, restrictions=None,
    rate_limit=30, collector_key=None, render_javascript=False,
    approval_reference=None, approved_by=None, retention_days=90,
    contains_personal_data=False,
):
    """Persist and audit an explicit policy and privacy decision."""
    if decision.status.value == "ALLOWED" and (not approval_reference or not approved_by):
        raise ValueError("ALLOWED sources require approval_reference and approved_by")
    with conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE data_sources
            SET source_url = %s, collection_method = %s, policy_status = %s,
                collection_justification = %s, technical_restrictions = %s::jsonb,
                rate_limit_per_minute = %s, collector_key = %s,
                render_javascript = %s, policy_checked_at = NOW(),
                approval_reference = %s, approved_by = %s,
                approved_at = CASE WHEN %s = 'ALLOWED' THEN NOW() ELSE NULL END,
                privacy_reviewed_at = NOW(), retention_days = %s,
                contains_personal_data = %s
            WHERE tenant_id = %s AND source_id = %s;
            """,
            (
                decision.collection_url,
                decision.method.value if decision.method else None,
                decision.status.value,
                decision.justification,
                json.dumps(restrictions or {}),
                rate_limit,
                collector_key,
                render_javascript,
                approval_reference,
                approved_by,
                decision.status.value,
                retention_days,
                contains_personal_data,
                tenant_id,
                source_id,
            ),
        )
        if cursor.rowcount != 1:
            raise ValueError("data source was not found for this tenant")
        cursor.execute(
            """
            INSERT INTO audit_logs
                (tenant_id, action_type, target_table, record_id, changed_data_json)
            VALUES (%s, 'COLLECTION_POLICY_DECIDED', 'data_sources', %s, %s::jsonb);
            """,
            (
                tenant_id,
                source_id,
                json.dumps({
                    "status": decision.status.value,
                    "method": decision.method.value if decision.method else None,
                    "justification": decision.justification,
                    "approval_reference": approval_reference,
                    "approved_by": approved_by,
                    "retention_days": retention_days,
                    "contains_personal_data": contains_personal_data,
                }),
            ),
        )
    conn.commit()


def list_tenant_competitors_by_proximity(
    conn, tenant_id: str, radius_km: Optional[float] = None, scope: Optional[str] = None,
    limit: Optional[int] = None,
) -> list:
    """
    Real proximity ranking, closest to farthest - the query-time half of
    "rank or filter them based on the user's preference/input": distance_km
    is already computed and persisted by competitor_classification.py::
    classify_competitor(), so this is a plain sort, not a recomputation.

    radius_km: when given, filters OUT anything farther than this (or with
    unknown distance) - the "narrow the search area" direction. Omit it
    (default) to rank every tracked competitor by distance without
    excluding any, which is also how "expand the radius" ends up working
    from a caller's point of view: a wider radius_km simply admits more of
    the same already-computed rows, no new discovery run required.

    A competitor with distance_km still NULL (neither side ever had
    coordinates set) sorts last, never first - unknown distance must never
    look closer than a real, known one.

    scope: optional filter to one competitor_scope value ('NICHE_ITEM',
    'PARTIAL_OVERLAP', 'BROAD_DOMAIN') - e.g. "show me only broad domain
    rivals near me". Omit for every scope.
    """
    conditions = ["tc.tenant_id = %s", "tc.is_tracked = TRUE"]
    params: list = [tenant_id]
    if radius_km is not None:
        conditions.append("tc.distance_km IS NOT NULL AND tc.distance_km <= %s")
        params.append(radius_km)
    if scope is not None:
        conditions.append("tc.competitor_scope = %s")
        params.append(scope)

    query = f"""
        SELECT gc.global_competitor_id, gc.competitor_name, gc.website_url, gc.city,
               tc.distance_km, tc.competitor_scope, tc.tier, tc.product_match_rate,
               tc.discovery_method
        FROM tenant_competitors tc
        JOIN global_competitors gc ON gc.global_competitor_id = tc.global_competitor_id
        WHERE {' AND '.join(conditions)}
        ORDER BY (tc.distance_km IS NULL), tc.distance_km ASC, gc.competitor_name ASC
    """
    if limit is not None:
        query += " LIMIT %s"
        params.append(limit)

    with conn.cursor() as cursor:
        cursor.execute(query, params)
        rows = cursor.fetchall()

    return [
        {
            "global_competitor_id": str(row[0]),
            "competitor_name": row[1],
            "website_url": row[2],
            "city": row[3],
            "distance_km": row[4],
            "competitor_scope": row[5],
            "tier": row[6],
            "product_match_rate": row[7],
            "discovery_method": row[8],
        }
        for row in rows
    ]


def register_self_service_data_source(
    conn, tenant_id: str, actor_user_id: str, source_name: str, collector_key: str,
    collector_config: dict, credentials: Optional[dict] = None, sync_frequency_minutes: Optional[int] = None,
) -> str:
    """
    The onboarding flow's real INSERT - the one missing piece between the
    fully-working DB/API connector SYNC logic (connector_sync.py,
    api_connector_sync.py) and a tenant actually being able to create one
    of these sources at all. Neither record_policy_decision() (an UPDATE
    that assumes a source_id already exists - the CLI's register-source
    command has always required one to be created some other way first)
    nor job_management.resolve_or_create_data_source() (a bare, policy-
    free INSERT correct for a manual file upload, which isn't "collection"
    in the scraping-policy sense at all) covers this.

    A tenant connecting THEIR OWN business system is not the compliance
    risk record_policy_decision()'s scraping-policy framework exists for
    (getting permission to collect a THIRD PARTY's data under someone
    else's terms of service) - so this auto-approves at registration time
    rather than requiring a human reviewer's sign-off on someone else's
    site, while still writing the exact same real, audited approval trail
    chk_allowed_source_has_approval requires of every ALLOWED row in this
    table: approval_reference names this as a self-service connection,
    approved_by is the real acting user (never a placeholder), approved_at/
    privacy_reviewed_at are both NOW().

    Deliberately narrow: registers the source only. Wiring credentials
    reuses set_source_credentials() (the same real field-level-encrypted
    envelope every other credentialed collector already uses) rather than
    a second, parallel encryption path.
    """
    source_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO data_sources
                (source_id, tenant_id, source_name, source_type, collector_key, collector_config,
                 policy_status, is_active, approval_reference, approved_by, approved_at,
                 privacy_reviewed_at, sync_frequency_minutes)
            VALUES (%s, %s, %s, 'OWN_SYSTEM_CONNECTOR', %s, %s::jsonb, 'ALLOWED', TRUE,
                    %s, %s, NOW(), NOW(), %s);
            """,
            (
                source_id, tenant_id, source_name, collector_key, json.dumps(collector_config),
                "Self-service connection to the tenant's own business system", actor_user_id,
                sync_frequency_minutes,
            ),
        )
    if credentials:
        set_source_credentials(conn, tenant_id, source_id, credentials)  # commits
    else:
        conn.commit()
    return source_id


def get_onboarding_status(conn, tenant_id: str) -> dict:
    """
    The backend half of the vision's guided first-time-user "How do you
    currently manage your business data?" step: reports whether this
    tenant has already connected any data source (a live connector, a
    past file upload) or recorded any sale by any means, so a caller
    (a future onboarding UI, or a chatbot answering "have I set
    everything up?") never has to re-derive this by hand.

    invoices is checked too, not just data_sources: a tenant who used
    Quick Sale, or whose upload never registered a formal data_sources
    row for some historical reason, should still report as genuinely
    connected rather than "not started" - the real signal onboarding
    cares about is "does this business have any real data in the system
    yet", not "does a specific bookkeeping row exist".
    """
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT collector_key, source_type FROM data_sources WHERE tenant_id = %s AND is_active = TRUE;",
            (tenant_id,),
        )
        sources = cursor.fetchall()
        cursor.execute("SELECT COUNT(*) FROM invoices WHERE tenant_id = %s;", (tenant_id,))
        invoice_count = cursor.fetchone()[0]

    connected_methods = sorted({(collector_key or source_type) for collector_key, source_type in sources})
    has_any_connection = bool(connected_methods) or invoice_count > 0

    return {
        "status": "connected" if has_any_connection else "not_started",
        "connected_methods": connected_methods,
        "invoice_count": invoice_count,
    }
