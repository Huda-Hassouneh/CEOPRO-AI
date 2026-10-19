"""Competitor discovery API: run discovery, follow a run, browse what was
found (with sources), and choose which competitors to track."""
import logging
import threading
from decimal import Decimal
from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from src.ai import db
from src.ai.billing import credits
from src.ai.market_inputs import public_sources
from src.ai.core import tenant_cache, usage
from src.ai.core.security import TenantContext, get_tenant_context
from src.ai.market_inputs import (
    competitor_analysis, competitor_intel, discovered_competitors, intel_review, market_news, market_structure, price_history, product_matches,
)
from src.infrastructure.request_language import get_request_language
from src.market_scraper.market_discovery import industries, pipeline

logger = logging.getLogger("APEX_MARKET_DISCOVERY")
router = APIRouter(prefix="/discovery", tags=["discovery"])


def _run_in_background(tenant_id: str, user_id: str, run_id: str, radius_km: Optional[float]) -> None:
    conn = db.dedicated_tenant_connection(tenant_id, user_id)
    try:
        pipeline.execute_run(conn, tenant_id, run_id, radius_km)
    except Exception:  # noqa: BLE001 - recorded on the run row
        pass
    finally:
        conn.close()
        tenant_cache.bump(tenant_id)  # new competitors show on the next screen


@router.get("/industries")
def list_industries() -> dict:
    return {"industries": industries.choices()}


@router.get("/status")
def discovery_status(ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """What discovery will search for, which sources are connected, and the last run."""
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        profile = pipeline.load_profile(conn, ctx.tenant_id)
        query = pipeline.build_query(ctx.tenant_id, profile)
        industry, how = industries.resolve(profile.get("industry_key"), profile.get("business_type"), profile.get("product_names") or [])
        return {
            "industry": {"key": industry.key, "label": {"en": industry.label_en, "ar": industry.label_ar}, "decided_by": how},
            "location": {"city": profile.get("city"), "country_code": profile.get("country_code"),
                         "latitude": profile.get("latitude"), "longitude": profile.get("longitude"),
                         "has_location": query.has_location or bool(profile.get("city"))},
            "radius_km": query.radius_km,
            "keywords": query.keywords,
            # Kinds of source, never provider names (market_inputs/public_sources.py).
            "providers": public_sources.provider_status(pipeline.provider_status()),
            "last_run": public_sources.public_run(pipeline.get_run(conn, ctx.tenant_id)),
        }
    finally:
        conn.close()


class DiscoverRequest(BaseModel):
    radius_km: Optional[float] = Field(default=None, ge=0.5, le=30)


@router.post("/runs", status_code=202)
def start_discovery(body: DiscoverRequest, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    credits.ensure_available(ctx.tenant_id, credits.DATA)  # 402 when this period's Data Credits are used
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        run_id = pipeline.start_run(conn, ctx.tenant_id, ctx.user_id, body.radius_km)
        conn.commit()
    except pipeline.DiscoveryBusy as busy:
        conn.rollback()
        return {"run_id": busy.run_id, "status": "running", "already_running": True}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    threading.Thread(target=_run_in_background, args=(ctx.tenant_id, ctx.user_id, run_id, body.radius_km),
                     name=f"discovery-{run_id}", daemon=True).start()
    return {"run_id": run_id, "status": "queued", "already_running": False}


@router.get("/runs/{run_id}")
def get_discovery_run(run_id: str, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        try:
            run = pipeline.get_run(conn, ctx.tenant_id, run_id)
        except Exception:  # noqa: BLE001 - malformed id
            conn.rollback()
            run = None
        if run is None:
            raise HTTPException(status_code=404, detail="Discovery run not found")
        return public_sources.public_run(run)
    finally:
        conn.close()


@router.get("/news")
def list_market_news(limit: int = Query(default=30, ge=1, le=100), competitor_id: Optional[str] = None,
                     ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """Recent industry and competitor news found by discovery, newest first,
    each linking to the article."""
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        try:
            return {"articles": market_news.latest(conn, ctx.tenant_id, limit, competitor_id)}
        except Exception as exc:  # noqa: BLE001 - malformed competitor id
            conn.rollback()
            if "invalid input syntax" in str(exc):
                return {"articles": []}
            raise
    finally:
        conn.close()


@router.get("/competitors")
def list_discovered(
    status: Literal["all", "tracked", "suggested"] = "all",
    sort: Literal["relevance", "confidence", "distance", "rating", "reviews", "name", "recent"] = "relevance",
    q: Optional[str] = Query(default=None, max_length=100),
    origin: Optional[Literal["manual", "map", "web"]] = None,
    min_confidence: Optional[float] = Query(default=None, ge=0, le=1),
    limit: int = Query(default=200, ge=1, le=500), offset: int = Query(default=0, ge=0),
    relationship: Optional[Literal["DIRECT", "INDIRECT", "RELATED", "UNVERIFIED", "with_prices"]] = None,
    ctx: TenantContext = Depends(get_tenant_context),
) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        result = discovered_competitors.list_competitors(conn, ctx.tenant_id, status, sort, q, origin, min_confidence, limit,
                                                         offset, relationship)
        feature = usage.get_plan(conn, ctx.tenant_id)["features"].get(usage.TRACKED_COMPETITORS)
        result["plan_limit"] = feature["limit"] if feature else None
        return result
    finally:
        conn.close()


@router.get("/competitors/{competitor_id}")
def get_discovered(competitor_id: str, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        try:
            result = discovered_competitors.get_competitor(conn, ctx.tenant_id, competitor_id)
        except Exception:  # noqa: BLE001 - malformed id
            conn.rollback()
            result = None
        if result is None:
            raise HTTPException(status_code=404, detail="Competitor not found")
        result["intel"] = competitor_intel.get_intel(conn, ctx.tenant_id, competitor_id)
        return result
    finally:
        conn.close()


@router.post("/competitors/{competitor_id}/refresh")
def refresh_competitor_intel(competitor_id: str, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """Reads the competitor's website again now (also the retry after a
    failed read). Same rules as during discovery: robots.txt, public sites
    only, a few pages."""
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        try:
            outcome = competitor_intel.refresh_competitor(conn, ctx.tenant_id, competitor_id)
        except (LookupError, ValueError):
            conn.rollback()
            raise HTTPException(status_code=404, detail="Competitor not found")
        except Exception as exc:  # noqa: BLE001 - malformed id
            conn.rollback()
            if "invalid input syntax" in str(exc):
                raise HTTPException(status_code=404, detail="Competitor not found")
            raise
        conn.commit()
        tenant_cache.bump(ctx.tenant_id)
        return {**outcome, "intel": competitor_intel.get_intel(conn, ctx.tenant_id, competitor_id)}
    finally:
        conn.close()


class ReviewIntelRequest(BaseModel):
    intel_id: UUID
    verdict: Literal["CONFIRMED", "CORRECTED", "REJECTED", "CLEARED"]
    corrected_price: Optional[Decimal] = Field(default=None, ge=0)
    currency: Optional[str] = Field(default=None, min_length=3, max_length=3)
    note: Optional[str] = Field(default=None, max_length=500)


@router.post("/competitors/{competitor_id}/intel/review")
def review_competitor_intel(competitor_id: UUID, body: ReviewIntelRequest, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """
    The owner's check of one price read from the competitor's website or menu:
    CONFIRMED (verified, confidence 1.0), CORRECTED (their price replaces the
    one read; send corrected_price), REJECTED (dropped), or CLEARED (withdraws
    an earlier decision). Decisions are remembered across re-reads of the site,
    per item AND price read: a changed price on the site is a new, unreviewed
    fact. Prices are re-matched to your products afterwards. Owner/admin only.
    """
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        if not intel_review.can_review(conn, ctx.tenant_id, ctx.user_id):
            raise HTTPException(status_code=403, detail="You do not have permission to perform this action.")
        competitor_id, intel_id = str(competitor_id), str(body.intel_id)
        try:
            if body.verdict == "CLEARED":
                result = {"intel_id": intel_id, "verdict": "CLEARED",
                          "had_decision": intel_review.clear_review(conn, ctx.tenant_id, competitor_id, intel_id)}
            else:
                result = intel_review.review_fact(conn, ctx.tenant_id, competitor_id, intel_id, body.verdict, ctx.user_id,
                                                  body.corrected_price, body.currency, body.note)
        except LookupError:
            conn.rollback()
            raise HTTPException(status_code=404, detail="Price not found for this competitor.")
        except intel_review.ReviewError as err:
            conn.rollback()
            raise HTTPException(status_code=422, detail=str(err))
        from src.market_scraper.market_discovery import pipeline

        pipeline._match_prices(conn, ctx.tenant_id, [competitor_id])  # noqa: SLF001 - a corrected or rejected price changes the matches
        conn.commit()
        tenant_cache.bump(ctx.tenant_id)
        return {**result, "intel": competitor_intel.get_intel(conn, ctx.tenant_id, competitor_id)}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _known_competitor(conn, tenant_id: str, competitor_id: str) -> str:
    competitor_id = str(competitor_id)
    try:
        competitor_intel.competitor_website(conn, tenant_id, competitor_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="Competitor not found")
    return competitor_id


@router.get("/competitors/{competitor_id}/price-changes")
def competitor_price_changes(competitor_id: UUID, days: int = Query(default=90, ge=1, le=730), include_unreliable: bool = False,
                             limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0),
                             ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """
    Price changes on this competitor's own menu, site and posts, newest first: item, old and new price, % change, when,
    where it was read. Changes between two weak reads (picture / caption / AI reads) are included only with
    include_unreliable=true, unless the owner confirmed them.
    """
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        competitor_id = _known_competitor(conn, ctx.tenant_id, competitor_id)
        changes = price_history.list_changes(conn, ctx.tenant_id, competitor_id, days, include_unreliable, limit, offset)
        conn.commit()
        return {"competitor_id": competitor_id, "days": days, "changes": changes}
    finally:
        conn.close()


@router.get("/price-changes")
def recent_price_changes(days: int = Query(default=30, ge=1, le=365), include_unreliable: bool = False,
                         limit: int = Query(default=30, ge=1, le=200), offset: int = Query(default=0, ge=0),
                         ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """Recent price changes across every competitor (newest first); same rules as the per-competitor list."""
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        changes = price_history.list_changes(conn, ctx.tenant_id, None, days, include_unreliable, limit, offset)
        conn.commit()
        return {"days": days, "changes": changes}
    finally:
        conn.close()


@router.get("/competitors/{competitor_id}/price-history")
def competitor_item_price_history(competitor_id: UUID, item_key: str = Query(min_length=1, max_length=200),
                                  currency: Optional[str] = Query(default=None, min_length=3, max_length=3),
                                  ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """The recorded prices of one item (item_key from price-changes), oldest first - a trend line."""
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        competitor_id = _known_competitor(conn, ctx.tenant_id, competitor_id)
        series = price_history.item_series(conn, ctx.tenant_id, competitor_id, item_key, currency.upper() if currency else None)
        conn.commit()
        return {"competitor_id": competitor_id, "item_key": item_key, "series": series}
    finally:
        conn.close()


@router.get("/competitors/{competitor_id}/matches")
def competitor_product_matches(competitor_id: UUID, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """Which of this competitor's items are matched to which of your products, the priced items you can choose from,
    and the matches you rejected."""
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        competitor_id = _known_competitor(conn, ctx.tenant_id, competitor_id)
        result = product_matches.list_matches(conn, ctx.tenant_id, competitor_id)
        conn.commit()
        return {"competitor_id": competitor_id, **result}
    finally:
        conn.close()


class RejectMatchRequest(BaseModel):
    product_id: UUID


class ChooseMatchRequest(BaseModel):
    product_id: UUID
    intel_id: UUID


def _match_change(competitor_id, ctx, action):
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        if not product_matches.can_manage(conn, ctx.tenant_id, ctx.user_id):
            raise HTTPException(status_code=403, detail="You do not have permission to perform this action.")
        competitor_id = _known_competitor(conn, ctx.tenant_id, competitor_id)
        try:
            result = action(conn, competitor_id)
        except LookupError:
            conn.rollback()
            raise HTTPException(status_code=404, detail="Product, price or match not found for this competitor.")
        except product_matches.MatchError as err:
            conn.rollback()
            raise HTTPException(status_code=422, detail=str(err))
        conn.commit()
        tenant_cache.bump(ctx.tenant_id)
        return {**result, **{k: v for k, v in product_matches.list_matches(conn, ctx.tenant_id, competitor_id).items()}}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.post("/competitors/{competitor_id}/matches/reject")
def reject_competitor_match(competitor_id: UUID, body: RejectMatchRequest, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """"This item is not that product": it is never matched to it again, the price comparison stops using it and the
    next best item (if any) is matched instead. Owner/admin only."""
    return _match_change(competitor_id, ctx, lambda conn, cid: product_matches.reject_match(conn, ctx.tenant_id, cid, str(body.product_id), ctx.user_id))


@router.post("/competitors/{competitor_id}/matches")
def choose_competitor_match(competitor_id: UUID, body: ChooseMatchRequest, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """You choose the competitor item (intel_id from the matches list) that is this product. Same currency required; a
    price read from a post must be confirmed first. Owner/admin only."""
    return _match_change(competitor_id, ctx, lambda conn, cid: product_matches.choose_match(
        conn, ctx.tenant_id, cid, str(body.product_id), str(body.intel_id), ctx.user_id))


@router.delete("/competitors/{competitor_id}/matches/{product_id}")
def clear_competitor_match(competitor_id: UUID, product_id: UUID, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """Back to automatic matching for this product (removes your decisions about it). Owner/admin only."""
    return _match_change(competitor_id, ctx, lambda conn, cid: product_matches.clear_match(conn, ctx.tenant_id, cid, str(product_id)))


def _analysis_error(err: "competitor_analysis.AnalysisUnavailable") -> HTTPException:
    if err.reason == "not_configured":
        return HTTPException(status_code=503, detail="Analysis isn't set up on this server yet.",
                             headers={"X-Assistant-Reason": "not_configured"})
    if err.reason == "busy":
        return HTTPException(status_code=503, detail="The analyst is busy right now. Try again in a minute.",
                             headers={"Retry-After": "30"})
    return HTTPException(status_code=502, detail="The analysis couldn't be written this time. Try again.")


@router.post("/competitors/{competitor_id}/analysis")
def analyse_competitor(competitor_id: str, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """AI analysis of one competitor from the facts collected about it;
    every point cites them. Uses the plan's AI token allowance."""
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        try:
            return competitor_analysis.analyse_competitor(conn, ctx.tenant_id, competitor_id, get_request_language())
        except LookupError:
            conn.rollback()
            raise HTTPException(status_code=404, detail="Competitor not found")
        except competitor_analysis.AnalysisUnavailable as err:
            raise _analysis_error(err) from err
        except Exception as exc:
            conn.rollback()
            if "invalid input syntax" in str(exc):
                raise HTTPException(status_code=404, detail="Competitor not found")
            raise
    finally:
        conn.close()


@router.get("/market/structure")
def market_structure_view(ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """Counts and price ranges over the stored competitors (no AI, no guess)."""
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        return market_structure.build(conn, ctx.tenant_id)
    finally:
        conn.close()


@router.get("/market/analysis")
def market_analysis(ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        return {"analysis": competitor_analysis.latest_market_summary(conn, ctx.tenant_id)}
    finally:
        conn.close()


@router.post("/market/analysis")
def refresh_market_analysis(ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """AI summary of market trends from stored news and competitor facts,
    every point citing them. Uses the plan's AI token allowance."""
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        try:
            return {"analysis": competitor_analysis.analyse_market(conn, ctx.tenant_id, get_request_language())}
        except competitor_analysis.AnalysisUnavailable as err:
            raise _analysis_error(err) from err
    finally:
        conn.close()


def _set_tracked(competitor_id: str, tracked: bool, ctx: TenantContext) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        try:
            changed = discovered_competitors.set_tracked(conn, ctx.tenant_id, competitor_id, tracked)
        except Exception:  # noqa: BLE001 - malformed id
            conn.rollback()
            changed = False
        if not changed:
            raise HTTPException(status_code=404, detail="Competitor not found")
        if tracked:
            usage.ensure_capacity(conn, ctx.tenant_id, usage.TRACKED_COMPETITORS, 0)
        conn.commit()
        return {"competitor_id": competitor_id, "is_tracked": tracked}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.post("/competitors/{competitor_id}/track")
def track_competitor(competitor_id: str, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    return _set_tracked(competitor_id, True, ctx)


@router.delete("/competitors/{competitor_id}/track")
def untrack_competitor(competitor_id: str, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    return _set_tracked(competitor_id, False, ctx)
