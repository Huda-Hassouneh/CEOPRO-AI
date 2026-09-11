"""Tenant-safe PostgreSQL operations owned by the Market Scraper Service."""

import json
import os
from typing import Optional

import psycopg2

from src.market_scraper.credential_vault import decrypt_credentials, encrypt_credentials, get_default_kms_backend


def get_tenant_connection(tenant_id: str):
    db_url = os.getenv("SCRAPER_DATABASE_URL") or os.getenv("DATABASE_URL")
    actor_user_id = os.getenv("SCRAPER_ACTOR_USER_ID")
    if not db_url:
        raise RuntimeError("SCRAPER_DATABASE_URL or DATABASE_URL must be set")
    if not actor_user_id:
        raise RuntimeError("SCRAPER_ACTOR_USER_ID must identify an active tenant service principal")
    conn = psycopg2.connect(db_url)
    try:
        with conn.cursor() as cursor:
            cursor.execute("SET app.current_tenant_id = %s;", (str(tenant_id),))
            cursor.execute("SET app.current_user_id = %s;", (actor_user_id,))
        conn.commit()
        return conn
    except Exception:
        conn.close()
        raise


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
              AND tc.is_tracked = TRUE
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


def create_ingestion_job(conn, tenant_id: str, source_id: str) -> str:
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
    conn.commit()
    return str(row[0])


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


def finish_ingestion_job(
    conn, tenant_id: str, job_id: str, status: str, processed: int,
    failed: int, error=None, quarantined: int = 0,
):
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
