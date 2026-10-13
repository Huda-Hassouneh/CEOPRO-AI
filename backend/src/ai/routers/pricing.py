from fastapi import HTTPException, APIRouter, Depends

from src.ai import db
from src.ai.core.security import TenantContext, get_tenant_context
from src.ai.pricing import pipeline as pricing_pipeline

router = APIRouter(prefix="/pricing", tags=["pricing"])


@router.post("/recommend")
def pricing_recommend(product_id: str, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        result = pricing_pipeline.run_price_recommendation(conn, ctx.tenant_id, product_id)
        conn.commit()
        return result
    except pricing_pipeline.ProductNotFoundError:
        conn.rollback()
        raise HTTPException(status_code=404, detail="Product not found")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
