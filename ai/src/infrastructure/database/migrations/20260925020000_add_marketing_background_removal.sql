-- Automated Marketing System: product reference image workflow.
--
-- source_image_key (existing, 20260925000000) is the tenant's original
-- upload, untouched by anything here - background removal never deletes
-- or overwrites it. source_image_processed_key is the separate, optional
-- background-removed version (src/ai/marketing/background_removal.py),
-- stored alongside the original so a tenant can switch between them at
-- any time. background_removal_status follows the exact same honest-state
-- vocabulary as image_generation_status (20260925010000) - NOT_CONFIGURED
-- when no provider is set (the default - see backend/requirements.txt's
-- own note on why rembg is off by default on this platform's free-tier
-- hosting), PROVIDER_ERROR for a real failure, never silently COMPLETED
-- for anything less than a real processed image actually stored.
--
-- reference_image_selection records which of the two (if either) the
-- tenant has chosen to use as this campaign's product reference for a
-- future/real reference-image generation call. image_generation_used_reference
-- and image_generation_reference_note record the honest outcome of the
-- *last* generate-image call specifically: neither image-generation
-- provider implemented in this pass (Pollinations, Hugging Face's default
-- text-to-image model) actually supports a reference/product image - see
-- MARKETING_AI_CAPABILITIES.md - so a campaign can have a real, valid
-- reference_image_selection while image_generation_used_reference stays
-- false, and the frontend must show the reference_note explaining why
-- rather than implying the product photo was used when it wasn't.

ALTER TABLE campaigns
    ADD COLUMN IF NOT EXISTS source_image_processed_key VARCHAR(512),
    ADD COLUMN IF NOT EXISTS background_removal_status VARCHAR(20)
        CONSTRAINT chk_campaigns_background_removal_status CHECK (
            background_removal_status IS NULL OR background_removal_status IN ('COMPLETED', 'NOT_CONFIGURED', 'PROVIDER_ERROR')
        ),
    ADD COLUMN IF NOT EXISTS background_removal_provider VARCHAR(30),
    ADD COLUMN IF NOT EXISTS background_removal_error TEXT,
    ADD COLUMN IF NOT EXISTS background_removal_completed_at TIMESTAMP WITH TIME ZONE,
    ADD COLUMN IF NOT EXISTS reference_image_selection VARCHAR(10)
        CONSTRAINT chk_campaigns_reference_image_selection CHECK (
            reference_image_selection IS NULL OR reference_image_selection IN ('ORIGINAL', 'PROCESSED')
        ),
    ADD COLUMN IF NOT EXISTS image_generation_used_reference BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS image_generation_reference_note TEXT;
