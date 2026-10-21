from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Literal, Optional
from uuid import UUID
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from src.ai import db
from src.ai.core.security import TenantContext, get_tenant_context
from src.ai.dashboard import competitors as dashboard_competitors
from src.ai.market_inputs import competitor_landscape
from src.ai.market_inputs import competitor_prices as manual_prices
from src.ai.core import usage
from src.market_scraper import data_access, enqueue, source_review
from src.market_scraper import discovery as market_scraper_discovery

router = APIRouter(tags=["competitors"])

# Owner/admin only - reviewing a discovered source's own Terms of Service
# and deciding whether this tenant's automated collector may scrape it is
# a real, accountable, company-wide decision (it's what
# data_sources.approved_by ends up recording), same authorization tier as
# settings.py's own company-wide endpoints - not something every "staff"
# team member should be able to do to every discovered source.
_SOURCE_REVIEW_ROLES = {"owner", "admin"}


def _require_role(conn, tenant_id: str, user_id: str, allowed_roles: set) -> str:
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT role_key FROM tenant_users WHERE tenant_id = %s AND user_id = %s AND removed_at IS NULL;",
            (tenant_id, user_id),
        )
        row = cursor.fetchone()
    if row is None or row[0] not in allowed_roles:
        raise HTTPException(status_code=403, detail="You do not have permission to perform this action.")
    return row[0]


@router.get("/competitors")
def list_competitors_endpoint(
    sort: Literal["name", "confidence"] = "name",
    ctx: TenantContext = Depends(get_tenant_context),
) -> dict:
    """
    The Competitors list page's backend contract - a single flat list a
    table/grid can render directly, instead of GET /dashboard/competitors'
    tier-grouped {"strategic": [...], "relevant": [...]} shape (kept
    as-is there; that endpoint's own contract is the dashboard's, not
    this page's). Reuses dashboard/competitors.py::get_competitor_directory()
    for the real query/scoring logic rather than duplicating it - this
    endpoint only reshapes its output (both groups concatenated, each row
    keeping its own "tier" field so the page can still show/filter by
    STRATEGIC vs RELEVANT). Alphabetical by name by default (the page's
    original, stable order); `sort=confidence` orders by confidence_score,
    best first (unscored rows last, then by name) - the same order as the
    tier-grouped directory.
    """
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        directory = dashboard_competitors.get_competitor_directory(conn, ctx.tenant_id)
        conn.commit()
        rows = directory["strategic"] + directory["relevant"]
        if sort == "confidence":
            competitors = sorted(rows, key=lambda row: (row.get("confidence_score") is None, -(row.get("confidence_score") or 0), row["name"]))
        else:
            competitors = sorted(rows, key=lambda row: row["name"])
        return {"competitors": competitors}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.post("/competitors/reclassify")
def reclassify_competitors_endpoint(ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """
    Re-scores every competitor this tenant already has against the current
    classification rules (category relevance + confidence score) and repairs
    old product-title names. Scores, categories and evidence are refreshed;
    tracking is only ever REMOVED (a competitor the system tracked that is in
    a different category) - never started, and an owner's explicit track /
    untrack choice is never overturned. Idempotent; see
    discovery.py::refresh_tenant_competitors().
    """
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        result = market_scraper_discovery.refresh_tenant_competitors(conn, ctx.tenant_id)
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# --- Discovered source review (the real "not enough data" fix) ----------
#
# Traced from a real tenant: discovery correctly found and classified 168
# real, in-scope, tracked competitors (03851fb), but every one of their
# data_sources landed BLOCKED or RESTRICTED, zero ALLOWED - so nothing was
# ever collected (competitor_prices/market_observations/reviews all
# empty). This isn't a bug in policy.py::evaluate_source(): a fully
# automated discovery run never supplies real Terms-of-Service evidence,
# so it correctly refuses to auto-approve ANY source - see policy_cli.py's
# own --terms-permit flag, the pre-existing CLI-only version of this same
# human decision. These two endpoints are that decision made reachable
# from the product itself, for the tenant's own owner/admin, instead of
# only a CLI an operator would have to run per tenant per source.
#
# Registered BEFORE GET /competitors/{competitor_id} below - FastAPI
# matches routes in declaration order, and "/competitors/sources" would
# otherwise be swallowed by that path-parameter route (competitor_id=
# "sources"), returning a fabricated-looking 404 instead of this list.

@router.get("/competitors/landscape")
def competitor_landscape_endpoint(ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """Market-wide and product-level competitors with their price position,
    and competitor coverage for every product (competitor_landscape.py)."""
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        result = competitor_landscape.build_landscape(conn, ctx.tenant_id)
        feature = usage.get_plan(conn, ctx.tenant_id)["features"].get(usage.TRACKED_COMPETITORS)
        result["plan_limit"] = feature["limit"] if feature else None
        return result
    finally:
        conn.close()


class CompetitorLevelRequest(BaseModel):
    competition_level: str = Field(pattern="^(MARKET|PRODUCT)$")
    product_ids: List[UUID] = Field(default_factory=list, max_length=500)


@router.patch("/competitors/{competitor_id}/level")
def set_competitor_level_endpoint(competitor_id: UUID, body: CompetitorLevelRequest, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """Says how this competitor competes (whole business or specific
    products) and links it to products."""
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT 1 FROM tenant_competitors WHERE tenant_id = %s AND global_competitor_id = %s;", (ctx.tenant_id, str(competitor_id)))
            if cursor.fetchone() is None:
                raise HTTPException(status_code=404, detail="Competitor not found")
        competitor_landscape.set_level(conn, ctx.tenant_id, str(competitor_id), body.competition_level)
        linked = competitor_landscape.link_products(conn, ctx.tenant_id, str(competitor_id), body.product_ids)
        conn.commit()
        return {"competitor_id": str(competitor_id), "competition_level": body.competition_level, "products_linked": linked}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.get("/competitors/sources")
def list_discovered_sources(
    status: Optional[str] = None, limit: int = 50, offset: int = 0,
    ctx: TenantContext = Depends(get_tenant_context),
) -> dict:
    """
    The review queue: this tenant's real discovered data_sources, with
    real counts per policy_status so an owner/admin can see at a glance
    how many are actually pending (RESTRICTED) vs. correctly excluded
    (BLOCKED) vs. already collecting (ALLOWED). status=RESTRICTED is the
    real "needs your review" filter the UI defaults to.
    """
    if status is not None and status not in {"ALLOWED", "RESTRICTED", "BLOCKED"}:
        raise HTTPException(status_code=422, detail="status must be one of ALLOWED, RESTRICTED, BLOCKED")
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        sources = data_access.list_tenant_sources(conn, ctx.tenant_id, policy_status=status, limit=limit, offset=offset)
        counts = data_access.count_tenant_sources_by_status(conn, ctx.tenant_id)
        conn.commit()
        return {"sources": sources, "counts": counts}
    except ValueError as err:
        conn.rollback()
        raise HTTPException(status_code=422, detail=str(err))
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


class ReviewSourceRequest(BaseModel):
    terms_permit: bool
    reviewer_reference: str


@router.post("/competitors/sources/{source_id}/review")
def review_discovered_source(
    source_id: str, body: ReviewSourceRequest, ctx: TenantContext = Depends(get_tenant_context),
) -> dict:
    """
    Records a real reviewer decision (source_review.py::review_source() -
    the same policy.py::evaluate_source() automated discovery already
    uses, given the one real human input it was always missing) and, only
    when that produces a genuinely ALLOWED source, enqueues real
    collection for it (market_scraper/enqueue.py::enqueue_collection() -
    the same function discovery_worker.py already uses for a source that
    was already ALLOWED at discovery time). A transient enqueue failure
    (e.g. Redis briefly unreachable) never rolls back the review decision
    itself - the approval is real and durable either way; collection can
    always be retried, a lost human decision could not be.
    """
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        _require_role(conn, ctx.tenant_id, ctx.user_id, _SOURCE_REVIEW_ROLES)
        result = source_review.review_source(
            conn, ctx.tenant_id, source_id, ctx.user_id,
            terms_permit=body.terms_permit, reviewer_reference=body.reviewer_reference,
        )
        conn.commit()
    except HTTPException:
        conn.rollback()
        raise
    except ValueError as err:
        conn.rollback()
        raise HTTPException(status_code=422, detail=str(err))
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    result["enqueued"] = False
    result["enqueue_error"] = None
    if result["status"] == "ALLOWED":
        try:
            enqueue.enqueue_collection(ctx.tenant_id, source_id, actor_user_id=ctx.user_id)
            result["enqueued"] = True
        except Exception as exc:  # noqa: BLE001 - a real infra/gate failure here must not look like a failed review
            result["enqueue_error"] = str(exc)
    return result


@router.get("/competitors/{competitor_id}")
def get_competitor_profile_endpoint(competitor_id: str, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """
    The Competitor Detail page's backend contract - one competitor's real
    fields (see dashboard/competitors.py::get_competitor_profile()'s own
    docstring). 404s for a competitor this tenant isn't tracking (never
    tracked, or a TIER_CANDIDATE this platform excluded) rather than
    fabricating an empty profile.
    """
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        result = dashboard_competitors.get_competitor_profile(conn, ctx.tenant_id, competitor_id)
        conn.commit()
        if result is None:
            raise HTTPException(status_code=404, detail="Competitor not found")
        return result
    except HTTPException:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


class AddCompetitorRequest(BaseModel):
    """The "Add Competitor" modal's two required fields (Marketplace
    Links/Social Media Handles aren't stored anywhere yet - see
    market_scraper/discovery.py::register_manual_competitor()'s own
    docstring for why this is a distinct entry point from the automated
    discovery paths, not a shortcut through them)."""
    name: str = Field(max_length=200)
    website_url: str = Field(max_length=2000)
    # MARKET: competes with the whole business; PRODUCT: on the listed products.
    competition_level: Optional[str] = Field(default=None, pattern="^(MARKET|PRODUCT)$")
    product_ids: List[UUID] = Field(default_factory=list, max_length=500)

    @field_validator("name")
    @classmethod
    def _name_present(cls, value):
        value = " ".join(value.split())
        if not value:
            raise ValueError("name is required")
        return value

    @field_validator("website_url")
    @classmethod
    def _website(cls, value):
        """Accepts what people type ("rival.jo", "www.rival.jo/shop") by
        assuming https://, and rejects anything that isn't a web address -
        the hostname is the competitor's identity for de-duplication."""
        value = value.strip()
        if value and "://" not in value:
            value = f"https://{value}"
        parts = urlsplit(value)
        host = parts.hostname or ""
        if parts.scheme not in ("http", "https") or "." not in host or " " in value or host.startswith(".") or host.endswith("."):
            raise ValueError("website_url must be a web address such as https://example.com")
        return value


@router.post("/competitors")
def add_competitor_endpoint(body: AddCompetitorRequest, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """
    The "Add Competitor" modal - registers a competitor the business
    owner names directly. See market_scraper/discovery.py::
    register_manual_competitor()'s own docstring for why this is a
    distinct, honestly-labeled entry point (discovery_method left NULL)
    rather than routed through the automated discovery functions, which
    require a real discovery_method value this action doesn't have.
    """
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        result = market_scraper_discovery.register_manual_competitor(conn, ctx.tenant_id, body.name, body.website_url)
        # Checked after registering: re-adding a competitor that is already
        # tracked must keep working at the limit; only a new one can exceed it.
        usage.ensure_capacity(conn, ctx.tenant_id, usage.TRACKED_COMPETITORS, 0)
        if body.product_ids:
            result["products_linked"] = competitor_landscape.link_products(conn, ctx.tenant_id, result["competitor_id"], body.product_ids)
        level = body.competition_level or ("PRODUCT" if body.product_ids else None)
        if level:
            competitor_landscape.set_level(conn, ctx.tenant_id, result["competitor_id"], level)
            result["competition_level"] = level
        conn.commit()
        return result
    except HTTPException:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


class RecordCompetitorPriceRequest(BaseModel):
    """One competitor price the owner saw themselves (store visit, phone,
    flyer, marketplace listing) for one of their own products."""
    product_id: str
    price: Decimal = Field(ge=0, le=Decimal("99999999"))
    currency: Optional[str] = None  # defaults to the product's own currency
    product_url: Optional[str] = Field(default=None, max_length=2000)
    observed_at: Optional[datetime] = None

    @field_validator("currency")
    @classmethod
    def _currency_code(cls, value):
        if value is None:
            return value
        value = value.strip().upper()
        if len(value) != 3 or not value.isalpha():
            raise ValueError("currency must be a 3-letter ISO code")
        return value

    @field_validator("observed_at")
    @classmethod
    def _not_in_future(cls, value):
        if value is not None:
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            if value > datetime.now(timezone.utc):
                raise ValueError("observed_at cannot be in the future")
        return value


@router.post("/competitors/{competitor_id}/prices")
def record_competitor_price_endpoint(
    competitor_id: str, body: RecordCompetitorPriceRequest, ctx: TenantContext = Depends(get_tenant_context),
) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        currency = body.currency
        if currency is None:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT currency FROM products WHERE tenant_id = %s AND product_id = %s AND deleted_at IS NULL;",
                    (ctx.tenant_id, body.product_id),
                )
                row = cursor.fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Product not found")
            currency = row[0]
        result = manual_prices.record_competitor_price(
            conn, ctx.tenant_id, competitor_id, body.product_id, body.price, currency, body.product_url, body.observed_at,
        )
        conn.commit()
        return result
    except manual_prices.NotFound as err:
        conn.rollback()
        raise HTTPException(status_code=404, detail=str(err))
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.get("/competitors/{competitor_id}/prices")
def list_competitor_prices_endpoint(competitor_id: str, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        return {"prices": manual_prices.list_competitor_prices(conn, ctx.tenant_id, competitor_id)}
    except manual_prices.NotFound as err:
        raise HTTPException(status_code=404, detail=str(err))
    finally:
        conn.close()
