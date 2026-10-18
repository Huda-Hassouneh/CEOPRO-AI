-- Automated Marketing System (Phase 2): real AI image generation.
--
-- generated_image_key already existed on `campaigns` (20260807225947) but
-- was never written to - reserved for exactly this. The four new columns
-- record the honest outcome of a generation attempt so the frontend can
-- render "generated" / "not configured" / "provider error" distinctly
-- rather than inferring state from generated_image_key alone (NULL is
-- ambiguous between "never requested" and "failed").
--
-- image_generation_status vocabulary matches src/ai/marketing/
-- image_generation.py's own ImageGenerationError.status values exactly -
-- never a bare "FAILED"/"error" that would blur "no provider configured"
-- (an operator/deployment fact) with "the configured provider's call
-- failed" (a real, per-request outcome) into one meaning.

ALTER TABLE campaigns
    ADD COLUMN IF NOT EXISTS image_generation_status VARCHAR(20)
        CONSTRAINT chk_campaigns_image_generation_status CHECK (
            image_generation_status IS NULL OR image_generation_status IN ('COMPLETED', 'NOT_CONFIGURED', 'PROVIDER_ERROR')
        ),
    ADD COLUMN IF NOT EXISTS image_generation_provider VARCHAR(30),
    ADD COLUMN IF NOT EXISTS image_generation_error TEXT,
    ADD COLUMN IF NOT EXISTS image_generated_at TIMESTAMP WITH TIME ZONE;
