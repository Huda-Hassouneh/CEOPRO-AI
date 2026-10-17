"""
Competitor data completeness + retry: what we know about each competitor,
why a field is empty, and the Retry buttons (single, background, and "retry
all failed"). Logic lives in market_scraper/competitor_enrichment.py; the
background jobs are consumed by market_scraper/enrichment_worker.py.

Price collection from a competitor's own website is approved through the
existing owner/admin review (POST /competitors/sources/{source_id}/review in
routers/competitors.py); a PRICES gap that needs it carries
`action: "review_source"` and the source ids to review.
"""
import logging
from typing import List, Optional
from uuid import UUID

import redis
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from src.ai import db
from src.ai.core.redis_client import get_redis_client
from src.ai.core.security import TenantContext, get_tenant_context
from src.market_scraper import competitor_enrichment, enrichment_queue, price_coverage

router = APIRouter(tags=["competitors"])
logger = logging.getLogger("CEOPRO_AI_COMPETITOR_ENRICHMENT_API")


class EnrichCompetitorRequest(BaseModel):
    # Omit to retry everything collectable (competitor_enrichment.ENRICHABLE_FACETS).
    facets: Optional[List[str]] = None


def _competitor_uuid(competitor_id: str) -> str:
    try:
        return str(UUID(competitor_id))
    except ValueError:
        raise HTTPException(status_code=422, detail="competitor_id must be a UUID.")


def _enrichment_redis() -> redis.Redis:
    return get_redis_client(socket_timeout=3, socket_connect_timeout=3)


def _queue_enrichment(tenant_id: str, competitor_id: Optional[str], facets, mode: str):
    """202 for a background job. A Redis outage is a 503 (retry shortly), never
    a silent drop; an identical job already queued is reported, not duplicated."""
    try:
        message_id = enrichment_queue.enqueue_enrichment(_enrichment_redis(), tenant_id, competitor_id, facets, mode)
    except redis.RedisError:
        logger.exception("could not enqueue enrichment for tenant=%s", tenant_id)
        raise HTTPException(status_code=503, detail="The retry queue is unavailable; try again shortly.")
    return JSONResponse(
        status_code=202,
        content={"queued": message_id is not None, "already_queued": message_id is None,
                 "competitor_id": competitor_id, "mode": mode},
    )


@router.post("/competitors/enrich-failed")
def enrich_failed_competitors_endpoint(ctx: TenantContext = Depends(get_tenant_context)):
    """
    "Retry all failed": queues one background job that re-runs every
    competitor facet of this tenant that failed, is partial, is pending, or is
    blocked only on a missing/rejected key. 202 immediately; identical jobs are
    deduplicated (competitor_enrichment.enrich_tenant_competitors, mode="force").
    """
    return _queue_enrichment(ctx.tenant_id, None, None, enrichment_queue.MODE_FORCE)


@router.get("/competitors/{competitor_id}/data-status")
def competitor_data_status_endpoint(competitor_id: str, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """Per-facet data completeness for one competitor - what was collected, and
    for each gap the reason and whether a retry is possible. The same object
    GET /competitors returns as `data_completeness`; `queued` says a background
    retry is pending."""
    competitor_id = _competitor_uuid(competitor_id)
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        status = competitor_enrichment.load_data_completeness(conn, ctx.tenant_id, competitor_id)
    finally:
        conn.close()
    if competitor_id not in status:
        raise HTTPException(status_code=404, detail="Competitor not found.")
    try:
        queued = enrichment_queue.is_queued(_enrichment_redis(), ctx.tenant_id, competitor_id)
    except redis.RedisError:
        queued = None  # unknown - the queue being down must not hide the data status
    return {"competitor_id": competitor_id, "queued": queued, **status[competitor_id]}


@router.post("/competitors/{competitor_id}/enrich")
def enrich_competitor_endpoint(
    competitor_id: str, body: Optional[EnrichCompetitorRequest] = None,
    background: bool = Query(default=False), ctx: TenantContext = Depends(get_tenant_context),
):
    """
    The per-competitor Retry button: re-runs the collectable facets (profile,
    social links, Google reviews) and returns each outcome plus the refreshed
    completeness. Additive - a retry only adds data or raises confidence. A
    provider/setup problem comes back as that facet's reason_code, not an HTTP
    error. background=true queues it for the enrichment worker instead (202).
    """
    competitor_id = _competitor_uuid(competitor_id)
    facets = body.facets if body and body.facets else None
    unsupported = [f for f in (facets or []) if f not in competitor_enrichment.ENRICHABLE_FACETS]
    if unsupported:
        raise HTTPException(
            status_code=422,
            detail=f"Cannot retry {unsupported} yet; supported: {list(competitor_enrichment.ENRICHABLE_FACETS)}.",
        )
    if background:
        return _queue_enrichment(ctx.tenant_id, competitor_id, facets, enrichment_queue.MODE_FORCE)
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        try:
            results = competitor_enrichment.enrich_competitor(
                conn, ctx.tenant_id, competitor_id, facets=facets, throttle=True, actor_user_id=ctx.user_id,
            )
        except ValueError:
            conn.rollback()
            raise HTTPException(status_code=404, detail="Competitor not found.")
        if results and all(r.get("status") == "THROTTLED" for r in results.values()):
            wait = max(r["retry_after_seconds"] for r in results.values())
            raise HTTPException(status_code=429, detail="Retried too recently.", headers={"Retry-After": str(wait)})
        completeness = competitor_enrichment.load_data_completeness(conn, ctx.tenant_id, competitor_id)
        conn.commit()
        return {"competitor_id": competitor_id, "results": results, "data_completeness": completeness.get(competitor_id)}
    except HTTPException:
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.get("/pricing/market-coverage")
def market_price_coverage_endpoint(
    include_covered: bool = Query(default=False), limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0), ctx: TenantContext = Depends(get_tenant_context),
) -> dict:
    """
    How many of the tenant's products have at least one competitor price, and
    for each that does not, why (price_coverage.py). `summary` covers every
    product; `products` lists the gaps, paged (include_covered=true adds the
    products that already have a price). A gap with action "review_source"
    is fixed by the owner/admin review at
    POST /competitors/sources/{source_id}/review for each id in `source_ids`.
    """
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        result = price_coverage.get_price_coverage(conn, ctx.tenant_id, include_covered, limit, offset)
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
