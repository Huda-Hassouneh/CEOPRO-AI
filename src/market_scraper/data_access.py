"""Tenant-safe PostgreSQL operations owned by the Market Scraper Service."""

import json
import os
from typing import Optional

import psycopg2


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
    # connection_credentials_vault is a plain TEXT column (no secrets-manager
    # integration exists in this repo); it holds a JSON object of API
    # credentials for collectors that need them (e.g. {"api_key": "..."}).
    try:
        credentials = json.loads(row[16]) if row[16] else {}
    except (TypeError, ValueError):
        credentials = {}
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
