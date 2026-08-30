"""
CEOPRO AI - Ingestion job/data-source bookkeeping.

ingestion_jobs.source_id is a NOT NULL FK to data_sources - a caller must
have a registered source before a job can even be created. For an
interactive upload (as opposed to a scheduled connector sync,
data_sources.sync_frequency_minutes' actual use case), there's no setup
step where a tenant "registers" the fact that they upload files by hand -
so this module finds-or-creates a per-tenant, per-source-type data_sources
row on first use, the same find-or-create pattern
market_scraper/persistence.py::resolve_competitor_id() already uses for an
analogous "this might already exist, or might need to be created right
now" situation.
"""
from typing import Optional


def resolve_or_create_data_source(conn, tenant_id: str, source_type: str, source_name: str) -> str:
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT source_id FROM data_sources WHERE tenant_id = %s AND source_type = %s LIMIT 1;",
            (tenant_id, source_type),
        )
        row = cursor.fetchone()
        if row:
            return str(row[0])

        cursor.execute(
            "INSERT INTO data_sources (tenant_id, source_name, source_type) VALUES (%s, %s, %s) "
            "RETURNING source_id;",
            (tenant_id, source_name, source_type),
        )
        return str(cursor.fetchone()[0])


def create_ingestion_job(conn, tenant_id: str, source_id: str) -> str:
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO ingestion_jobs (tenant_id, source_id, job_status, started_at) "
            "VALUES (%s, %s, 'PROCESSING', NOW()) RETURNING job_id;",
            (tenant_id, source_id),
        )
        return str(cursor.fetchone()[0])


def finalize_ingestion_job(conn, tenant_id: str, job_id: str, status: str, error: Optional[str] = None) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE ingestion_jobs SET job_status = %s, ended_at = NOW(), error_log = %s "
            "WHERE tenant_id = %s AND job_id = %s;",
            (status, error, tenant_id, job_id),
        )
