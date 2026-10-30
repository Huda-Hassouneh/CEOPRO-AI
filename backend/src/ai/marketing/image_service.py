"""
KEEL - make one campaign image and store it in the campaign's gallery.

Shared by the API (POST .../generate-image, campaign creation) and the
background image worker (marketing/image_worker.py), so both store,
account and fall back in exactly the same way.

Plan image allowance: each image is reserved against the plan's
`marketing_image_generation` count before any provider is called and given
back when nothing comes out. That count exists to cap hosted providers'
per-image cost; when every usable provider is a self-hosted image server
(no per-image cost - see image_generation.only_self_hosted()), it is not
used, unless MARKETING_SELF_HOSTED_IMAGES_USE_PLAN_ALLOWANCE=true. Storage
limits always apply.
"""
import logging
import os
from datetime import datetime, timezone
from typing import Callable, Optional

from src.ai import db
from src.ai.billing import credits
from src.ai.core import storage_ledger, usage
from src.ai.marketing import data_access, designed_poster, image_generation, image_storage

logger = logging.getLogger("CEOPRO_AI_MARKETING")


class ReferenceImageError(Exception):
    """The campaign's selected product photo could not be read from storage."""


def load_reference_image(client, campaign: dict) -> tuple:
    """Resolves campaign.reference_image_selection ('ORIGINAL'/'PROCESSED'/
    None) into real stored image bytes, or (None, None) if nothing is
    selected or the selected version was never actually stored (e.g. the
    tenant picked PROCESSED before background removal ever completed) -
    silently falling back to no reference rather than erroring the whole
    generation attempt over a stale selection."""
    selection = campaign.get("reference_image_selection")
    if selection == "PROCESSED" and campaign.get("source_image_processed_key"):
        return image_storage.get_image(client, image_storage.PROCESSED_IMAGES_BUCKET, campaign["source_image_processed_key"])
    if selection == "ORIGINAL" and campaign.get("source_image_key"):
        return image_storage.get_image(client, image_storage.SOURCE_IMAGES_BUCKET, campaign["source_image_key"])
    return None, None


def uses_plan_allowance() -> bool:
    if os.getenv("MARKETING_SELF_HOSTED_IMAGES_USE_PLAN_ALLOWANCE", "false").strip().lower() in ("1", "true", "yes"):
        return True
    return not image_generation.only_self_hosted()


def generate_and_store(conn, tenant_id: str, user_id: Optional[str], campaign_id: str, campaign: dict, *,
                       image_format: str = image_generation.DEFAULT_IMAGE_FORMAT, prompt: Optional[str] = None,
                       channel: Optional[str] = None, attach: bool = True, seed: Optional[int] = None,
                       fallback_to_designed: bool = True,
                       on_pre_upload: Optional[Callable[[str, str, int], None]] = None) -> dict:
    """Makes a campaign image in `image_format` with the provider chain and
    adds it to the campaign's gallery (campaign_image_assets); with attach
    (or when the campaign has no image yet) it becomes the image the campaign
    uses. Earlier images stay in the gallery until deleted. `prompt` is the
    owner's edited image prompt (kept for next time); otherwise it is built
    from the campaign. `seed` makes a distinct, reproducible variation on
    providers that take one.

    When no provider makes an image: with fallback_to_designed (the API) a
    designed poster is stored instead and the outcome says so; without it
    (the background worker, which retries later) ImageGenerationError is
    raised. Raises ReferenceImageError for an unreadable product photo and
    usage.PlanLimitReached / credits.BudgetError before any provider call."""
    reference_content = reference_content_type = None
    if campaign.get("reference_image_selection"):
        try:
            reference_content, reference_content_type = load_reference_image(db.minio_client(), campaign)
        except Exception as err:
            logger.error("Could not read reference image (tenant=%s campaign=%s): %s", tenant_id, campaign_id, err)
            raise ReferenceImageError(str(err)) from err

    if (prompt or "").strip():
        prompt = prompt.strip()[:2000]
        data_access.set_image_prompt(conn, tenant_id, campaign_id, prompt)
    else:
        prompt = image_generation.build_image_prompt(campaign)
    usage.ensure_capacity(conn, tenant_id, usage.DOCUMENT_STORAGE_MB, 0.001)  # refuse when storage is full
    reservation = usage.reserve(conn, tenant_id, usage.IMAGE_GENERATION) if uses_plan_allowance() else None
    conn.commit()
    try:
        try:
            with credits.metering(tenant_id, "marketing_image", usage_class="image_generation",
                                  actor_user_id=user_id):
                generated = image_generation.generate_campaign_image(
                    prompt, reference_image=reference_content, reference_content_type=reference_content_type,
                    image_format=image_format, **({"seed": seed} if seed is not None else {}),
                )
        except image_generation.ImageGenerationError as err:
            if not fallback_to_designed:
                raise
            # No AI image (free allowances used up / providers down / none
            # configured): deliver a designed poster from the campaign's own
            # copy (+ the product photo if selected) so the tenant always gets
            # a finished, watermark-free image. Not AI-generated - and it says so.
            logger.warning("No AI image for campaign %s (%s); using the designed poster", campaign_id, err.message)
            try:
                poster_size = image_generation.IMAGE_FORMATS[image_format]["poster"]
                generated = image_generation.GeneratedImage(
                    content=designed_poster.render_designed_poster(campaign, reference_content, poster_size),
                    content_type="image/png", provider="designed", mode="designed",
                    used_reference=bool(reference_content), width=poster_size[0], height=poster_size[1],
                    image_format=image_format,
                )
            except Exception:  # noqa: BLE001 - never turn a render bug into a lost image: report honestly
                logger.exception("Designed poster failed for campaign %s", campaign_id)
                if reservation is not None:
                    usage.release(conn, reservation)
                    reservation = None
                data_access.save_image_generation_failure(
                    conn, tenant_id, campaign_id, status=err.status, error_message=err.message, provider=None,
                )
                conn.commit()
                return {
                    "campaign_id": campaign_id, "image_generation_status": err.status,
                    "image_generation_provider": None, "image_generation_error": err.message,
                    "image_generation_used_reference": False, "image_generation_reference_note": None,
                }

        client = db.minio_client()
        image_key = image_storage.upload_generated_image(
            client, generated.content, generated.content_type, tenant_id, campaign_id,
            on_pre_upload=on_pre_upload,
        )
        # Only "ai" or "designed" is shown; which provider/model served it is
        # kept for operators (server log and the asset row), never returned.
        logger.info("Campaign %s image served by %s (%s)", campaign_id, generated.provider, image_format)
        asset_id = data_access.add_image_asset(
            conn, tenant_id, campaign_id, image_key=image_key, image_format=image_format, mode=generated.mode,
            provider=generated.provider, model=generated.model, prompt=prompt, width=generated.width,
            height=generated.height, content_type=generated.content_type, size_bytes=len(generated.content),
            used_reference=generated.used_reference, channel=channel, created_by=user_id,
        )
        attached = attach or not campaign.get("generated_image_key")
        if attached:
            data_access.save_generated_image(
                conn, tenant_id, campaign_id, provider=generated.mode, image_key=image_key,
                used_reference=generated.used_reference, reference_note=generated.reference_note,
            )
        storage_ledger.record(conn, tenant_id, image_storage.GENERATED_IMAGES_BUCKET, image_key,
                              len(generated.content), "marketing_generated_image")
        conn.commit()
        reservation = None  # used: an image was produced and saved
        current_key = image_key if attached else campaign.get("generated_image_key")
        return {
            "campaign_id": campaign_id, "image_generation_status": "COMPLETED",
            "image_generation_provider": generated.mode, "image_generation_mode": generated.mode,
            "generated_image_key": current_key,
            "image_generation_used_reference": generated.used_reference,
            "image_generation_reference_note": generated.reference_note,
            # The gallery entry just written (same shape as GET .../assets).
            "asset": {
                "asset_id": asset_id, "image_format": image_format, "channel": channel, "mode": generated.mode,
                "prompt": prompt, "width": generated.width, "height": generated.height,
                "content_type": generated.content_type, "size_bytes": len(generated.content),
                "used_reference": generated.used_reference,
                "created_at": datetime.now(timezone.utc).isoformat(), "attached": attached,
            },
        }
    finally:
        if reservation is not None:  # failed after reserving: give it back
            try:
                conn.rollback()
                usage.release(conn, reservation)
                conn.commit()
            except Exception:
                logger.exception("Could not release an unused image reservation (tenant=%s)", tenant_id)
