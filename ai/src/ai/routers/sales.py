import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.ai import db
from src.ai.core.security import TenantContext, get_tenant_context
from src.ai.sales import quick_sale

logger = logging.getLogger("CEOPRO_AI_SALES_API")

router = APIRouter(prefix="/sales", tags=["sales"])


class QuickSaleRequest(BaseModel):
    """The dashboard's "Quick Sale" quick action - one manual sale entry.
    unit_price is optional: defaults to the product's own current_price
    when omitted (see sales/quick_sale.py's own docstring)."""
    product_id: str
    # Fractional quantities are real sales (2.5 kg, 1.5 hours, 12.75 m).
    quantity: float = Field(gt=0, le=10_000_000)
    unit_price: Optional[float] = Field(default=None, ge=0, le=99_999_999)


@router.post("/quick-sale")
def quick_sale_endpoint(body: QuickSaleRequest, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """
    The "Quick Sale" quick action - records one manual sale immediately
    (one invoice + one invoice_item). See sales/quick_sale.py's own
    docstring for why this writes to invoices/invoice_items specifically
    (the platform's real manual-sales record, previously unreachable from
    any endpoint) rather than the separate `transactions` table uploads/
    POS syncs use.
    """
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        result = quick_sale.record_quick_sale(
            conn, ctx.tenant_id, ctx.user_id, body.product_id, body.quantity, body.unit_price,
        )
        conn.commit()
        _refresh_product_forecast(ctx, body.product_id)
        return result
    except quick_sale.ProductNotFoundError as err:
        conn.rollback()
        raise HTTPException(status_code=404, detail=str(err))
    except quick_sale.InsufficientStockError as err:
        conn.rollback()
        raise HTTPException(status_code=409, detail=str(err))
    except HTTPException:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _refresh_product_forecast(ctx: TenantContext, product_id) -> None:
    """A new sale changes this product's demand history: re-forecast it in the
    background (skipped when a refresh is already running; the next visit to
    Demand Prediction picks it up, since its forecast is older than the sale)."""
    try:
        from src.ai.forecasting import refresh as forecast_refresh

        if forecast_refresh.auto_refresh_enabled():
            forecast_refresh.start_refresh(ctx.tenant_id, ctx.user_id, [str(product_id)])
    except Exception:
        logger.exception("Could not start the forecast refresh after a sale (tenant=%s)", ctx.tenant_id)
