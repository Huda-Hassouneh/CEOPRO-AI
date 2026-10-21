-- Marketing image gallery: every image made for a campaign is kept as an
-- asset (format / aspect ratio, prompt, how it was made, the channel it is
-- meant for), instead of a regenerated image replacing and deleting the
-- previous one. campaigns.generated_image_key stays the image ATTACHED to the
-- campaign (the one its post uses); an asset is attached when its image_key
-- equals it, so there is a single source of truth for that.
--
-- provider / model record which free provider served an AI image, for
-- operators and cost reconciliation only - the API never returns them to a
-- company (the Studio shows "AI" or "designed").
--
-- Additive: one new table, a $0 price row for the self-hosted image server,
-- and a backfill of the one image each existing campaign already has.

CREATE TABLE IF NOT EXISTS campaign_image_assets (
    asset_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES companies(tenant_id) ON DELETE CASCADE,
    campaign_id UUID NOT NULL,
    image_key VARCHAR(512) NOT NULL,
    image_format VARCHAR(20) NOT NULL DEFAULT 'SQUARE'
        CHECK (image_format IN ('SQUARE', 'PORTRAIT', 'STORY', 'LANDSCAPE', 'WIDE')),
    channel VARCHAR(20)
        CHECK (channel IS NULL OR channel IN ('INSTAGRAM', 'FACEBOOK', 'TIKTOK', 'GOOGLE_ADS', 'WEBSITE', 'PRINT', 'OTHER')),
    mode VARCHAR(20) NOT NULL CHECK (mode IN ('ai', 'designed')),
    provider VARCHAR(40),
    model VARCHAR(120),
    prompt TEXT,
    width INTEGER CHECK (width IS NULL OR width > 0),
    height INTEGER CHECK (height IS NULL OR height > 0),
    content_type VARCHAR(40),
    size_bytes BIGINT CHECK (size_bytes IS NULL OR size_bytes >= 0),
    used_reference BOOLEAN NOT NULL DEFAULT FALSE,
    created_by UUID,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_campaign_image_assets_campaign FOREIGN KEY (tenant_id, campaign_id)
        REFERENCES campaigns (tenant_id, campaign_id) ON DELETE CASCADE,
    CONSTRAINT uq_campaign_image_assets_key UNIQUE (tenant_id, image_key)
);

CREATE INDEX IF NOT EXISTS idx_campaign_image_assets_campaign
    ON campaign_image_assets (tenant_id, campaign_id, created_at DESC);

ALTER TABLE campaign_image_assets ENABLE ROW LEVEL SECURITY;
ALTER TABLE campaign_image_assets FORCE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'campaign_image_assets'
                   AND policyname = 'isolation_campaign_image_assets') THEN
        CREATE POLICY isolation_campaign_image_assets ON campaign_image_assets
            FOR ALL USING (tenant_id = get_current_tenant());
    END IF;
END $$;

-- A self-hosted image server (MARKETING_IMAGE_PROVIDERS=local) runs on the
-- operator's own hardware: no provider charge per image.
INSERT INTO provider_cost_schedules (budget_kind, provider, operation, unit, unit_cost_usd, safety_margin, charged_on_failure,
                                     source, configured_by) VALUES
    ('ai', 'local', 'image_generation', 'image', 0, 0, FALSE,
     'Self-hosted image server (LOCAL_IMAGE_BASE_URL) on the operator''s own hardware, no per-image charge',
     'migration 20261029000000')
ON CONFLICT (budget_kind, provider, operation, unit) DO NOTHING;

-- Each existing campaign's one image becomes its first (attached) asset.
INSERT INTO campaign_image_assets (tenant_id, campaign_id, image_key, image_format, mode, prompt, used_reference, created_at)
SELECT c.tenant_id, c.campaign_id, c.generated_image_key, 'SQUARE',
       CASE WHEN c.image_generation_provider = 'designed' THEN 'designed' ELSE 'ai' END,
       c.image_prompt, COALESCE(c.image_generation_used_reference, FALSE),
       COALESCE(c.image_generated_at, c.completed_at, c.requested_at, CURRENT_TIMESTAMP)
FROM campaigns c
WHERE c.generated_image_key IS NOT NULL
ON CONFLICT (tenant_id, image_key) DO NOTHING;
