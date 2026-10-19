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
from typing import List, Literal, Optional
from uuid import UUID

import redis
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from src.ai import db
from src.ai.billing import credits
from src.ai.core.redis_client import get_redis_client
from src.ai.core.security import TenantContext, get_tenant_context
from src.ai.dashboard import product_market
from src.ai.market_inputs import competitor_comments, public_sources
from src.market_scraper import competitor_enrichment, enrichment_queue, price_coverage

router = APIRouter(tags=["competitors"])
logger = logging.getLogger("CEOPRO_AI_COMPETITOR_ENRICHMENT_API")


class EnrichCompetitorRequest(BaseModel):
    # Omit to retry everything collectable (competitor_enrichment.ENRICHABLE_FACETS).
    facets: Optional[List[str]] = None
    # "deep" = "load more": PRICES reads more pages, items and menu files (slower, so prefer background=true).
    depth: Literal["standard", "deep"] = "standard"


def _competitor_uuid(competitor_id: str) -> str:
    try:
        return str(UUID(competitor_id))
    except ValueError:
        raise HTTPException(status_code=422, detail="competitor_id must be a UUID.")


def _enrichment_redis() -> redis.Redis:
    return get_redis_client(socket_timeout=3, socket_connect_timeout=3)


def _queue_enrichment(tenant_id: str, competitor_id: Optional[str], facets, mode: str, *extra):
    """202 for a background job. A Redis outage is a 503 (retry shortly), never
    a silent drop; an identical job already queued is reported, not duplicated."""
    try:
        message_id = enrichment_queue.enqueue_enrichment(_enrichment_redis(), tenant_id, competitor_id, facets, mode, *extra)
    except redis.RedisError:
        logger.exception("could not enqueue enrichment for tenant=%s", tenant_id)
        raise HTTPException(status_code=503, detail="The retry queue is unavailable; try again shortly.")
    return JSONResponse(
        status_code=202,
        content={"queued": message_id is not None, "already_queued": message_id is None,
                 "competitor_id": competitor_id, "mode": mode},
    )


@router.post("/competitors/enrich-failed", dependencies=[credits.requires_budget(credits.DATA)])
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


@router.post("/competitors/{competitor_id}/enrich", dependencies=[credits.requires_budget(credits.DATA)])
def enrich_competitor_endpoint(
    competitor_id: str, body: Optional[EnrichCompetitorRequest] = None,
    background: bool = Query(default=False), ctx: TenantContext = Depends(get_tenant_context),
):
    """
    The per-competitor Retry button: re-runs the collectable facets (profile,
    social links, Google reviews, news, comments, and prices from the website
    and its menu PDFs / pictures; depth=deep loads more of the website) and returns each outcome plus the refreshed
    completeness. Additive - a retry only adds data or raises confidence. A
    provider/setup problem comes back as that facet's reason_code, not an HTTP
    error. background=true queues it for the enrichment worker instead (202); depth=deep is always queued.
    """
    competitor_id = _competitor_uuid(competitor_id)
    facets = body.facets if body and body.facets else None
    deep = bool(body and body.depth == "deep")
    unsupported = [f for f in (facets or []) if f not in competitor_enrichment.ENRICHABLE_FACETS]
    if unsupported:
        raise HTTPException(
            status_code=422,
            detail=f"Cannot retry {unsupported} yet; supported: {list(competitor_enrichment.ENRICHABLE_FACETS)}.",
        )
    if deep:
        background = True  # a deep read can take minutes (24 pages, 15 menu files, OCR): never hold the request open
    if background:
        return _queue_enrichment(ctx.tenant_id, competitor_id, facets, enrichment_queue.MODE_FORCE,
                                  *(("deep",) if deep else ()))
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        try:
            results = competitor_enrichment.enrich_competitor(
                conn, ctx.tenant_id, competitor_id, facets=facets, throttle=True, actor_user_id=ctx.user_id, **({"deep": True} if deep else {}),
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
    offset: int = Query(default=0, ge=0), missing_barcode: bool = Query(default=False),
    ctx: TenantContext = Depends(get_tenant_context),
) -> dict:
    """
    How many of the tenant's products have at least one competitor price, and
    for each that does not, why (price_coverage.py). `summary` covers every
    product; `products` lists the gaps, paged (include_covered=true adds the
    products that already have a price). A gap with action "review_source"
    is fixed by the owner/admin review at
    POST /competitors/sources/{source_id}/review for each id in `source_ids`. A gap
    with suggestion "add_barcode" has no barcode: entering one (PATCH /products/{id},
    or a barcode column on import) makes the open price databases exact.
    missing_barcode=true lists every product without a barcode instead (the worklist).
    """
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        result = price_coverage.get_price_coverage(conn, ctx.tenant_id, include_covered, limit, offset, missing_barcode)
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.post("/pricing/market-coverage/fill", dependencies=[credits.requires_budget(credits.DATA)])
def fill_market_price_gaps_endpoint(ctx: TenantContext = Depends(get_tenant_context)):
    """
    Looks up a market reference price for products that have none: open price
    databases, sellers' public product pages found by web search, and (when
    set up) a shopping search - cheapest source first, bounded per run
    (price_lookup/pipeline.py). Queued for the background worker (202); watch
    GET /pricing/market-coverage. Products already looked up recently are
    skipped, so repeating this does not re-spend.
    """
    return _queue_enrichment(ctx.tenant_id, None, None, enrichment_queue.MODE_PRICES)


@router.get("/pricing/market-prices/{product_id}")
def list_market_prices_endpoint(product_id: str, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """The market reference prices found for one product: seller, price, the
    listing's own star rating and review count when it shows them, and a link
    to the public page. `counted` is false for a price far from the product's
    own price (kept for inspection, not counted as coverage)."""
    product_id = _competitor_uuid(product_id)
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM products WHERE tenant_id = %s AND product_id = %s AND deleted_at IS NULL;",
                (ctx.tenant_id, product_id),
            )
            if cursor.fetchone() is None:
                raise HTTPException(status_code=404, detail="Product not found.")
            cursor.execute(
                """
                SELECT seller_name, product_title, source_url, price, currency, rating, review_count,
                       match_score, plausible, provider, observed_at
                FROM market_price_observations WHERE tenant_id = %s AND product_id = %s
                ORDER BY (plausible IS NOT FALSE) DESC, observed_at DESC, price LIMIT 50;
                """,
                (ctx.tenant_id, product_id),
            )
            rows = cursor.fetchall()
        conn.commit()
    except HTTPException:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {"product_id": product_id, "prices": [
        {
            "seller": seller, "listing_title": title, "url": public_sources.public_url(public_sources.category(provider), url),
            "price": float(price), "currency": currency, "rating": float(rating) if rating is not None else None,
            "review_count": review_count, "match_score": round(score, 2), "counted": plausible is not False,
            "source": public_sources.category(provider), "observed_at": observed_at.isoformat(),
        }
        for seller, title, url, price, currency, rating, review_count, score, plausible, provider, observed_at in rows
    ]}


@router.get("/competitors/{competitor_id}/reviews")
def competitor_reviews_endpoint(
    competitor_id: str, sort: str = Query(default=competitor_comments.SORT_HELPFUL, pattern="^(helpful|recent)$"),
    limit: int = Query(default=20, ge=1, le=100), offset: int = Query(default=0, ge=0),
    ctx: TenantContext = Depends(get_tenant_context),
) -> dict:
    """
    The real comments and reviews collected about one competitor: the text, star
    rating, how many people liked each (people_agreeing), replies under the comment
    they answer, and the sentiment read from the text. sort=helpful puts the most
    agreed-with first. Comments held back by the safety scan are counted in
    summary.held_back_for_safety, never silently dropped.
    """
    competitor_id = _competitor_uuid(competitor_id)
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        result = competitor_comments.list_competitor_comments(conn, ctx.tenant_id, competitor_id, sort, limit, offset)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    if result is None:
        raise HTTPException(status_code=404, detail="Competitor not found.")
    return {"competitor_id": competitor_id, **result}


@router.get("/competitor-data/overview")
def competitor_data_overview_endpoint(ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """
    One bulk read for the competitor list: for every tracked competitor its
    Google rating and review count, comments collected, people agreeing,
    sentiment (plain and agreement-weighted), social profiles and data
    completeness (what is missing, why, and whether Retry applies). Keyed by
    competitor_id - the list screens merge it onto their rows.
    """
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        details = product_market.competitor_details(conn, ctx.tenant_id)
        conn.commit()
        return {"competitors": details}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
