"""
KEEL - Ingestion job/data-source bookkeeping.

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


def create_ingestion_job(conn, tenant_id: str, source_id: str, file_name: Optional[str] = None) -> str:
    # file_name is the uploaded file's original name, display metadata only
    # (Connect Data's import history, the dashboard activity feed).
    if file_name is not None:
        file_name = file_name.strip()[:255] or None
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO ingestion_jobs (tenant_id, source_id, job_status, started_at, file_name) "
            "VALUES (%s, %s, 'PROCESSING', NOW(), %s) RETURNING job_id;",
            (tenant_id, source_id, file_name),
        )
        return str(cursor.fetchone()[0])


RECENT_IMPORTS_LIMIT = 20


def list_recent_imports(conn, tenant_id: str, limit: int = RECENT_IMPORTS_LIMIT) -> list:
    """The tenant's file imports, newest first - the real history behind
    Connect Data's "Recent Data Activity" table. Only *_UPLOAD sources:
    scheduled connector/scraper jobs are not something the tenant uploaded."""
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT ij.job_id, COALESCE(ij.file_name, ds.source_name), ds.source_type, ij.job_status,
                   ij.rows_processed, ij.rows_partial, ij.rows_failed, ij.error_log, ij.created_at, ij.ended_at
            FROM ingestion_jobs ij
            JOIN data_sources ds ON ds.tenant_id = ij.tenant_id AND ds.source_id = ij.source_id
            WHERE ij.tenant_id = %s AND ds.source_type LIKE '%%\_UPLOAD'
            ORDER BY ij.created_at DESC
            LIMIT %s;
            """,
            (tenant_id, limit),
        )
        rows = cursor.fetchall()
    return [
        {
            "job_id": str(job_id),
            "file_name": file_name,
            "file_type": source_type.split("_", 1)[0].lower(),
            "status": status,
            "rows_processed": rows_processed or 0,
            "rows_partial": rows_partial or 0,
            "rows_failed": rows_failed or 0,
            "created_at": created_at.isoformat(),
            "ended_at": ended_at.isoformat() if ended_at else None,
        }
        for job_id, file_name, source_type, status, rows_processed, rows_partial, rows_failed, _error, created_at, ended_at in rows
    ]


def finalize_ingestion_job(conn, tenant_id: str, job_id: str, status: str, error: Optional[str] = None) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE ingestion_jobs SET job_status = %s, ended_at = NOW(), error_log = %s "
            "WHERE tenant_id = %s AND job_id = %s;",
            (status, error, tenant_id, job_id),
        )
