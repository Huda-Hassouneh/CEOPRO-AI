"""HTTP owns connection lifetime, error rollback and delivery transaction ends.

Summary evidence is committed by the pipeline before the router's separate
commit. Each wrapper commit/rollback restores context in a new transaction;
close rolls back remaining work before pool return. FastAPI serialization is
outside this lifetime and cannot undo already committed evidence.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from src.ai import db
from src.ai.core.security import TenantContext, get_tenant_context
from src.ai.mpi import application
# Retain the existing internal import seam for callers and characterization.
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
        result = application.compute_summary(conn, ctx.tenant_id, subject_type, subject_id)
        # Ends the restored-context transaction, not the evidence transaction.
        conn.commit()
        return result
    except mpi_pipeline.data_access.InvalidSubjectType as exc:
        conn.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except mpi_pipeline.data_access.InvalidSubjectIdentifier as exc:
        conn.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except mpi_pipeline.data_access.SubjectNotFoundError:
        conn.rollback()
        raise HTTPException(status_code=404, detail="MPI subject not found.") from None
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.get('/history')
def mpi_history(subject_type:str,subject_id:Optional[str]=None,limit:int=Query(20,ge=1,le=100),offset:int=Query(0,ge=0),ctx:TenantContext=Depends(get_tenant_context)):
    """Read persisted evidence only: no scoring, refresh, provider calls or charges."""
    conn=db.app_role_connection(ctx.tenant_id,ctx.user_id)
    try:
        rows=application.get_history(conn,ctx.tenant_id,subject_type,subject_id,limit,offset)
        # Preserve read-transaction completion before response construction.
        conn.commit()
        return {'items':[{'evidence_id':str(r[0]),'generated_at':r[1].isoformat(),'result':r[2],'confidence_score':float(r[3]) if r[3] is not None else None,'explanation':r[4]} for r in rows[:limit]],'has_more':len(rows)>limit,'limit':limit,'offset':offset}
    except mpi_pipeline.data_access.InvalidSubjectType as exc:
        conn.rollback();raise HTTPException(422,str(exc)) from None
    except mpi_pipeline.data_access.InvalidSubjectIdentifier as exc:
        conn.rollback();raise HTTPException(422,str(exc)) from None
    except mpi_pipeline.data_access.SubjectNotFoundError:
        conn.rollback();raise HTTPException(404,'MPI subject not found.') from None
    except Exception:
        conn.rollback();raise
    finally:conn.close()
