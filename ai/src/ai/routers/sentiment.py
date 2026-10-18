from typing import Optional

from fastapi import APIRouter, Depends

from src.ai import db
from src.ai.core.security import TenantContext, get_tenant_context
from src.ai.sentiment import pipeline as sentiment_pipeline

router = APIRouter(prefix="/sentiment", tags=["sentiment"])


@router.post("/analyze-pending")
def sentiment_analyze_pending(batch_size: int = 100, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        result = sentiment_pipeline.classify_and_store_reviews(conn, ctx.tenant_id, batch_size)
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.get("/summary")
def sentiment_summary(
    subject_type: str,
    subject_id: Optional[str] = None,
    country_context: Optional[str] = None,
    ctx: TenantContext = Depends(get_tenant_context),
) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        result = sentiment_pipeline.get_subject_sentiment_summary(
            conn, ctx.tenant_id, subject_type, subject_id, country_context
        )
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
