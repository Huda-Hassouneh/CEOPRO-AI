-- Automated Marketing System (Phase 1): the `campaigns` table already
-- existed (20260807225947_add_campaigns_table.sql) but was never written
-- to by any code - it also had no columns for the actual generated
-- content (copy/headlines/hashtags/CTA/platform), the creative-control
-- inputs, or the derived audience/positioning outputs. This migration
-- extends it with those inputs/outputs and adds campaign_content, one row
-- per generated platform variant, rather than widening `campaigns` itself
-- for a 1-to-many relationship.
--
-- generated_image_key (already on campaigns) is reserved for a FUTURE
-- generated creative asset (posters/banners - Phase 2, needs approval,
-- see the documented-but-dead campaign_image_requested event contract in
-- DATA_OWNERSHIP_AND_CONTRACTS.md). source_image_key here is a different,
-- Phase 1 thing: an optionally uploaded SOURCE product image, stored only
-- - this platform has no vision/image-understanding model of any kind
-- (confirmed repo-wide), so an uploaded image is never analyzed, only
-- kept alongside the campaign for the future phase that will be able to
-- use it.
--
-- audience_summary/positioning_label are Phase 1's honest boundary:
-- positioning_label is derived from real matched-competitor pricing data
-- (the same source dashboard/competitor_pricing.py already reads) -
-- genuine, not fabricated. audience_summary is an LLM-generated
-- suggestion, not measured customer data (this schema has no
-- customer/order demographic tables at all) - stored as plain text, never
-- structured age/geo/income fields that would imply real measurement.
--
-- creative_theme/theme_source/custom_creative_prompt/creative_direction:
-- the visual-creative-direction layer, added after this feature's original
-- scope was extended mid-implementation. creative_theme is one of a fixed
-- set of named visual styles (marketing/creative_direction.py::THEMES);
-- theme_source records whether the tenant picked it explicitly or this
-- platform recommended it (marketing/creative_direction.py::recommend_theme()
-- - a deterministic rule over this tenant's own real category/positioning/
-- market-activity data, not a new ML model). creative_direction is the one
-- LLM-synthesized paragraph combining product understanding + positioning +
-- theme + any custom_creative_prompt into a single structured brief - text
-- only. No image or video is generated from it in Phase 1 (no such model
-- exists in this repo); it exists so a future image/video generation phase
-- has a real, structured input to consume rather than starting from
-- nothing.

ALTER TABLE campaigns
    ADD COLUMN IF NOT EXISTS input_source VARCHAR(10) NOT NULL DEFAULT 'TEXT'
        CONSTRAINT chk_campaigns_input_source CHECK (input_source IN ('PRODUCT', 'TEXT', 'URL')),
    ADD COLUMN IF NOT EXISTS style VARCHAR(50),
    ADD COLUMN IF NOT EXISTS tone VARCHAR(50),
    ADD COLUMN IF NOT EXISTS focus VARCHAR(50),
    ADD COLUMN IF NOT EXISTS strategy_type VARCHAR(30) NOT NULL DEFAULT 'SALES_DRIVEN'
        CONSTRAINT chk_campaigns_strategy_type CHECK (
            strategy_type IN ('SALES_DRIVEN', 'BRAND_AWARENESS', 'STORYTELLING', 'URGENCY', 'INFLUENCER_STYLE')
        ),
    ADD COLUMN IF NOT EXISTS source_text TEXT,
    ADD COLUMN IF NOT EXISTS source_url TEXT,
    ADD COLUMN IF NOT EXISTS source_image_key VARCHAR(512),
    ADD COLUMN IF NOT EXISTS audience_summary TEXT,
    ADD COLUMN IF NOT EXISTS positioning_label VARCHAR(20)
        CONSTRAINT chk_campaigns_positioning_label CHECK (
            positioning_label IS NULL OR positioning_label IN ('BUDGET', 'MID_RANGE', 'PREMIUM')
        ),
    ADD COLUMN IF NOT EXISTS error_message TEXT,
    ADD COLUMN IF NOT EXISTS creative_theme VARCHAR(20)
        CONSTRAINT chk_campaigns_creative_theme CHECK (
            creative_theme IS NULL OR creative_theme IN (
                'LUXURY_PREMIUM', 'MINIMAL_CLEAN', 'MODERN_TECH', 'SOCIAL_TRENDY',
                'BOLD_PROMOTIONAL', 'LIFESTYLE', 'SEASONAL', 'CUSTOM'
            )
        ),
    ADD COLUMN IF NOT EXISTS theme_source VARCHAR(15)
        CONSTRAINT chk_campaigns_theme_source CHECK (
            theme_source IS NULL OR theme_source IN ('RECOMMENDED', 'USER_SELECTED')
        ),
    ADD COLUMN IF NOT EXISTS custom_creative_prompt TEXT,
    ADD COLUMN IF NOT EXISTS creative_direction TEXT;

CREATE TABLE IF NOT EXISTS campaign_content (
    content_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    campaign_id UUID NOT NULL,
    platform VARCHAR(20) NOT NULL
        CONSTRAINT chk_campaign_content_platform CHECK (platform IN ('INSTAGRAM', 'FACEBOOK', 'TIKTOK', 'GOOGLE_ADS')),
    variant_index SMALLINT NOT NULL DEFAULT 1,
    headline TEXT,
    body_copy TEXT NOT NULL,
    hashtags TEXT[] NOT NULL DEFAULT '{}',
    cta TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_campaign_content_campaign_isolated FOREIGN KEY (tenant_id, campaign_id)
        REFERENCES campaigns(tenant_id, campaign_id) ON DELETE CASCADE,
    CONSTRAINT uq_campaign_content_variant UNIQUE (tenant_id, campaign_id, platform, variant_index)
);

CREATE INDEX IF NOT EXISTS idx_campaign_content_tenant_campaign ON campaign_content(tenant_id, campaign_id);

ALTER TABLE campaign_content ENABLE ROW LEVEL SECURITY;
ALTER TABLE campaign_content FORCE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'campaign_content' AND policyname = 'isolation_campaign_content') THEN
        CREATE POLICY isolation_campaign_content ON campaign_content FOR ALL USING (tenant_id = get_current_tenant());
    END IF;
END $$;
