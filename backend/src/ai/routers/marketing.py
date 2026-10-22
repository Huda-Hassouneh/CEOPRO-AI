"""
KEEL - Automated Marketing System endpoints.

Product understanding is composed entirely from data this platform
already has - no new AI model was introduced for it:
- product_id input: reads the tenant's own products row (products.py's
  own get_product(), reused directly rather than re-querying).
- text input: used as-is.
- url input: src/ai/marketing/url_extractor.py (extruct/lxml, no new
  scraping infrastructure).

Market positioning (BUDGET/MID_RANGE/PREMIUM) is derived from this
tenant's real matched-competitor pricing data via src/ai/marketing/
positioning.py, reusing dashboard/competitor_pricing.py - never fabricated,
and only available (never guessed) when a real product_id with matched
competitor prices exists.

Ad copy/caption generation is one call into src/ai/marketing/
content_generator.py, which itself reuses rag/llm_client.py's existing
Groq/local/paid LLM backend selection - no new model or provider.

AI image generation (POST .../generate-image) is real, and genuinely
optional infrastructure - src/ai/marketing/image_generation.py dispatches
to a provider behind MARKETING_IMAGE_PROVIDER; see that module's own
docstring for exactly which providers, why, and their tradeoffs. Video
generation is investigated, not implemented - src/ai/marketing/
video_generation.py documents why and what would be needed later; GET
/marketing/options surfaces both as honest `capabilities.image_generation`/
`capabilities.video_generation` states.

Every endpoint here is synchronous (matches this service's other long-
running endpoint, POST /extraction/upload) rather than resurrecting the
dead campaign_image_requested Redis event contract - see this feature's own
plan for why: that scaffold was never wired to anything, and this service
has no background worker to defer onto even for the real generation step
image generation now is.
"""
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from urllib.parse import urlparse
from uuid import UUID

import psycopg2

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator

from src.ai import db
from src.ai.billing import credits
from src.ai.core.security import TenantContext, get_tenant_context
from src.ai.marketing import occasions
from src.ai.marketing import (
    background_removal, content_generator, creative_direction, data_access, designed_poster, image_generation,
    image_jobs, image_service, image_storage, positioning, url_extractor, video_generation,
)
from src.ai.core import storage_ledger, usage
from src.ai.rag import llm_client
from src.ai.routers.products import get_product
from src.infrastructure.request_language import get_request_language

logger = logging.getLogger("CEOPRO_AI_MARKETING")
# Tokens reserved per campaign before the model is asked (prompt ~1,500 +
# up to 2,200 written); settled to the real count afterwards.
MARKETING_TOKEN_RESERVATION = int(os.getenv("MARKETING_TOKEN_RESERVATION", "4000"))
router = APIRouter(prefix="/marketing", tags=["marketing"])

_MAX_TEXT_LENGTH = 5000
_MAX_IMAGE_BYTES = int(os.getenv("MAX_MARKETING_IMAGE_BYTES", str(8 * 1024 * 1024)))  # 8MB
_IMAGE_MAGIC_BYTES = {
    ".jpg": b"\xff\xd8\xff", ".jpeg": b"\xff\xd8\xff", ".png": b"\x89PNG\r\n\x1a\n",
}
_IMAGE_CONTENT_TYPES = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp",
}
_STORAGE_RECOVERY_GRACE = timedelta(hours=24)
_STORAGE_RECOVERY_BATCH = 100


def _track_image_before_put(ctx: TenantContext, kind: str, on_recorded=None):
    """Commit the tenant-scoped quota record on its own app-role connection."""
    def track(bucket: str, object_key: str, size_bytes: int) -> None:
        ledger_conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
        try:
            storage_ledger.record(ledger_conn, ctx.tenant_id, bucket, object_key, size_bytes, kind)
            ledger_conn.commit()
            if on_recorded is not None:
                on_recorded()
        except Exception:
            ledger_conn.rollback()
            raise
        finally:
            ledger_conn.close()

    return track


def _reconcile_stale_marketing_uploads(conn, client, tenant_id: str) -> int:
    """Remove only old, unreferenced marketing objects; retain uncertain rows.

    Runs lazily on marketing upload paths. The 24-hour grace avoids racing a
    slow in-flight request; active campaign pointers and storage failures keep
    their ledger rows. A later retry can safely repeat cleanup.
    """
    cutoff = datetime.now(timezone.utc) - _STORAGE_RECOVERY_GRACE

    def is_referenced(bucket: str, object_key: str) -> bool:
        if bucket not in image_storage.ALL_BUCKETS:
            return True
        parts = object_key.split("/", 2)
        if object_key.startswith(f"{tenant_id}/") and len(parts) == 3 and parts[1]:
            keys = data_access.stored_image_keys(conn, tenant_id, parts[1])
            return keys is not None and object_key in keys.values()
        return True

    try:
        return storage_ledger.recover_stale(
            conn,
            tenant_id,
            "marketing_",
            cutoff,
            lambda bucket, key: image_storage.object_exists(client, bucket, key),
            is_referenced=is_referenced,
            remove_object=lambda bucket, key: image_storage.remove_image(client, bucket, key),
            limit=_STORAGE_RECOVERY_BATCH,
        )
    except Exception:
        conn.rollback()
        logger.exception("Could not inspect stale marketing storage rows (tenant=%s)", tenant_id)
        return 0


def _compensate_image_upload(conn, tenant_id: str, campaign_id: str, bucket: str, object_key: str,
                             size_bytes: int, kind: str, client) -> None:
    """Remove an unreferenced upload or retain its bytes in the quota ledger."""
    try:
        conn.rollback()
        try:
            keys = data_access.stored_image_keys(conn, tenant_id, campaign_id)
            referenced = keys is not None and object_key in keys.values()
        except Exception:
            # A commit error can be ambiguous. Keep the object accounted for
            # unless the database proves that no campaign references it.
            referenced = None

        if referenced is not False:
            storage_ledger.record(conn, tenant_id, bucket, object_key, size_bytes, kind)
            removed = False
        else:
            removed = storage_ledger.compensate_upload(
                conn, tenant_id, bucket, object_key, size_bytes, kind,
                lambda: image_storage.remove_image(client, bucket, object_key),
            )
        conn.commit()
        if not removed:
            logger.error("Kept storage accounting for an object that could not be removed (tenant=%s key=%s)",
                         tenant_id, object_key)
    except Exception:
        logger.exception("Could not reconcile a failed image upload (tenant=%s key=%s)", tenant_id, object_key)
        try:
            conn.rollback()
        except Exception:
            logger.exception("Could not roll back image cleanup transaction (tenant=%s)", tenant_id)


class CampaignCreateRequest(BaseModel):
    """Exactly one of product_id/text/url must be provided - validated in
    the endpoint (needs all three fields together, not expressible as a
    single-field validator). style/tone/focus are the blueprint's
    "Optional creative instructions" - all optional, free text.

    creative_theme: one of creative_direction.THEMES, or omitted entirely
    to let this platform recommend one (creative_direction.recommend_theme(),
    a deterministic rule over this tenant's own real data - see that
    module's own docstring). "CUSTOM" requires a non-empty
    custom_creative_prompt (validated below); custom_creative_prompt is
    also accepted alongside a named theme, as extra instructions layered
    on top of it."""
    product_id: Optional[str] = None
    text: Optional[str] = Field(default=None, max_length=_MAX_TEXT_LENGTH)
    url: Optional[str] = Field(default=None, max_length=2000)
    style: Optional[str] = Field(default=None, max_length=50)
    tone: Optional[str] = Field(default=None, max_length=50)
    focus: Optional[str] = Field(default=None, max_length=50)
    strategy_type: str = Field(default="SALES_DRIVEN")
    variants_per_platform: int = Field(default=2, ge=1, le=3)
    # Only these platforms' copy (the Studio asks for one post); all when omitted.
    platforms: Optional[List[str]] = Field(default=None, min_length=1, max_length=4)
    creative_theme: Optional[str] = None
    custom_creative_prompt: Optional[str] = Field(default=None, max_length=2000)
    # The Studio's id for one "Generate" press: the same key again returns
    # the campaign already made instead of writing (and charging) a second.
    request_key: Optional[str] = Field(default=None, min_length=8, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    # Also make the campaign's image in the same request (the Studio does),
    # in this format (image_generation.IMAGE_FORMATS; square when omitted).
    generate_image: bool = False
    image_format: Optional[str] = None

    @field_validator("image_format")
    @classmethod
    def _valid_image_format(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and value not in image_generation.IMAGE_FORMATS:
            raise ValueError(f"image_format must be one of {list(image_generation.IMAGE_FORMATS)}")
        return value

    @field_validator("strategy_type")
    @classmethod
    def _valid_strategy(cls, value: str) -> str:
        if value not in content_generator.STRATEGIES:
            raise ValueError(f"strategy_type must be one of {sorted(content_generator.STRATEGIES)}")
        return value

    @field_validator("platforms")
    @classmethod
    def _valid_platforms(cls, value: Optional[List[str]]) -> Optional[List[str]]:
        if value is not None and any(p not in content_generator.PLATFORMS for p in value):
            raise ValueError(f"platforms must be among {list(content_generator.PLATFORMS)}")
        return value

    @field_validator("creative_theme")
    @classmethod
    def _valid_theme(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and value not in creative_direction.THEMES:
            raise ValueError(f"creative_theme must be one of {sorted(creative_direction.THEMES)}")
        return value


def _localized(value) -> Optional[str]:
    if not value:
        return None
    if isinstance(value, str):
        return value
    return value.get("en") or value.get("ar") or next(iter(value.values()), None)


def _product_understanding_text(product: dict) -> str:
    lines = [f"Product name: {_localized(product['product_name'])}"]
    brand = _localized(product.get("brand"))
    category = _localized(product.get("category"))
    description = _localized(product.get("description"))
    if brand:
        lines.append(f"Brand: {brand}")
    if category:
        lines.append(f"Category: {category}")
    if description:
        lines.append(f"Description: {description}")
    lines.append(f"Price: {product['current_price']} {product['currency']}")
    return "\n".join(lines)


_BRIEF_MAX_LENGTH = 120
_BRIEF_LABEL = re.compile(r"^\s*product name:\s*", re.IGNORECASE)


def _campaign_brief_summary(product_understanding: str, product_name: Optional[str] = None) -> str:
    """The campaign's title in the Studio and its history: what the campaign
    is about, in the customer's words - the product's own name (in the
    language they work in when the product has one), never the internal
    "Product name:" label the model's prompt uses."""
    if product_name:
        title = product_name
    else:
        first_line = next((line for line in (product_understanding or "").splitlines() if line.strip()), "")
        title = _BRIEF_LABEL.sub("", first_line).strip()
    title = title or "-"
    if len(title) > _BRIEF_MAX_LENGTH:
        title = title[:_BRIEF_MAX_LENGTH - 1].rstrip() + "…"
    return title


def _name_in_language(value, language: str) -> Optional[str]:
    if isinstance(value, dict) and (value.get(language) or "").strip():
        return value[language].strip()
    return _localized(value)


@router.post("/campaigns")
def create_campaign_endpoint(body: CampaignCreateRequest, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    provided = [name for name, value in (("product_id", body.product_id), ("text", body.text), ("url", body.url)) if value]
    if len(provided) != 1:
        raise HTTPException(status_code=422, detail="Provide exactly one of product_id, text, or url.")
    if body.creative_theme == "CUSTOM" and not (body.custom_creative_prompt or "").strip():
        raise HTTPException(status_code=422, detail="creative_theme 'CUSTOM' requires a non-empty custom_creative_prompt.")

    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    reservation, settled = None, False
    try:
        if body.request_key:
            existing = data_access.find_by_request_key(conn, ctx.tenant_id, body.request_key)
            if existing:  # a repeated press or a retried request
                result = data_access.get_campaign(conn, ctx.tenant_id, existing)
                conn.commit()
                return {**result, "duplicate_request": True}
        category = product_name = None
        if body.product_id:
            input_source = "PRODUCT"
            product = get_product(conn, ctx.tenant_id, body.product_id)
            if product is None:
                raise HTTPException(status_code=404, detail="Product not found")
            product_understanding = _product_understanding_text(product)
            product_name = _name_in_language(product["product_name"], get_request_language())
            category = _localized(product.get("category"))
        elif body.text:
            input_source = "TEXT"
            product_understanding = body.text
        else:
            input_source = "URL"
            try:
                extracted = url_extractor.extract_product_info_from_url(body.url)
            except url_extractor.URLExtractionError as err:
                raise HTTPException(status_code=422, detail=str(err))
            product_understanding = extracted.as_text()
            product_name = (extracted.name or "").strip() or urlparse(body.url).netloc or None

        positioning_label = positioning.derive_positioning_label(conn, ctx.tenant_id, body.product_id)

        if body.creative_theme:
            theme, theme_source = body.creative_theme, "USER_SELECTED"
        else:
            theme = creative_direction.recommend_theme(conn, ctx.tenant_id, category, positioning_label)
            theme_source = "RECOMMENDED"

        # Campaign writing uses the plan's AI token allowance, like the
        # assistant: an estimate is reserved up front (refused when nothing is
        # left), settled to the real count afterwards, given back if no tokens
        # were used.
        left = usage.remaining(conn, ctx.tenant_id, usage.RAG_ASSISTANT)
        estimate = MARKETING_TOKEN_RESERVATION if left is None else max(1, min(MARKETING_TOKEN_RESERVATION, left))
        reservation = usage.reserve(conn, ctx.tenant_id, usage.RAG_ASSISTANT, estimate)
        conn.commit()
        token_usage = {}

        try:
            campaign_id = data_access.create_campaign(
                conn, ctx.tenant_id, ctx.user_id,
                product_id=body.product_id, input_source=input_source,
                campaign_brief=_campaign_brief_summary(product_understanding, product_name),
                style=body.style, tone=body.tone, focus=body.focus, strategy_type=body.strategy_type,
                source_text=body.text, source_url=body.url,
                creative_theme=theme, theme_source=theme_source, custom_creative_prompt=body.custom_creative_prompt,
                request_key=body.request_key,
            )
            conn.commit()
        except psycopg2.errors.UniqueViolation:
            # The same press arrived twice at once: the other request is making it.
            conn.rollback()
            usage.release(conn, reservation)
            conn.commit()
            settled = True
            existing = data_access.find_by_request_key(conn, ctx.tenant_id, body.request_key)
            result = data_access.get_campaign(conn, ctx.tenant_id, existing) if existing else None
            if result is None:
                raise HTTPException(status_code=409, detail="This campaign is already being created.")
            return {**result, "duplicate_request": True}

        try:
            with credits.metering(ctx.tenant_id, "marketing_campaign", usage_class="long_form_content",
                                  actor_user_id=ctx.user_id):
                generated = content_generator.generate_campaign_content(
                    product_understanding, style=body.style, tone=body.tone, focus=body.focus,
                    strategy_type=body.strategy_type, positioning_label=positioning_label,
                    variants_per_platform=body.variants_per_platform,
                    creative_theme=theme, custom_creative_prompt=body.custom_creative_prompt,
                    language=get_request_language(), usage_out=token_usage, platforms=body.platforms,
                )
        except credits.BudgetError as err:
            if token_usage.get("total_tokens"):
                usage.settle(conn, reservation, token_usage["total_tokens"])
            else:
                usage.release(conn, reservation)
            settled = True
            data_access.mark_campaign_failed(conn, ctx.tenant_id, campaign_id, err.message())
            conn.commit()
            raise
        except content_generator.MarketingGenerationError as err:
            if token_usage.get("total_tokens"):
                usage.settle(conn, reservation, token_usage["total_tokens"])
            else:
                usage.release(conn, reservation)
            conn.commit()
            settled = True
            # The provider's raw error (it names the provider account) stays
            # in the server log; the tenant gets a plain explanation.
            logger.error("Marketing content generation failed (tenant=%s campaign=%s): %s", ctx.tenant_id, campaign_id, err)
            if isinstance(err.__cause__, llm_client.LLMNotConfiguredError):
                message = "Campaign writing isn't set up on this server yet. An administrator needs to configure the AI service."
                data_access.mark_campaign_failed(conn, ctx.tenant_id, campaign_id, message)
                conn.commit()
                raise HTTPException(status_code=503, detail=message, headers={"X-Assistant-Reason": "not_configured"})
            if isinstance(err.__cause__, llm_client.LLMRateLimitError):
                retry_after = max(1, round(err.__cause__.retry_after_seconds or 30))
                message = f"The content generator is handling too many requests right now. Please try again in about {retry_after} seconds."
                data_access.mark_campaign_failed(conn, ctx.tenant_id, campaign_id, message)
                conn.commit()
                raise HTTPException(status_code=503, detail=message, headers={"Retry-After": str(retry_after)})
            message = "Content generation failed: the language model is temporarily unavailable or returned an unusable answer. Please try again."
            data_access.mark_campaign_failed(conn, ctx.tenant_id, campaign_id, message)
            conn.commit()
            raise HTTPException(status_code=502, detail=message)

        data_access.save_campaign_result(conn, ctx.tenant_id, campaign_id, positioning_label, generated)
        # Providers that don't report usage are charged the reserved estimate.
        usage.settle(conn, reservation, token_usage.get("total_tokens") or reservation["amount"])
        conn.commit()
        settled = True

        result = data_access.get_campaign(conn, ctx.tenant_id, campaign_id)
        conn.commit()
        if body.generate_image:
            # One workflow: the copy is saved first, then its image. An image
            # that can't be made leaves a complete campaign with an honest
            # image status (and the allowance unused) - never a failed campaign.
            try:
                image = _generate_image(conn, ctx, campaign_id, result,
                                        image_format=body.image_format or image_generation.DEFAULT_IMAGE_FORMAT)
            except (usage.PlanLimitReached, credits.BudgetError) as err:  # images, storage or AI Credits used up: copy kept
                conn.rollback()
                image = {"image_generation_blocked": err.as_http().detail}
            except HTTPException as err:  # the selected reference photo couldn't be read
                conn.rollback()
                image = {"image_generation_blocked": {"message": err.detail}}
            result = {**data_access.get_campaign(conn, ctx.tenant_id, campaign_id), **{
                k: v for k, v in image.items() if k in ("image_generation_blocked",)}}
            conn.commit()
        return result
    except HTTPException:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        if reservation is not None and not settled:
            # Something failed before the model was asked: give the tokens back.
            try:
                conn.rollback()
                usage.release(conn, reservation)
                conn.commit()
            except Exception:  # noqa: BLE001 - never mask the original error
                logger.exception("Could not release a campaign token reservation (tenant=%s)", ctx.tenant_id)
        conn.close()


@router.get("/suggestions")
def marketing_suggestions_endpoint(product_id: Optional[UUID] = None, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """Upcoming occasions, how this product sold in past ones, and its demand
    and price signals - marketing/occasions.py. Never invents trends."""
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        if product_id is not None and get_product(conn, ctx.tenant_id, str(product_id)) is None:
            raise HTTPException(status_code=404, detail="Product not found")
        return occasions.build_suggestions(conn, ctx.tenant_id, str(product_id) if product_id else None)
    finally:
        conn.close()


@router.get("/options")
def marketing_options_endpoint(ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """Static reference data for the campaign-creation form (strategies,
    visual themes) - kept server-side rather than duplicated in the
    frontend, so the two can never drift apart. Still auth-gated for
    consistency with every other endpoint, even though the content itself
    carries no tenant data (same convention as GET /extraction/templates/{fmt})."""
    return {
        "strategies": content_generator.STRATEGIES,
        "themes": creative_direction.THEMES,
        "image_formats": image_generation.image_formats(),
        "asset_channels": list(data_access.ASSET_CHANNELS),
        "capabilities": {
            "image_generation": image_generation.get_image_generation_capability(),
            "reference_image_generation": image_generation.get_reference_image_capability(),
            "background_removal": background_removal.get_background_removal_capability(),
            "video_generation": video_generation.VIDEO_CAPABILITY,
        },
    }


@router.get("/campaigns")
def list_campaigns_endpoint(
    limit: int = Query(default=data_access.DEFAULT_LIMIT, ge=1, le=data_access.MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    q: Optional[str] = Query(default=None, max_length=100),
    ctx: TenantContext = Depends(get_tenant_context),
) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        result = data_access.list_campaigns(conn, ctx.tenant_id, limit=limit, offset=offset, search=(q or "").strip() or None)
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.get("/campaigns/{campaign_id}")
def get_campaign_endpoint(campaign_id: str, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        result = data_access.get_campaign(conn, ctx.tenant_id, campaign_id)
        conn.commit()
        if result is None:
            raise HTTPException(status_code=404, detail="Campaign not found")
        # The prompt the next image starts from, for the Studio to show and edit.
        return {**result, "image_prompt_default": image_generation.build_image_prompt(result)}
    except HTTPException:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


class VariantEdit(BaseModel):
    platform: str = Field(pattern=r"^(INSTAGRAM|FACEBOOK|TIKTOK|GOOGLE_ADS)$")
    variant_index: int = Field(ge=1, le=10)
    headline: Optional[str] = Field(default=None, max_length=300)
    body_copy: Optional[str] = Field(default=None, min_length=1, max_length=5000)
    hashtags: Optional[list[str]] = Field(default=None, max_length=30)
    cta: Optional[str] = Field(default=None, max_length=120)

    @field_validator("hashtags")
    @classmethod
    def _tidy_hashtags(cls, value):
        if value is None:
            return value
        tags = []
        for tag in value:
            tag = (tag or "").strip()
            if tag:
                tags.append(tag if tag.startswith("#") else f"#{tag}")
        return [t[:80] for t in tags]


class CampaignEditRequest(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=120)
    audience_summary: Optional[str] = Field(default=None, max_length=2000)
    variants: list[VariantEdit] = Field(default_factory=list, max_length=40)


@router.patch("/campaigns/{campaign_id}")
def edit_campaign_endpoint(campaign_id: str, body: CampaignEditRequest, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """Saves the owner's edits to the title, audience note and any copy
    variant (headline, caption, hashtags, call to action). Google Ads
    limits (30 / 90 characters) still apply."""
    for variant in body.variants:
        if variant.platform == "GOOGLE_ADS":
            if variant.headline and len(variant.headline) > 30:
                raise HTTPException(status_code=422, detail="Google Ads headlines can be at most 30 characters.")
            if variant.body_copy and len(variant.body_copy) > 90:
                raise HTTPException(status_code=422, detail="Google Ads descriptions can be at most 90 characters.")
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        try:
            found = data_access.update_campaign_copy(
                conn, ctx.tenant_id, campaign_id, title=body.title.strip() if body.title else None,
                audience_summary=body.audience_summary,
                variants=[v.model_dump(exclude_none=True) for v in body.variants],
            )
        except ValueError as err:
            conn.rollback()
            raise HTTPException(status_code=422, detail=str(err))
        except psycopg2.errors.InvalidTextRepresentation:
            conn.rollback()
            found = False
        if not found:
            raise HTTPException(status_code=404, detail="Campaign not found")
        result = data_access.get_campaign(conn, ctx.tenant_id, campaign_id)
        conn.commit()
        return result
    except HTTPException:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.delete("/campaigns/{campaign_id}")
def delete_campaign_endpoint(campaign_id: str, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """Deletes the campaign, its copy and every image stored for it (which
    then no longer count toward the plan's storage)."""
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        try:
            found = data_access.stored_image_keys(conn, ctx.tenant_id, campaign_id) is not None
        except psycopg2.errors.InvalidTextRepresentation:
            conn.rollback()
            found = False
        if not found:
            raise HTTPException(status_code=404, detail="Campaign not found")
        removed = []
        try:
            removed = image_storage.remove_campaign_images(db.minio_client(), ctx.tenant_id, campaign_id)
        except Exception as err:  # noqa: BLE001 - preserve database/accounting state for a safe retry
            logger.exception("Could not delete the images of campaign %s (tenant=%s)", campaign_id, ctx.tenant_id)
            raise HTTPException(status_code=502, detail="Could not delete stored campaign images. Please try again.") from err
        with conn.cursor() as cursor:
            cursor.execute(
                "DELETE FROM tenant_storage_objects WHERE tenant_id = %s AND kind LIKE 'marketing_%%' AND object_key LIKE %s;",
                (ctx.tenant_id, f"{ctx.tenant_id}/{campaign_id}/%"),
            )
        data_access.delete_campaign(conn, ctx.tenant_id, campaign_id)
        conn.commit()
        return {"campaign_id": campaign_id, "deleted": True, "images_removed": len(removed)}
    except HTTPException:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _detect_image_ext(filename: str) -> str:
    ext = os.path.splitext(filename or "")[1].lower()
    if ext not in _IMAGE_CONTENT_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported image type - use .jpg, .jpeg, .png, or .webp.")
    return ext


def _read_image_within_limit(file: UploadFile) -> bytes:
    contents = file.file.read(_MAX_IMAGE_BYTES + 1)
    if len(contents) > _MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail=f"Image exceeds the {_MAX_IMAGE_BYTES}-byte upload limit.")
    if not contents:
        raise HTTPException(status_code=400, detail="Uploaded image is empty.")
    return contents


def _validate_image_content(ext: str, contents: bytes) -> None:
    expected_magic = _IMAGE_MAGIC_BYTES.get(ext)
    if expected_magic and not contents.startswith(expected_magic):
        raise HTTPException(status_code=400, detail=f"File content doesn't match its '{ext}' extension.")
    if ext == ".webp" and not (contents[:4] == b"RIFF" and contents[8:12] == b"WEBP"):
        raise HTTPException(status_code=400, detail="File content doesn't match its '.webp' extension.")


@router.post("/campaigns/{campaign_id}/image")
def upload_campaign_image_endpoint(
    campaign_id: str, file: UploadFile = File(...), ctx: TenantContext = Depends(get_tenant_context),
) -> dict:
    """
    Stores an optional source product image for an existing campaign.
    Phase 1 only stores it (same extension allowlist/magic-byte/size-cap
    security pattern as extraction.py's own upload endpoint, applied to
    image types) - it is never analyzed, since no vision model exists in
    this repo. The campaign's generated content is unaffected by this
    call; a caller that wants the image reflected in generated copy must
    describe it via the `text` field on campaign creation instead.
    """
    ext = _detect_image_ext(file.filename or "")
    contents = _read_image_within_limit(file)
    _validate_image_content(ext, contents)

    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    image_key = None
    minio_client = None
    preupload_recorded = False

    def mark_preupload_recorded():
        nonlocal preupload_recorded
        preupload_recorded = True

    try:
        existing = data_access.get_campaign(conn, ctx.tenant_id, campaign_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="Campaign not found")
        minio_client = db.minio_client()
        _reconcile_stale_marketing_uploads(conn, minio_client, ctx.tenant_id)
        # The plan's storage limit and monthly upload allowance cover images too.
        usage.ensure_capacity(conn, ctx.tenant_id, usage.DOCUMENT_STORAGE_MB, len(contents) / 1048576)
        usage.reserve(conn, ctx.tenant_id, usage.DOCUMENT_EXTRACTION, max(1, -(-len(contents) // 1024)))

        image_key = image_storage.new_image_object_key(ctx.tenant_id, campaign_id, ext)
        image_key = image_storage.upload_source_image(
            minio_client, contents, _IMAGE_CONTENT_TYPES[ext], ctx.tenant_id, campaign_id, ext,
            object_key=image_key,
            on_pre_upload=_track_image_before_put(ctx, "marketing_source_image", mark_preupload_recorded),
        )
        data_access.set_source_image_key(conn, ctx.tenant_id, campaign_id, image_key)
        storage_ledger.record(conn, ctx.tenant_id, image_storage.SOURCE_IMAGES_BUCKET, image_key, len(contents), "marketing_source_image")
        conn.commit()
        return {
            "campaign_id": campaign_id,
            "source_image_key": image_key,
            "note": "Image stored. This platform does not yet analyze image content - generated copy is based only on the text/URL/product information provided.",
        }
    except HTTPException:
        conn.rollback()
        if image_key and minio_client and preupload_recorded:
            _compensate_image_upload(conn, ctx.tenant_id, campaign_id, image_storage.SOURCE_IMAGES_BUCKET, image_key,
                                     len(contents), "marketing_source_image", minio_client)
        raise
    except Exception:
        conn.rollback()
        if image_key and minio_client and preupload_recorded:
            _compensate_image_upload(conn, ctx.tenant_id, campaign_id, image_storage.SOURCE_IMAGES_BUCKET, image_key,
                                     len(contents), "marketing_source_image", minio_client)
        raise
    finally:
        conn.close()


@router.post("/campaigns/{campaign_id}/remove-background")
def remove_background_endpoint(campaign_id: str, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """
    Real background removal (src/ai/marketing/background_removal.py),
    dispatched by MARKETING_BACKGROUND_REMOVAL_PROVIDER - unset (and
    therefore NOT_CONFIGURED) by default; see that module's own docstring
    for exactly why it is not safe to enable on this platform's current
    $0 Render staging plan. Operates on the campaign's existing
    source_image_key (the tenant's own upload via POST .../image) - 404s
    if no source image was ever uploaded, since there is nothing to
    process. Never modifies or deletes source_image_key itself; the result
    is stored separately as source_image_processed_key, same honest-state
    convention as generate-image: always 200 with a real
    background_removal_status, never a fake COMPLETED.
    """
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    processed_key = None
    minio_client = None
    processed_size = 0
    preupload_recorded = False

    def mark_preupload_recorded():
        nonlocal preupload_recorded
        preupload_recorded = True

    try:
        campaign = data_access.get_campaign(conn, ctx.tenant_id, campaign_id)
        if campaign is None:
            raise HTTPException(status_code=404, detail="Campaign not found")
        if not campaign.get("source_image_key"):
            raise HTTPException(status_code=409, detail="Upload a source product image (POST .../image) before removing its background.")

        minio_client = db.minio_client()
        _reconcile_stale_marketing_uploads(conn, minio_client, ctx.tenant_id)
        try:
            original_bytes, _content_type = image_storage.get_image(minio_client, image_storage.SOURCE_IMAGES_BUCKET, campaign["source_image_key"])
        except Exception as err:
            logger.error("Could not read source image (tenant=%s): %s", ctx.tenant_id, err)
            raise HTTPException(status_code=502, detail="Could not read the source image. Please try again.") from err

        try:
            processed = background_removal.remove_background(original_bytes)
        except background_removal.BackgroundRemovalError as err:
            data_access.save_background_removal_failure(
                conn, ctx.tenant_id, campaign_id, status=err.status, error_message=err.message,
                provider=os.getenv("MARKETING_BACKGROUND_REMOVAL_PROVIDER") or None,
            )
            conn.commit()
            return {
                "campaign_id": campaign_id, "background_removal_status": err.status,
                "background_removal_provider": os.getenv("MARKETING_BACKGROUND_REMOVAL_PROVIDER") or None,
                "background_removal_error": err.message,
            }

        usage.ensure_capacity(conn, ctx.tenant_id, usage.DOCUMENT_STORAGE_MB, len(processed.content) / 1048576)
        processed_size = len(processed.content)
        processed_key = image_storage.new_processed_image_object_key(
            ctx.tenant_id, campaign_id, processed.content_type,
        )
        processed_key = image_storage.upload_processed_image(
            minio_client, processed.content, processed.content_type, ctx.tenant_id, campaign_id,
            object_key=processed_key,
            on_pre_upload=_track_image_before_put(ctx, "marketing_processed_image", mark_preupload_recorded),
        )
        data_access.save_processed_image(conn, ctx.tenant_id, campaign_id, provider=processed.provider, image_key=processed_key)
        storage_ledger.record(conn, ctx.tenant_id, image_storage.PROCESSED_IMAGES_BUCKET, processed_key,
                              len(processed.content), "marketing_processed_image")
        conn.commit()
        return {
            "campaign_id": campaign_id, "background_removal_status": "COMPLETED",
            "background_removal_provider": processed.provider, "source_image_processed_key": processed_key,
        }
    except HTTPException:
        conn.rollback()
        if processed_key and minio_client and preupload_recorded:
            _compensate_image_upload(conn, ctx.tenant_id, campaign_id, image_storage.PROCESSED_IMAGES_BUCKET, processed_key,
                                     processed_size, "marketing_processed_image", minio_client)
        raise
    except Exception:
        conn.rollback()
        if processed_key and minio_client and preupload_recorded:
            _compensate_image_upload(conn, ctx.tenant_id, campaign_id, image_storage.PROCESSED_IMAGES_BUCKET, processed_key,
                                     processed_size, "marketing_processed_image", minio_client)
        raise
    finally:
        conn.close()


class ReferenceSelectionRequest(BaseModel):
    """Which stored image (if either) this campaign should treat as its
    product reference for a future generate-image call. None clears the
    selection (equivalent to "don't use a reference"). Validated against
    the campaign's own actually-stored keys in the endpoint, not here -
    this model only constrains the shape of the value itself."""
    selection: Optional[str] = None

    @field_validator("selection")
    @classmethod
    def _valid_selection(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and value not in ("ORIGINAL", "PROCESSED"):
            raise ValueError("selection must be 'ORIGINAL', 'PROCESSED', or null")
        return value


@router.post("/campaigns/{campaign_id}/reference-selection")
def set_reference_selection_endpoint(
    campaign_id: str, body: ReferenceSelectionRequest, ctx: TenantContext = Depends(get_tenant_context),
) -> dict:
    """Records which image the tenant wants used as this campaign's
    product reference. Does not itself generate anything - the next POST
    .../generate-image reads this selection (see that endpoint's own
    docstring for why setting it does not by itself guarantee the product
    photo is actually reflected in the result)."""
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        campaign = data_access.get_campaign(conn, ctx.tenant_id, campaign_id)
        if campaign is None:
            raise HTTPException(status_code=404, detail="Campaign not found")
        if body.selection == "ORIGINAL" and not campaign.get("source_image_key"):
            raise HTTPException(status_code=409, detail="No original source image has been uploaded for this campaign yet.")
        if body.selection == "PROCESSED" and not campaign.get("source_image_processed_key"):
            raise HTTPException(status_code=409, detail="No background-removed image has been produced for this campaign yet.")

        data_access.set_reference_image_selection(conn, ctx.tenant_id, campaign_id, body.selection)
        conn.commit()
        return {"campaign_id": campaign_id, "reference_image_selection": body.selection}
    except HTTPException:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _generate_image(conn, ctx: TenantContext, campaign_id: str, campaign: dict, *,
                    image_format: str = image_generation.DEFAULT_IMAGE_FORMAT, prompt: Optional[str] = None,
                    channel: Optional[str] = None, attach: bool = True) -> dict:
    """Generate through the shared gallery/service path while retaining durable
    pre-upload storage accounting and stale-object recovery.
    """
    try:
        client = db.minio_client()
        _reconcile_stale_marketing_uploads(conn, client, ctx.tenant_id)
    except Exception:
        logger.exception("Could not run stale-image recovery before generation (tenant=%s)", ctx.tenant_id)

    upload = {}
    def remember_preupload(bucket: str, object_key: str, size_bytes: int) -> None:
        upload.update(bucket=bucket, object_key=object_key, size_bytes=size_bytes)

    track_preupload = _track_image_before_put(ctx, "marketing_generated_image")
    def on_pre_upload(bucket: str, object_key: str, size_bytes: int) -> None:
        remember_preupload(bucket, object_key, size_bytes)
        track_preupload(bucket, object_key, size_bytes)

    try:
        return image_service.generate_and_store(
            conn, ctx.tenant_id, ctx.user_id, campaign_id, campaign,
            image_format=image_format, prompt=prompt, channel=channel, attach=attach,
            on_pre_upload=on_pre_upload,
        )
    except image_service.ReferenceImageError as err:
        raise HTTPException(status_code=502, detail="Could not read the selected reference image. Please try again.") from err
    except Exception:
        if upload:
            try:
                _compensate_image_upload(
                    conn, ctx.tenant_id, campaign_id, upload["bucket"], upload["object_key"],
                    upload["size_bytes"], "marketing_generated_image", client,
                )
            except Exception:
                logger.exception("Could not reconcile failed generated image (tenant=%s campaign=%s)", ctx.tenant_id, campaign_id)
        raise


class GenerateImageRequest(BaseModel):
    """Optional gallery generation controls; an empty body uses the campaign prompt."""
    image_format: str = Field(default=image_generation.DEFAULT_IMAGE_FORMAT)
    prompt: Optional[str] = Field(default=None, max_length=2000)
    channel: Optional[str] = None
    attach: bool = True

    @field_validator("image_format")
    @classmethod
    def _valid_format(cls, value: str) -> str:
        if value not in image_generation.IMAGE_FORMATS:
            raise ValueError(f"image_format must be one of {list(image_generation.IMAGE_FORMATS)}")
        return value

    @field_validator("channel")
    @classmethod
    def _valid_channel(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and value not in data_access.ASSET_CHANNELS:
            raise ValueError(f"channel must be one of {list(data_access.ASSET_CHANNELS)}")
        return value


@router.post("/campaigns/{campaign_id}/generate-image")
def generate_campaign_image_endpoint(
    campaign_id: str, body: Optional[GenerateImageRequest] = None,
    ctx: TenantContext = Depends(get_tenant_context),
) -> dict:
    """
    (Re)generates the campaign's image - the "Regenerate image" action; a
    new campaign gets its image during creation (generate_image=true).
    Synchronous: this service has no background worker to defer onto.

    Always returns 200 with an honest image_generation_status -
    NOT_CONFIGURED and PROVIDER_ERROR are real outcomes, not exceptions.
    404/409 when the campaign doesn't exist or has no copy yet; 402 when the
    plan's image allowance or storage is used up.
    """
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        campaign = data_access.get_campaign(conn, ctx.tenant_id, campaign_id)
        if campaign is None:
            raise HTTPException(status_code=404, detail="Campaign not found")
        if campaign["status"] != "COMPLETED":
            raise HTTPException(status_code=409, detail="Campaign content must be generated successfully before an image can be generated.")
        body = body or GenerateImageRequest()
        return _generate_image(conn, ctx, campaign_id, campaign, image_format=body.image_format,
                               prompt=body.prompt, channel=body.channel, attach=body.attach)
    except HTTPException:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


_IMAGE_KIND_FIELDS = {
    "source": ("source_image_key", image_storage.SOURCE_IMAGES_BUCKET),
    "processed": ("source_image_processed_key", image_storage.PROCESSED_IMAGES_BUCKET),
    "generated": ("generated_image_key", image_storage.GENERATED_IMAGES_BUCKET),
}


@router.get("/campaigns/{campaign_id}/image")
def get_campaign_image_endpoint(
    campaign_id: str, kind: str = Query(default="generated", pattern="^(source|processed|generated)$"),
    ctx: TenantContext = Depends(get_tenant_context),
) -> Response:
    """Streams a stored campaign image (uploaded source, its background-
    removed processed version, or AI-generated) back through this
    authenticated API rather than a signed MinIO URL - keeps every tenant-
    scoped read behind the same get_tenant_context boundary every other
    endpoint in this service uses, with no separate object-storage
    exposure to reason about."""
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        campaign = data_access.get_campaign(conn, ctx.tenant_id, campaign_id)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")

    field, bucket = _IMAGE_KIND_FIELDS[kind]
    key = campaign[field]
    if not key:
        raise HTTPException(status_code=404, detail=f"No {kind} image stored for this campaign.")

    try:
        content, content_type = image_storage.get_image(db.minio_client(), bucket, key)
    except Exception as err:
        logger.error("Could not read stored image (tenant=%s): %s", ctx.tenant_id, err)
        raise HTTPException(status_code=502, detail="Could not read the stored image. Please try again.") from err
    return Response(content=content, media_type=content_type)


# --- Image gallery -----------------------------------------------------------
# Every image made for a campaign (campaign_image_assets). All reads and
# writes go through the company's RLS-scoped connection, and an asset is
# only ever looked up together with its campaign id, so a guessed asset id
# from another campaign or company is simply "not found".

def _asset_or_404(conn, ctx: TenantContext, campaign_id: str, asset_id: str) -> dict:
    try:
        asset = data_access.get_image_asset(conn, ctx.tenant_id, campaign_id, asset_id)
    except psycopg2.errors.InvalidTextRepresentation:  # not a UUID
        conn.rollback()
        asset = None
    if asset is None:
        raise HTTPException(status_code=404, detail="Image not found")
    return asset


@router.get("/campaigns/{campaign_id}/assets")
def list_campaign_assets_endpoint(campaign_id: str, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """The campaign's images, newest first; `attached` marks the one its post uses."""
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        try:
            assets = data_access.list_image_assets(conn, ctx.tenant_id, campaign_id)
        except psycopg2.errors.InvalidTextRepresentation:
            conn.rollback()
            assets = None
        conn.commit()
        if assets is None:
            raise HTTPException(status_code=404, detail="Campaign not found")
        return {"campaign_id": campaign_id, "assets": assets}
    finally:
        conn.close()


@router.get("/campaigns/{campaign_id}/assets/{asset_id}/image")
def get_campaign_asset_image_endpoint(campaign_id: str, asset_id: str,
                                      ctx: TenantContext = Depends(get_tenant_context)) -> Response:
    """Streams one gallery image through this authenticated API (never a
    direct storage URL), like GET .../image."""
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        asset = _asset_or_404(conn, ctx, campaign_id, asset_id)
        conn.commit()
    finally:
        conn.close()
    # Defence in depth: a stored key always sits under this company's own prefix.
    if not asset["image_key"].startswith(f"{ctx.tenant_id}/{campaign_id}/"):
        logger.error("Asset %s key outside its company prefix (tenant=%s)", asset_id, ctx.tenant_id)
        raise HTTPException(status_code=404, detail="Image not found")
    try:
        content, content_type = image_storage.get_image(db.minio_client(), image_storage.GENERATED_IMAGES_BUCKET,
                                                        asset["image_key"])
    except Exception as err:
        logger.error("Could not read stored asset (tenant=%s): %s", ctx.tenant_id, err)
        raise HTTPException(status_code=502, detail="Could not read the stored image. Please try again.") from err
    return Response(content=content, media_type=content_type, headers={"Cache-Control": "private, max-age=3600"})


class AssetUpdateRequest(BaseModel):
    """attach: make this the campaign's image. channel: where it will be
    used (null clears it). Send either or both."""
    attach: Optional[bool] = None
    channel: Optional[str] = None
    clear_channel: bool = False

    @field_validator("channel")
    @classmethod
    def _valid_channel(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and value not in data_access.ASSET_CHANNELS:
            raise ValueError(f"channel must be one of {list(data_access.ASSET_CHANNELS)}")
        return value


@router.patch("/campaigns/{campaign_id}/assets/{asset_id}")
def update_campaign_asset_endpoint(campaign_id: str, asset_id: str, body: AssetUpdateRequest,
                                   ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        asset = _asset_or_404(conn, ctx, campaign_id, asset_id)
        if body.channel is not None or body.clear_channel:
            data_access.set_image_asset_channel(conn, ctx.tenant_id, campaign_id, asset_id, body.channel)
        if body.attach:
            data_access.attach_image_asset(conn, ctx.tenant_id, campaign_id, asset["image_key"], asset["mode"],
                                           asset["used_reference"])
        result = data_access.get_image_asset_public(conn, ctx.tenant_id, campaign_id, asset_id)
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


@router.delete("/campaigns/{campaign_id}/assets/{asset_id}")
def delete_campaign_asset_endpoint(campaign_id: str, asset_id: str,
                                   ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """Deletes one gallery image (its file too, which then no longer counts
    toward storage). Deleting the attached image attaches the newest one left."""
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        _asset_or_404(conn, ctx, campaign_id, asset_id)
        asset = data_access.delete_image_asset(conn, ctx.tenant_id, campaign_id, asset_id)
        storage_ledger.forget(conn, ctx.tenant_id, image_storage.GENERATED_IMAGES_BUCKET, asset["image_key"])
        conn.commit()
    except HTTPException:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    try:
        image_storage.remove_image(db.minio_client(), image_storage.GENERATED_IMAGES_BUCKET, asset["image_key"])
    except Exception:  # noqa: BLE001 - the record is gone; a leftover file is only logged
        logger.exception("Could not delete asset file (tenant=%s campaign=%s)", ctx.tenant_id, campaign_id)
    return {"campaign_id": campaign_id, "asset_id": asset_id, "deleted": True}


# --- Background image batches ------------------------------------------------
# Many images at once (formats x variations) are queued and made by the image
# worker (marketing/image_worker.py), so no request waits minutes per image.

class ImageBatchRequest(BaseModel):
    formats: List[str] = Field(min_length=1, max_length=5)
    variations: int = Field(default=1, ge=1, le=image_jobs.BATCH_MAX)
    prompt: Optional[str] = Field(default=None, max_length=2000)
    channel: Optional[str] = None
    # Attach the first image of the batch to the campaign when it is made.
    attach_first: bool = False

    @field_validator("formats")
    @classmethod
    def _valid_formats(cls, value: List[str]) -> List[str]:
        if any(f not in image_generation.IMAGE_FORMATS for f in value):
            raise ValueError(f"formats must be among {list(image_generation.IMAGE_FORMATS)}")
        return value

    @field_validator("channel")
    @classmethod
    def _valid_channel(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and value not in data_access.ASSET_CHANNELS:
            raise ValueError(f"channel must be one of {list(data_access.ASSET_CHANNELS)}")
        return value


def _completed_campaign_or_error(conn, ctx: TenantContext, campaign_id: str) -> dict:
    try:
        campaign = data_access.get_campaign(conn, ctx.tenant_id, campaign_id)
    except psycopg2.errors.InvalidTextRepresentation:
        conn.rollback()
        campaign = None
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if campaign["status"] != "COMPLETED":
        raise HTTPException(status_code=409, detail="Campaign content must be generated successfully before images can be made.")
    return campaign


@router.post("/campaigns/{campaign_id}/image-batches")
def queue_image_batch_endpoint(campaign_id: str, body: ImageBatchRequest,
                               ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """Queues variations x formats images for the background worker. 202-like:
    returns at once with the batch id; GET .../image-jobs shows progress and
    every finished image appears in the gallery. 429 when over the request
    or per-company queue limit (image_jobs.py)."""
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        _completed_campaign_or_error(conn, ctx, campaign_id)
        try:
            batch = image_jobs.enqueue_batch(
                conn, ctx.tenant_id, ctx.user_id, campaign_id, formats=body.formats, variations=body.variations,
                prompt=body.prompt, channel=body.channel, attach_first=body.attach_first,
            )
        except image_jobs.QueueLimit as err:
            conn.rollback()
            raise HTTPException(status_code=429, detail={"message": err.message, "limit": err.limit, "pending": err.pending})
        if (body.prompt or "").strip():
            data_access.set_image_prompt(conn, ctx.tenant_id, campaign_id, body.prompt.strip()[:2000])
        conn.commit()
        return {**batch, "campaign_id": campaign_id, "capacity": image_jobs.capacity(conn)}
    except HTTPException:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.get("/campaigns/{campaign_id}/image-jobs")
def list_image_jobs_endpoint(campaign_id: str, batch_id: Optional[UUID] = None, limit: int = Query(default=200, ge=1, le=1000),
                             ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        try:
            if data_access.get_campaign(conn, ctx.tenant_id, campaign_id) is None:
                raise HTTPException(status_code=404, detail="Campaign not found")
        except psycopg2.errors.InvalidTextRepresentation:
            conn.rollback()
            raise HTTPException(status_code=404, detail="Campaign not found")
        result = image_jobs.list_jobs(conn, ctx.tenant_id, campaign_id=campaign_id,
                                      batch_id=str(batch_id) if batch_id else None, limit=limit)
        conn.commit()
        return {"campaign_id": campaign_id, **result}
    finally:
        conn.close()


class ImageJobsActionRequest(BaseModel):
    batch_id: Optional[UUID] = None


@router.post("/campaigns/{campaign_id}/image-jobs/cancel")
def cancel_image_jobs_endpoint(campaign_id: str, body: Optional[ImageJobsActionRequest] = None,
                               ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """Cancels the campaign's waiting images (one being made finishes)."""
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        if _campaign_exists(conn, ctx, campaign_id) is False:
            raise HTTPException(status_code=404, detail="Campaign not found")
        batch = str(body.batch_id) if body and body.batch_id else None
        cancelled = image_jobs.cancel(conn, ctx.tenant_id, campaign_id, batch)
        conn.commit()
        return {"campaign_id": campaign_id, "cancelled": cancelled}
    finally:
        conn.close()


@router.post("/campaigns/{campaign_id}/image-jobs/retry")
def retry_image_jobs_endpoint(campaign_id: str, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """Queues the campaign's failed images again."""
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        if _campaign_exists(conn, ctx, campaign_id) is False:
            raise HTTPException(status_code=404, detail="Campaign not found")
        retried = image_jobs.retry_failed(conn, ctx.tenant_id, campaign_id)
        conn.commit()
        return {"campaign_id": campaign_id, "requeued": retried}
    finally:
        conn.close()


def _campaign_exists(conn, ctx: TenantContext, campaign_id: str) -> bool:
    try:
        return data_access.get_campaign(conn, ctx.tenant_id, campaign_id) is not None
    except psycopg2.errors.InvalidTextRepresentation:
        conn.rollback()
        return False


@router.get("/image-capacity")
def image_capacity_endpoint(ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """Measured queue capacity (no company's data): live workers and image
    servers, recent seconds per image, images per hour, queue wait - and
    whether only self-hosted servers (no per-image cost) are in use."""
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        result = image_jobs.capacity(conn)
        conn.commit()
    finally:
        conn.close()
    return {**result, "self_hosted_only": image_generation.only_self_hosted(),
            "uses_plan_allowance": image_service.uses_plan_allowance(),
            "servers": image_generation.local_server_health()}
