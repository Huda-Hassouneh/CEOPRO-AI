from typing import Literal, Optional
from uuid import UUID

import logging

from fastapi import BackgroundTasks, HTTPException, APIRouter, Depends, Query
from pydantic import BaseModel, Field

from src.ai import db
from src.ai.core import usage
from src.ai.core.entitlements import requires
from src.ai.core.security import TenantContext, get_tenant_context
from src.ai.pricing import comparisons as price_comparisons
from src.ai.pricing import pipeline as pricing_pipeline
from src.market_scraper.price_comparison import adjudicate as comparison_adjudicate
from src.market_scraper.market_discovery import offerings as comparison_offerings
from src.market_scraper.price_comparison import engine as comparison_engine

router = APIRouter(prefix="/pricing", tags=["pricing"])
logger = logging.getLogger("CEOPRO_AI_PRICING_ROUTER")


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


@router.post("/recommend-all")
def pricing_recommend_all(ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """A decision for every active product - none is left without one for lack of market data."""
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        result = pricing_pipeline.run_price_recommendations_for_all(conn, ctx.tenant_id)
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _uuid_list(raw: str) -> list:
    try:
        ids = [str(UUID(part.strip())) for part in raw.split(",") if part.strip()]
    except ValueError:
        raise HTTPException(status_code=422, detail="product_ids must be a comma-separated list of UUIDs.")
    if not ids:
        raise HTTPException(status_code=422, detail="product_ids is empty.")
    if len(ids) > price_comparisons.MAX_PRODUCTS_PER_REQUEST:
        raise HTTPException(status_code=422, detail=f"At most {price_comparisons.MAX_PRODUCTS_PER_REQUEST} products per request.")
    return ids


@router.get("/comparisons")
def pricing_comparisons_summary(
    product_ids: str = Query(..., description="Comma-separated product ids (at most 100)."),
    ctx: TenantContext = Depends(get_tenant_context),
) -> dict:
    """
    Per product: how many competitors sit in each comparison tier (EXACT / EQUIVALENT / SIMILAR /
    ADDED_VALUE) and the headline - your price against the middle of the best tier available. Products
    that are not the caller's are absent. For the per-item detail use GET /pricing/comparisons/{product_id}.
    """
    ids = _uuid_list(product_ids)
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        ladders = price_comparisons.get_ladders(conn, ctx.tenant_id, ids)
        conn.commit()
        return {"products": {pid: price_comparisons.summarize(ladder) for pid, ladder in ladders.items()}}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.get("/comparisons/{product_id}")
def pricing_comparison_ladder(product_id: UUID, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """
    The comparison ladder for one product: competitors' items in four tiers, each with the competitor's
    own price, the comparable price (scaled to your quantity when it differs: a 1-hour class against a
    30-minute class is compared at twice the listed price), how far you are from it, and why the item was
    placed in that tier. ADDED_VALUE items carry the premium you charge over the competitor's base item.
    """
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        ladders = price_comparisons.get_ladders(conn, ctx.tenant_id, [str(product_id)])
        conn.commit()
        ladder = ladders.get(str(product_id))
        if ladder is None:
            raise HTTPException(status_code=404, detail="Product not found")
        return ladder
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _ai_comparison_pass(tenant_id: str, user_id: str) -> None:
    """Background: asks the AI model about the pairs the rules left unsettled, then stores its answers. Own
    connection (the request's is closed by now); never raises - a failure leaves the pairs unsettled."""
    from src.market_scraper.market_discovery.relevance import ai_hints_enabled

    if not ai_hints_enabled():
        return
    conn = None
    try:
        conn = db.dedicated_tenant_connection(tenant_id, user_id)
        result = comparison_engine.refresh_for_tenant(conn, tenant_id, judge=comparison_adjudicate.model_judge)
        conn.commit()
        logger.info("price comparison AI pass done tenant=%s rows=%s unsettled_left=%s", tenant_id, result["rows"], result["unsettled"])
    except Exception:  # noqa: BLE001
        logger.exception("price comparison AI pass failed tenant=%s", tenant_id)
        if conn is not None:
            conn.rollback()
    finally:
        if conn is not None:
            conn.close()


@router.post("/comparisons/refresh", dependencies=[requires(usage.COMPETITOR_MANAGEMENT)])
def pricing_comparisons_refresh(background: BackgroundTasks, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """
    Recomputes the ladder for every tracked competitor from the items already stored (no crawl, no external
    request) and answers at once. Earlier AI verdicts and owner decisions are reused. Pairs the rules cannot place
    (`unsettled`) are then checked by the AI model in the background when one is configured (`ai_pending` says
    how many); call this again, or reload, a little later to see the answers.
    """
    from src.market_scraper.market_discovery.relevance import ai_hints_enabled

    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        result = comparison_engine.refresh_for_tenant(conn, ctx.tenant_id)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    pending = result["unsettled"] if ai_hints_enabled() else 0
    if pending:
        background.add_task(_ai_comparison_pass, ctx.tenant_id, ctx.user_id)
    return {**result, "ai_pending": pending}


class ComparisonOverride(BaseModel):
    competitor_id: UUID
    item_name: str = Field(min_length=1, max_length=200)
    # ADDITION: ours adds something to their item. VARIANT: only a different variant. NOT_COMPARABLE: never compare
    # these two. null: remove the decision and let the system decide again.
    verdict: Optional[Literal["ADDITION", "VARIANT", "NOT_COMPARABLE"]] = None


@router.put("/comparisons/{product_id}/override", dependencies=[requires(usage.COMPETITOR_MANAGEMENT)])
def pricing_comparison_override(product_id: UUID, body: ComparisonOverride, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """
    The owner's correction of one comparison: "this is an extra", "this is only a variant", "these are not
    comparable" (or null to clear it). Owner/admin only. The decision is kept by item name, so it survives every
    re-read of the competitor's site; the competitor's rows are recomputed at once and the product's new ladder is
    returned.
    """
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT role_key FROM tenant_users WHERE tenant_id = %s AND user_id = %s AND removed_at IS NULL;",
                           (ctx.tenant_id, ctx.user_id))
            row = cursor.fetchone()
            if row is None or row[0] not in ("owner", "admin"):
                raise HTTPException(status_code=403, detail="You do not have permission to perform this action.")
            cursor.execute("SELECT 1 FROM products WHERE tenant_id = %s AND product_id = %s AND deleted_at IS NULL;",
                           (ctx.tenant_id, str(product_id)))
            found_product = cursor.fetchone()
            cursor.execute("SELECT 1 FROM tenant_competitors WHERE tenant_id = %s AND global_competitor_id = %s;",
                           (ctx.tenant_id, str(body.competitor_id)))
            found_competitor = cursor.fetchone()
            if not found_product or not found_competitor:
                raise HTTPException(status_code=404, detail="Product or competitor not found")
            key = comparison_engine.name_key(body.item_name)
            if body.verdict is None:
                cursor.execute(
                    "DELETE FROM product_price_comparison_overrides WHERE tenant_id = %s AND product_id = %s "
                    "AND global_competitor_id = %s AND name_key = %s;",
                    (ctx.tenant_id, str(product_id), str(body.competitor_id), key))
            else:
                cursor.execute(
                    """
                    INSERT INTO product_price_comparison_overrides
                        (tenant_id, product_id, global_competitor_id, name_key, item_name, verdict, decided_by)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (tenant_id, product_id, global_competitor_id, name_key)
                    DO UPDATE SET verdict = EXCLUDED.verdict, item_name = EXCLUDED.item_name,
                                  decided_by = EXCLUDED.decided_by, decided_at = CURRENT_TIMESTAMP;
                    """,
                    (ctx.tenant_id, str(product_id), str(body.competitor_id), key, body.item_name, body.verdict, ctx.user_id))
        products = comparison_offerings.company_products(conn, ctx.tenant_id)
        comparison_engine.refresh_for_competitor(conn, ctx.tenant_id, str(body.competitor_id), products)
        ladder = price_comparisons.get_ladders(conn, ctx.tenant_id, [str(product_id)]).get(str(product_id))
        conn.commit()
        return ladder
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
