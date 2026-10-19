from typing import Optional

from fastapi import APIRouter, Depends

from src.ai import db
from src.ai.core.security import TenantContext, get_tenant_context
from src.ai.mpi import pipeline as mpi_pipeline

router = APIRouter(prefix="/mpi", tags=["mpi"])


@router.get("/summary")
def mpi_summary(
    subject_type: str,
    subject_id: Optional[str] = None,
    ctx: TenantContext = Depends(get_tenant_context),
) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        result = mpi_pipeline.get_subject_mpi(conn, ctx.tenant_id, subject_type, subject_id)
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
